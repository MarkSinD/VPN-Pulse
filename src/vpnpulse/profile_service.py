"""Transactional profile orchestration independent of SSH transport."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import subprocess
from typing import Protocol

from vpnpulse.access_policy import issuance_decision
from vpnpulse.storage.store import SqliteStore


class Provisioner(Protocol):
    def issue(self, *, server_id: str, public_key: str, address: str, idempotency_key: str) -> dict: ...
    def revoke(self, *, server_id: str, public_key: str, idempotency_key: str) -> dict: ...
    def inspect(self, *, server_id: str) -> dict: ...


@dataclass(frozen=True)
class ProfileServiceError(RuntimeError):
    code: str

    def __str__(self) -> str:
        return self.code


class ProfileService:
    def __init__(self, store: SqliteStore, config: dict, deployment: dict, provisioner: Provisioner) -> None:
        self.store, self.config, self.deployment, self.provisioner = store, config, deployment, provisioner

    def issue(self, *, member_id: str, server_id: str, public_key: str, idempotency_key: str) -> dict:
        decision = issuance_decision(self.config, server_id)
        if not decision.allowed:
            raise ProfileServiceError(decision.code or "issuance_disabled")
        server = (self.deployment.get("servers") or {}).get(server_id) or {}
        addresses = list(server.get("addresses") or [])
        if not addresses:
            raise ProfileServiceError("pool_unavailable")
        try:
            reservation = self.store.reserve_profile(member_id, server_id, public_key, addresses,
                                                       idempotency_key=idempotency_key)
        except ValueError as error:
            raise ProfileServiceError(str(error).replace(" ", "_")) from error
        if reservation["replayed"]:
            return {**reservation, "delivery": None}
        operation_id = reservation["operation_id"]
        self.store.set_profile_operation(operation_id, "applying")
        try:
            delivery = self.provisioner.issue(server_id=server_id, public_key=public_key,
                                               address=reservation["address"], idempotency_key=idempotency_key)
        except TimeoutError as error:
            self.store.set_profile_operation(operation_id, "needs_review", error_code="PROVISIONER_TIMEOUT")
            raise ProfileServiceError("provisioner_result_unknown") from error
        except Exception as error:
            hours = int((self.config.get("access") or {}).get("address_quarantine_hours", 24))
            self.store.fail_profile_issue(operation_id, error_code="PROVISIONER_FAILED", quarantine_hours=hours)
            raise ProfileServiceError("provisioner_failed") from error
        self.store.set_profile_operation(operation_id, "applied")
        # Delivery is deliberately ephemeral: the store receives only lifecycle state, never PSK/config.
        self.store.set_profile_operation(operation_id, "delivered")
        return {**reservation, "profile_state": "delivered", "operation_state": "delivered", "delivery": delivery}

    def revoke(self, *, member_id: str, profile_id: str, idempotency_key: str) -> dict:
        try:
            operation = self.store.reserve_profile_revoke(member_id, profile_id, idempotency_key=idempotency_key)
        except ValueError as error:
            raise ProfileServiceError(str(error).replace(" ", "_")) from error
        if operation["replayed"]:
            return {key: value for key, value in operation.items() if key != "public_key"}
        operation_id = operation["operation_id"]
        self.store.set_profile_operation(operation_id, "applying")
        try:
            self.provisioner.revoke(server_id=operation["server_id"], public_key=operation["public_key"],
                                    idempotency_key=idempotency_key)
        except TimeoutError as error:
            self.store.set_profile_operation(operation_id, "needs_review", error_code="PROVISIONER_TIMEOUT")
            raise ProfileServiceError("provisioner_result_unknown") from error
        except Exception as error:
            self.store.set_profile_operation(operation_id, "needs_review", error_code="PROVISIONER_FAILED")
            raise ProfileServiceError("provisioner_failed") from error
        hours = int((self.config.get("access") or {}).get("address_quarantine_hours", 24))
        self.store.release_profile(profile_id, quarantine_hours=hours)
        self.store.set_profile_operation(operation_id, "completed")
        return {"operation_id": operation_id, "operation_state": "completed", "server_id": operation["server_id"],
                "profile_state": "revoked", "replayed": False}

    def reconcile(self, *, server_id: str) -> dict:
        observed = self.provisioner.inspect(server_id=server_id)
        if observed.get("live_checked") is False:
            raise ProfileServiceError("live_inspection_unavailable")
        actual = set(observed.get("live_fingerprints") or observed.get("fingerprints") or [])
        managed = self.store.managed_profile_fingerprints(server_id)
        expected = set(managed)
        # Unknown peers are legacy/unmanaged and are report-only by policy; never remove them here.
        return {"server_id": server_id, "managed": len(expected), "observed": len(actual),
                "missing_managed": sorted(expected - actual), "unmanaged": sorted(actual - expected),
                "ok": not (expected - actual)}

    def process_lifecycle_jobs(self) -> dict:
        processed = failed = 0
        for job in self.store.due_lifecycle_jobs():
            try:
                for profile in self.store.member_profiles(job["member_id"]):
                    if profile["state"] not in {"revoked", "failed"}:
                        self.revoke(member_id=job["member_id"], profile_id=profile["id"],
                                    idempotency_key=f"lifecycle:{job['id']}:{profile['id']}")
                self.store.finish_lifecycle_job(job["id"])
                processed += 1
            except Exception as error:
                self.store.finish_lifecycle_job(job["id"], error=type(error).__name__)
                failed += 1
        return {"processed": processed, "failed": failed}


class SshProvisioner:
    """Calls only the provisioner's forced command; server details come from root-owned deployment JSON."""

    _ALIAS = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

    def __init__(self, deployment: dict, *, timeout_seconds: int = 20) -> None:
        self.deployment = deployment
        self.timeout_seconds = timeout_seconds

    def issue(self, *, server_id: str, public_key: str, address: str, idempotency_key: str) -> dict:
        remote, server = self._call(server_id, {"operation": "issue", "public_key": public_key,
                                               "allowed_ip": address, "idempotency_key": idempotency_key,
                                               "dry_run": False})
        psk = remote.get("preshared_key")
        if not isinstance(psk, str) or not psk:
            raise RuntimeError("provisioner omitted one-time secret")
        return {"address": address, "preshared_key": psk,
                "server_public_key": server["server_public_key"], "endpoint": server["endpoint"],
                "dns": list(server.get("dns") or []), "extra": dict(server.get("profile") or {})}

    def revoke(self, *, server_id: str, public_key: str, idempotency_key: str) -> dict:
        remote, _ = self._call(server_id, {"operation": "revoke", "public_key": public_key,
                                           "idempotency_key": idempotency_key, "dry_run": False})
        return remote

    def inspect(self, *, server_id: str) -> dict:
        remote, _ = self._call(server_id, {"operation": "inspect"})
        return remote

    def _call(self, server_id: str, request: dict) -> tuple[dict, dict]:
        server = (self.deployment.get("servers") or {}).get(server_id) or {}
        alias = server.get("ssh_alias")
        if not isinstance(alias, str) or not self._ALIAS.fullmatch(alias):
            raise ValueError("invalid provisioner ssh alias")
        try:
            result = subprocess.run(
                ["ssh", "-T", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={self.timeout_seconds}",
                 alias, "vpn-pulse-provisioner"],
                input=json.dumps(request, separators=(",", ":")), text=True, capture_output=True,
                timeout=self.timeout_seconds + 5, check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise TimeoutError("provisioner timeout") from error
        if result.returncode != 0:
            raise RuntimeError("provisioner rejected request")
        try:
            remote = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise RuntimeError("invalid provisioner response") from error
        if remote.get("ok") is not True or remote.get("dry_run") is True:
            raise RuntimeError("provisioner did not apply request")
        return remote, server
