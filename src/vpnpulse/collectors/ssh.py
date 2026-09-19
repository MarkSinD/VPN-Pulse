"""SshCollector — a real server through its read-only helper over SSH.

One call per run: `ssh -i <collector key> vpnpulse@<host>` whose forced command is
`deploy/helper/vpn-pulse-helper`; it answers with one JSON document of aggregate facts (see the
helper's header) and the collector turns that into observations:

- one `collector` observation with `metrics_json` per contracts/collector-observation.schema.json
  (connections, resources, profiles, components, service checks, admin attention, diagnostics);
- one `human_activity` observation when at least one peer handshaked within the freshness window —
  members proving the server works; no handshakes is not evidence of anything.

A failed call (SSH, deadline, helper error, unparsable answer) is a `collector` observation with
`result = failure` and an error *code*, so the evaluator sees "the collector could not read the
server" and the administrator gets a finding; nothing about the failure carries a host or a port.
Traffic is the byte delta between two consecutive answers, kept in memory per server.
"""
from __future__ import annotations

import json
import logging
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from vpnpulse.collectors.base import Collected
from vpnpulse.i18n import Translator

log = logging.getLogger("vpnpulse.collectors.ssh")

HELPER_SCHEMA = 1
ACTIVE_24H = 24 * 3600
DISK_PRESSURE_PERCENT = 85  # a 15 GB disk at 79 % is a fact, not a finding; attention starts where action is due
SWAP_PRESSURE_PERCENT = 50
ERROR_CODES = {
    "timeout": "SSH_TIMEOUT",
    "connect": "SSH_UNREACHABLE",
    "auth": "SSH_AUTH_FAILED",
    "hostkey": "SSH_HOST_KEY_MISMATCH",
    "helper": "HELPER_FAILED",
    "invalid": "HELPER_INVALID_ANSWER",
    "dump": "HELPER_DUMP_FAILED",
}


@dataclass(frozen=True)
class SshTarget:
    """Where a helper lives. Never printed: the host is for the SSH command line only."""

    host: str
    key_file: Path
    known_hosts_file: Path
    user: str = "vpnpulse"
    port: int = 22
    timeout_seconds: int = 20

    def command(self) -> list[str]:
        return [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=yes",
            "-o", f"UserKnownHostsFile={self.known_hosts_file}",
            "-o", "IdentitiesOnly=yes",
            "-o", f"ConnectTimeout={max(3, min(self.timeout_seconds - 5, 15))}",
            "-o", "LogLevel=ERROR",
            "-i", str(self.key_file),
            "-p", str(self.port),
            f"{self.user}@{self.host}",
            "vpn-pulse-helper",  # ignored by the forced command; explicit for a non-restricted test account
        ]


@dataclass
class HelperAnswer:
    ok: bool
    payload: dict | None = None
    error_code: str | None = None


Runner = Callable[[list[str], int], subprocess.CompletedProcess]


def _run(command: list[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False, stdin=subprocess.DEVNULL)


def classify_failure(returncode: int, stderr: str) -> str:
    text = stderr.lower()
    if "host key" in text or "remote host identification has changed" in text or "no hostkey" in text:
        return ERROR_CODES["hostkey"]
    if "permission denied" in text or "no supported authentication" in text or "publickey" in text:
        return ERROR_CODES["auth"]
    if returncode == 255 or "connection timed out" in text or "could not resolve" in text or "connection refused" in text or "network is unreachable" in text:
        return ERROR_CODES["connect"]
    return ERROR_CODES["helper"]


def call_helper(target: SshTarget, runner: Runner | None = None) -> HelperAnswer:
    runner = runner or _run
    try:
        completed = runner(target.command(), target.timeout_seconds)
    except subprocess.TimeoutExpired:
        return HelperAnswer(False, error_code=ERROR_CODES["timeout"])
    except OSError as error:  # ssh binary missing and the like: an installation problem, reported as a code
        log.warning("collector ssh failed to start: %s", type(error).__name__)
        return HelperAnswer(False, error_code=ERROR_CODES["helper"])
    if completed.returncode != 0:
        return HelperAnswer(False, error_code=classify_failure(completed.returncode, completed.stderr or ""))
    try:
        payload = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError):
        return HelperAnswer(False, error_code=ERROR_CODES["invalid"])
    if not isinstance(payload, dict) or payload.get("schema") != HELPER_SCHEMA or not isinstance(payload.get("peers"), dict) or not isinstance(payload.get("system"), dict):
        return HelperAnswer(False, error_code=ERROR_CODES["invalid"])
    return HelperAnswer(True, payload=payload)


def _num(value, lo: float | None = 0, hi: float | None = None):
    """A JSON number inside [lo, hi], else None — the helper is trusted for shape, not for sense."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if lo is not None and value < lo:
        return None
    if hi is not None and value > hi:
        return None
    return value


def _kernel_key(name: str) -> tuple:
    """Sort key for Ubuntu kernel names like 5.15.0-191-generic."""
    head = name.split("-generic")[0]
    parts: list[int] = []
    for chunk in head.replace("-", ".").split("."):
        parts.append(int(chunk) if chunk.isdigit() else 0)
    return tuple(parts)


class SshCollector:
    """One server, one helper. `name` is the collector id from collectors.yaml (never the host)."""

    def __init__(
        self,
        server_id: str,
        target: SshTarget,
        *,
        name: str | None = None,
        freshness_seconds: int = 180,
        translator: Translator | None = None,
        runner: Runner | None = None,
    ) -> None:
        self.server_id = server_id
        self.target = target
        self.name = name or f"collector:{server_id}"
        self.freshness = freshness_seconds
        self.i18n = translator or Translator()
        self.runner = runner
        self._last_counters: tuple[datetime, int] | None = None  # (at, rx+tx bytes) for the traffic delta

    # ---------- the Collector protocol ----------
    def collect(self, now: datetime) -> list[Collected]:
        answer = call_helper(self.target, self.runner)
        if not answer.ok:
            log.warning("collector failed", extra={"event": "collector.failed", "details": {"collector": self.name, "code": answer.error_code}})
            metrics = {"service_checks": [{"check": "ssh", "ok": False}], "diagnostics": {"code": answer.error_code, "ssh_ok": False}}
            return [Collected(self.server_id, "collector", "failure", now, metrics, error_code=answer.error_code)]
        payload = answer.payload or {}
        observed_at = self._observed_at(payload, now)
        metrics = self.metrics_from(payload, observed_at)
        out = [Collected(self.server_id, "collector", "success", observed_at, metrics)]
        active = metrics["connections"].get("amneziawg")
        if active:
            out.append(Collected(self.server_id, "human_activity", "success", observed_at, {"connections": {"amneziawg": active}}))
        return out

    def _observed_at(self, payload: dict, now: datetime) -> datetime:
        at = _num(payload.get("observed_at"), 0, None)
        if at is None:
            return now
        observed = datetime.fromtimestamp(at, UTC)
        # a helper clock far from ours is a finding, not the truth: keep within a minute of our own clock
        if abs((observed - now).total_seconds()) > 60:
            return now
        return observed

    # ---------- helper JSON -> contract payload ----------
    def metrics_from(self, payload: dict, observed_at: datetime) -> dict:
        peers = payload.get("peers") or {}
        system = payload.get("system") or {}
        engine = payload.get("engine") or {}
        dns = payload.get("dns")
        errors = [e for e in (payload.get("errors") or []) if isinstance(e, str)]
        ages = [a for a in (peers.get("handshake_ages") or []) if isinstance(a, int) and not isinstance(a, bool)]
        ever = [a for a in ages if a >= 0]
        active_now = sum(1 for a in ever if a <= self.freshness)
        active_24h = sum(1 for a in ever if a <= ACTIVE_24H)
        issued = _num(peers.get("count"), 0, None)
        last_connection = observed_at - timedelta(seconds=min(ever)) if ever else None

        engine_ok = engine.get("ok") is True and "DUMP_FAILED" not in errors
        connections = {"amneziawg": active_now if engine_ok else None}
        resources = {
            "traffic_mbps": self._traffic_mbps(observed_at, peers) if engine_ok else None,
            "cpu_percent": _num(system.get("cpu_percent"), 0, 100),
            "memory_percent": _num(system.get("memory_percent"), 0, 100),
            "swap_percent": _num(system.get("swap_percent"), 0, 100),
            "peak_connections_24h": None,
        }
        profiles = {
            "issued": int(issued) if issued is not None and engine_ok else None,
            "ever_connected": len(ever) if engine_ok else None,
            "active_24h": active_24h if engine_ok else None,
            "last_connection_at": last_connection.isoformat().replace("+00:00", "Z") if last_connection else None,
        }
        components = self._components(payload, system)
        checks = [
            {"check": "ssh", "ok": True},
            {"check": "engine", "ok": engine_ok},
            {"check": "port", "ok": engine.get("listening") if isinstance(engine.get("listening"), bool) else None},
        ]
        if isinstance(dns, dict) and dns.get("configured"):
            checks.append({"check": "dns", "ok": dns.get("resolves") if isinstance(dns.get("resolves"), bool) else None})
            checks.append({"check": "ddns", "ok": dns.get("matches_public_ip") if isinstance(dns.get("matches_public_ip"), bool) else None})
        attention = self._attention(system, resources, engine_ok, dns, errors)
        disk = _num(system.get("disk_percent"), 0, 100)
        diagnostics = {
            "ssh_ok": True,
            "engine_ok": engine_ok,
            "helper_errors": errors,
            "disk_percent": disk,
            "uptime_s": _num(system.get("uptime_s"), 0, None),
            "kernel_running": system.get("kernel") if isinstance(system.get("kernel"), str) else None,
            "kernel_newest_installed": self._newest_kernel(system),
            "congestion_control": system.get("congestion_control") if isinstance(system.get("congestion_control"), str) else None,
        }
        return {
            "connections": connections,
            "resources": resources,
            "profiles": profiles,
            "components": components,
            "service_checks": checks,
            "attention": attention,
            "diagnostics": diagnostics,
        }

    def _traffic_mbps(self, at: datetime, peers: dict) -> float | None:
        rx = _num(peers.get("rx_bytes"), 0, None)
        tx = _num(peers.get("tx_bytes"), 0, None)
        if rx is None or tx is None:
            return None
        total = int(rx) + int(tx)
        previous, self._last_counters = self._last_counters, (at, total)
        if previous is None:
            return None
        seconds = (at - previous[0]).total_seconds()
        if seconds <= 0 or total < previous[1]:  # counters reset (interface restarted): no rate this run
            return None
        return round((total - previous[1]) * 8 / seconds / 1_000_000, 2)

    def _components(self, payload: dict, system: dict) -> list[dict]:
        kind = payload.get("kind")
        version = system.get("awg_version") if isinstance(system.get("awg_version"), str) and system.get("awg_version") else None
        components = []
        if kind == "awg-host":
            components.append({"id": "amneziawg", "name": "AmneziaWG", "version": (version or "")[:32] or None, "note_key": "server.software.kernel", "note": None})
        elif kind == "awg-docker":
            components.append({"id": "amneziawg", "name": "AmneziaWG", "version": (version or "")[:32] or None, "note_key": "server.software.docker", "note": None})
        cc = system.get("congestion_control")
        if isinstance(cc, str) and cc:
            components.append({"id": "tuning", "name": cc.upper()[:40], "version": None, "note_key": "server.software.tuning", "note": None})
        dns = payload.get("dns")
        if isinstance(dns, dict) and dns.get("configured"):
            components.append({"id": "ddns", "name": "DDNS", "version": None, "note_key": "server.software.ddns", "note": None})
        return components[:12]

    def _newest_kernel(self, system: dict) -> str | None:
        installed = [k for k in (system.get("kernels_installed") or []) if isinstance(k, str) and k]
        return max(installed, key=_kernel_key) if installed else None

    def _attention(self, system: dict, resources: dict, engine_ok: bool, dns, errors: list[str]) -> list[dict]:
        items: list[dict] = []

        def add(severity: str, code: str, **params) -> None:
            items.append({"severity": severity, "code": code, "message": {lang: self.i18n.t(lang, f"attention.{code}", **params)[:240] for lang in ("ru", "en")}})

        running = system.get("kernel") if isinstance(system.get("kernel"), str) else None
        newest = self._newest_kernel(system)
        built = {k for k in (system.get("dkms_built_for") or []) if isinstance(k, str)}
        module = system.get("dkms_module") if isinstance(system.get("dkms_module"), str) else ""
        if module and newest and running and newest != running and newest not in built:
            add("high", "KERNEL_MODULE_MISMATCH")
        if not engine_ok:
            add("high", "ENGINE_UNREADABLE")
        disk = _num(system.get("disk_percent"), 0, 100)
        swap = resources.get("swap_percent")
        if (disk is not None and disk >= DISK_PRESSURE_PERCENT) or (swap is not None and swap >= SWAP_PRESSURE_PERCENT):
            add("medium", "DISK_PRESSURE", disk=int(disk) if disk is not None else "?", swap=int(swap) if swap is not None else "?")
        if isinstance(dns, dict) and dns.get("configured") and dns.get("matches_public_ip") is False:
            add("medium", "DDNS_MISMATCH")
        cc = system.get("congestion_control")
        if isinstance(cc, str) and cc and cc != "bbr":
            add("low", "TUNING_LOST", cc=cc)
        return items[:20]
