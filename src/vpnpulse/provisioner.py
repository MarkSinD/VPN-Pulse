"""Narrow forced-command boundary for VPN peer provisioning.

The first delivery is deliberately read-only: inspect and issue/revoke dry-runs are usable, while
real writes require both a later adapter implementation and ``writes_enabled``. Paths and commands
come only from the root-owned local configuration, never from SSH input.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import ipaddress
import json
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PUBLIC_KEY = re.compile(r"^[A-Za-z0-9+/]{42}[AEIMQUYcgkosw048]=$")


class ProvisionerError(ValueError):
    pass


@dataclass(frozen=True)
class Peer:
    public_key: str
    fingerprint: str
    allowed_ips: tuple[str, ...]
    preshared_key: str | None = None


def fingerprint(public_key: str) -> str:
    return hashlib.sha256(public_key.encode()).hexdigest()[:12]


def parse_awg_config(text: str) -> list[Peer]:
    peers: list[Peer] = []
    current_key: str | None = None
    current_ips: tuple[str, ...] = ()
    current_psk: str | None = None
    section = ""
    for raw in text.splitlines() + ["[end]"]:
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            if section == "Peer":
                if not current_key:
                    raise ProvisionerError("peer without public key")
                peers.append(Peer(current_key, fingerprint(current_key), current_ips, current_psk))
            section = line[1:-1]
            current_key, current_ips, current_psk = None, (), None
            continue
        if section != "Peer" or not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if key == "PublicKey":
            if not PUBLIC_KEY.fullmatch(value):
                raise ProvisionerError("invalid peer public key")
            current_key = value
        elif key == "AllowedIPs":
            values = tuple(part.strip() for part in value.split(","))
            for item in values:
                ipaddress.ip_network(item, strict=False)
            current_ips = values
        elif key == "PresharedKey":
            if not PUBLIC_KEY.fullmatch(value):
                raise ProvisionerError("invalid peer preshared key")
            current_psk = value
    return peers


def validate_clients_table(value: Any) -> int:
    if not isinstance(value, list):
        raise ProvisionerError("clientsTable must be a JSON list")
    client_ids: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            raise ProvisionerError("clientsTable entries must be objects")
        client_id = item.get("clientId")
        if not isinstance(client_id, str) or not PUBLIC_KEY.fullmatch(client_id):
            raise ProvisionerError("clientsTable entry has invalid clientId")
        if client_id in client_ids:
            raise ProvisionerError("clientsTable contains duplicate clientId")
        client_ids.add(client_id)
    return len(value)


@contextlib.contextmanager
def _locked(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        try:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except ImportError:  # tests on Windows; production is Linux
            pass
        yield
    finally:
        handle.close()


def _atomic_write(path: Path, content: str) -> None:
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with open(fd, "w", encoding="utf-8", newline="\n") as target:
            target.write(content)
            target.flush()
        Path(name).chmod(mode)
        Path(name).replace(path)
    finally:
        Path(name).unlink(missing_ok=True)


def _target_path(config: dict, value: str) -> str:
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ProvisionerError("target path must be absolute")
    return str(path).replace("\\", "/")


def _read_target(config: dict, value: str) -> str:
    path = _target_path(config, value)
    container = config.get("container")
    if not container:
        return Path(path).read_text(encoding="utf-8")
    result = subprocess.run(["docker", "exec", str(container), "cat", path], capture_output=True,
                            text=True, timeout=15, check=False)
    if result.returncode != 0:
        raise ProvisionerError("container target is unreadable")
    return result.stdout


def _write_target(config: dict, value: str, content: str) -> None:
    path = _target_path(config, value)
    container = config.get("container")
    if not container:
        _atomic_write(Path(path), content); return
    fd, local = tempfile.mkstemp(prefix="vpn-pulse-target-")
    remote = f"/tmp/vpn-pulse-target-{secrets.token_hex(8)}"
    try:
        with open(fd, "w", encoding="utf-8", newline="\n") as target:
            target.write(content); target.flush()
        Path(local).chmod(0o600)
        copied = subprocess.run(["docker", "cp", local, f"{container}:{remote}"], capture_output=True,
                                text=True, timeout=15, check=False)
        moved = subprocess.run(["docker", "exec", str(container), "mv", remote, path], capture_output=True,
                               text=True, timeout=15, check=False) if copied.returncode == 0 else copied
        if moved.returncode != 0:
            raise ProvisionerError("container target write failed")
    finally:
        Path(local).unlink(missing_ok=True)
        subprocess.run(["docker", "exec", str(container), "rm", "-f", remote], capture_output=True,
                       timeout=10, check=False)


def _backup_target(config: dict, value: str, stamp: str) -> None:
    path = _target_path(config, value)
    backup = f"{path}.bak-{stamp}"
    container = config.get("container")
    if container:
        result = subprocess.run(["docker", "exec", str(container), "cp", "-p", path, backup],
                                capture_output=True, text=True, timeout=15, check=False)
        if result.returncode != 0:
            raise ProvisionerError("container backup failed")
    else:
        shutil.copy2(path, backup)


def _without_peer(text: str, public_key: str) -> tuple[str, bool]:
    lines = text.splitlines(keepends=True)
    sections: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.strip().startswith("[") and current:
            sections.append(current); current = []
        current.append(line)
    if current:
        sections.append(current)
    kept, removed = [], False
    for section in sections:
        joined = "".join(section)
        if section[0].strip() == "[Peer]" and re.search(rf"(?m)^\s*PublicKey\s*=\s*{re.escape(public_key)}\s*$", joined):
            removed = True
        else:
            kept.append(joined)
    return "".join(kept).rstrip() + "\n", removed


def _peer_block(public_key: str, psk: str, allowed_ip: str) -> str:
    return f"\n[Peer]\nPublicKey = {public_key}\nPresharedKey = {psk}\nAllowedIPs = {allowed_ip}\n"


def _update_clients_table(value: list, operation: str, public_key: str, allowed_ip: str | None) -> list:
    retained = [item for item in value if item.get("clientId") != public_key]
    if operation == "issue":
        retained.append({"clientId": public_key, "userData": {"allowedIps": allowed_ip,
                         "clientName": f"vpn-pulse-{fingerprint(public_key)}",
                         "creationDate": datetime.now(timezone.utc).strftime("%a %b %d %H:%M:%S %Y"),
                         "dataReceived": "0 B", "dataSent": "0 B", "latestHandshake": "never"}})
    return retained


def _run_live(config: dict, operation: str, public_key: str, allowed_ip: str | None, psk: str | None) -> None:
    prefix = config.get("live_command")
    if not isinstance(prefix, list) or not prefix or not all(isinstance(v, str) and v for v in prefix):
        raise ProvisionerError("live_command must be a fixed string array")
    command = [*prefix, "peer", public_key]
    temp_name = None
    container_temp = None
    try:
        if operation == "issue":
            fd, temp_name = tempfile.mkstemp(prefix="vpn-pulse-psk-")
            with open(fd, "w", encoding="ascii") as target:
                target.write(psk or "")
            Path(temp_name).chmod(0o600)
            psk_path = temp_name
            container = config.get("container")
            if container:
                if not isinstance(container, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", container):
                    raise ProvisionerError("invalid container name")
                container_temp = f"/tmp/vpn-pulse-psk-{secrets.token_hex(8)}"
                copied = subprocess.run(["docker", "cp", temp_name, f"{container}:{container_temp}"],
                                        capture_output=True, text=True, timeout=15, check=False)
                if copied.returncode != 0:
                    raise ProvisionerError("container PSK copy failed")
                psk_path = container_temp
            command += ["preshared-key", psk_path, "allowed-ips", str(allowed_ip)]
        else:
            command += ["remove"]
        result = subprocess.run(command, capture_output=True, text=True, timeout=15, check=False)
        if result.returncode != 0:
            raise ProvisionerError("live apply failed")
    finally:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)
        if container_temp:
            subprocess.run(["docker", "exec", str(config["container"]), "rm", "-f", container_temp],
                           capture_output=True, timeout=10, check=False)


def _live_fingerprints(config: dict[str, Any]) -> list[str] | None:
    command = config.get("inspect_command")
    if command is None:
        return None
    if not isinstance(command, list) or not command or not all(isinstance(v, str) and v for v in command):
        raise ProvisionerError("inspect_command must be a fixed string array")
    result = subprocess.run(command, capture_output=True, text=True, timeout=15, check=False)
    if result.returncode != 0:
        raise ProvisionerError("live inspect failed")
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise ProvisionerError("live inspect returned no interface row")
    peers: list[str] = []
    for line in lines[1:]:
        fields = line.split("\t")
        if not fields or not PUBLIC_KEY.fullmatch(fields[0]):
            raise ProvisionerError("live inspect returned invalid peer data")
        peers.append(fingerprint(fields[0]))
    if len(peers) != len(set(peers)):
        raise ProvisionerError("live inspect returned duplicate peers")
    return sorted(peers)


def _apply(request: dict[str, Any], config: dict[str, Any], config_path: Path,
           table_path: Path | None) -> dict[str, Any]:
    operation, public_key = request["operation"], request["public_key"]
    allowed_ip = request.get("allowed_ip")
    lock_path = Path(config.get("lock_file") or f"{config_path}.vpn-pulse.lock")
    journal_path = Path(config.get("journal_file") or f"{config_path}.vpn-pulse-journal.json")
    with _locked(lock_path):
        journal = json.loads(journal_path.read_text(encoding="utf-8")) if journal_path.exists() else {}
        idem = request["idempotency_key"]
        if idem in journal:
            return {**journal[idem], "replayed": True}
        original = _read_target(config, str(config_path))
        peers = parse_awg_config(original)
        exists = any(peer.public_key == public_key for peer in peers)
        if (operation == "issue" and exists) or (operation == "revoke" and not exists):
            response = {"ok": True, "operation": operation, "fingerprint": fingerprint(public_key),
                        "changed": False}
            journal[idem] = response
            _atomic_write(journal_path, json.dumps(journal, sort_keys=True, separators=(",", ":")) + "\n")
            return response
        table_original = _read_target(config, str(table_path)) if table_path else None
        table = json.loads(table_original) if table_original is not None else None
        if table is not None:
            validate_clients_table(table)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        _backup_target(config, str(config_path), stamp)
        if table_path:
            _backup_target(config, str(table_path), stamp)
        psk = base64.b64encode(secrets.token_bytes(32)).decode("ascii") if operation == "issue" else None
        changed_config = original.rstrip() + _peer_block(public_key, psk or "", str(allowed_ip)) if operation == "issue" else _without_peer(original, public_key)[0]
        try:
            _write_target(config, str(config_path), changed_config)
            if table_path and table is not None:
                changed_table = _update_clients_table(table, operation, public_key, allowed_ip)
                _write_target(config, str(table_path), json.dumps(changed_table, ensure_ascii=False, indent=2) + "\n")
            _run_live(config, operation, public_key, allowed_ip, psk)
            readback = parse_awg_config(_read_target(config, str(config_path)))
            present = any(peer.public_key == public_key for peer in readback)
            if present != (operation == "issue"):
                raise ProvisionerError("persistent read-back failed")
        except Exception:
            _write_target(config, str(config_path), original)
            if table_path and table_original is not None:
                _write_target(config, str(table_path), table_original)
            try:
                inverse = "revoke" if operation == "issue" else "issue"
                old_peer = next((p for p in peers if p.public_key == public_key), None)
                rollback_psk = psk if operation == "issue" else (old_peer.preshared_key if old_peer else None)
                _run_live(config, inverse, public_key, old_peer.allowed_ips[0] if old_peer and old_peer.allowed_ips else allowed_ip, rollback_psk)
            except Exception:
                pass
            raise
        response = {"ok": True, "operation": operation, "fingerprint": fingerprint(public_key),
                    "changed": True}
        journal[idem] = response
        _atomic_write(journal_path, json.dumps(journal, sort_keys=True, separators=(",", ":")) + "\n")
        return {**response, **({"preshared_key": psk} if psk else {})}


def validate_request(request: dict[str, Any]) -> dict[str, Any]:
    allowed = {"operation", "public_key", "allowed_ip", "dry_run", "idempotency_key"}
    if set(request) - allowed:
        raise ProvisionerError("unknown request field")
    operation = request.get("operation")
    if operation not in {"inspect", "issue", "revoke"}:
        raise ProvisionerError("unsupported operation")
    if operation in {"issue", "revoke"}:
        public_key = request.get("public_key")
        if not isinstance(public_key, str) or not PUBLIC_KEY.fullmatch(public_key):
            raise ProvisionerError("invalid public key")
        key = request.get("idempotency_key")
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", key):
            raise ProvisionerError("invalid idempotency_key")
    if operation == "issue":
        allowed_ip = request.get("allowed_ip")
        try:
            network = ipaddress.ip_network(str(allowed_ip), strict=True)
        except ValueError as error:
            raise ProvisionerError("invalid allowed_ip") from error
        if network.prefixlen != network.max_prefixlen:
            raise ProvisionerError("allowed_ip must describe one host")
    return request


def execute(request: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    request = validate_request(request)
    config_path = Path(config["persistent_config"])
    peers = parse_awg_config(_read_target(config, str(config_path)))
    table_count = None
    if config.get("clients_table"):
        table_count = validate_clients_table(json.loads(_read_target(config, config["clients_table"])))
    operation = request["operation"]
    if operation == "inspect":
        persistent = sorted(peer.fingerprint for peer in peers)
        live = _live_fingerprints(config)
        return {"ok": True, "peer_count": len(peers), "clients_table_count": table_count,
                "fingerprints": persistent, "live_checked": live is not None,
                "live_peer_count": len(live) if live is not None else None,
                "live_fingerprints": live,
                "persistent_live_match": live == persistent if live is not None else None}
    fp = fingerprint(request["public_key"])
    if request.get("dry_run") is True or config.get("writes_enabled") is not True:
        return {"ok": True, "dry_run": True, "operation": operation, "fingerprint": fp,
                "would_change": (fp not in {p.fingerprint for p in peers}) if operation == "issue"
                                else (fp in {p.fingerprint for p in peers})}
    return _apply(request, config, config_path, Path(config["clients_table"]) if config.get("clients_table") else None)


def forced_command(original_command: str, *, config_path: Path = Path("/etc/vpn-pulse-provisioner/config.json")) -> dict[str, Any]:
    if original_command != "vpn-pulse-provisioner":
        raise ProvisionerError("forced command required")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    raw = sys.stdin.buffer.read(65_537)
    if not raw or len(raw) > 65_536:
        raise ProvisionerError("request size invalid")
    request = json.loads(raw)
    if not isinstance(request, dict):
        raise ProvisionerError("request must be an object")
    return execute(request, config)
