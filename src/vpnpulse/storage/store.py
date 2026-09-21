"""SqliteStore — everything the API writes, in the database (no in-memory state in the app).

- web sessions: `web_sessions` keyed by the SHA-256 of the cookie token; the Telegram user id is
  stored only as a peppered hash
- enrollment codes: `probe_enrollments` keyed by the SHA-256 of the one-time code (10 minutes,
  single use)
- probes: `probes` with the SHA-256 of the bearer token and a short prefix for support
- reports: `probe_reports` (idempotent by report_id) turned into `observations` per target
  server, which the read model and the evaluator consume
- administrator note: `admin_notes` (active / replaced / deleted)
- product analytics: `product_events` through SqliteAnalyticsRepository
- audit: `audit_entries` for every administrator action
- retention: `sweep()` deletes what the configuration says has expired

Secrets never touch the database in clear text; tokens are returned once to the caller.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from vpnpulse.analytics import SqliteAnalyticsRepository
from vpnpulse.auth import Identity, Session

PROTOCOL_OF_TYPE = {"awg-host": "amneziawg", "awg-docker": "amneziawg", "hiddify": "xray_reality"}
SOURCE_OF_PROBE = {"pc": "pc", "android": "mobile", "abroad": "abroad", "watchdog": "collector"}
SCOPE_OF_PROBE = {"pc": "country", "android": "country", "abroad": "abroad", "watchdog": "all"}
FULL_TEST_CHECKS = {"handshake", "https"}
PROBE_CHECKS = {"pc": ["control_internet", "handshake", "https"], "android": ["dns", "tcp"], "abroad": ["handshake"], "watchdog": []}


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z") if value else None


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _sha(value: str) -> bytes:
    return hashlib.sha256(value.encode()).digest()


def sync_servers(connection: sqlite3.Connection, config: dict, now: datetime | None = None) -> None:
    """Mirror config servers/protocols into the tables that reference them (config stays the source of truth).

    Idempotent; a server that left the configuration is disabled, never deleted — its history stays.
    """
    now = now or datetime.now(UTC)
    configured = {s["id"] for s in config.get("servers", [])}
    with connection:
        for order, s in enumerate(config.get("servers", [])):
            connection.execute(
                """
                INSERT INTO servers(id, public_id, type, enabled, display_order, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET type=excluded.type, enabled=excluded.enabled, display_order=excluded.display_order, updated_at=excluded.updated_at
                """,
                (s["id"], s["id"], s["type"], 1 if s.get("enabled", True) else 0, order + 1, _iso(now), _iso(now)),
            )
            kind = PROTOCOL_OF_TYPE.get(s["type"], "amneziawg")
            connection.execute(
                """
                INSERT INTO protocols(id, server_id, kind, label_key, enabled, coverage_state, created_at, updated_at) VALUES (?, ?, ?, ?, 1, 'complete', ?, ?)
                ON CONFLICT(id) DO UPDATE SET enabled=1, updated_at=excluded.updated_at
                """,
                (f"{s['id']}:{kind}", s["id"], kind, f"server.protocol.{kind}", _iso(now), _iso(now)),
            )
        for (server_id,) in connection.execute("SELECT id FROM servers WHERE enabled = 1").fetchall():
            if server_id not in configured:
                connection.execute("UPDATE servers SET enabled = 0, updated_at = ? WHERE id = ?", (_iso(now), server_id))


class SqliteStore:
    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        analytics_schema: Path,
        config: dict | None = None,
        pepper: str = "",
        now: Callable[[], datetime] | None = None,
        session_minutes: int = 30,
        enrollment_minutes: int = 10,
    ) -> None:
        self.db = connection
        self.config = config or {}
        self.pepper = pepper
        self.now = now or (lambda: datetime.now(UTC))
        self.session_ttl = timedelta(minutes=session_minutes)
        self.enrollment_ttl = timedelta(minutes=enrollment_minutes)
        retention = self.config.get("retention") or {}
        self.retention = {
            "observations_days": retention.get("observations_days", 7),
            "events_days": retention.get("events_days", 180),
            "analytics_raw_days": retention.get("analytics_raw_days", 30),
            "audit_days": retention.get("audit_days", 365),
        }
        monitoring = self.config.get("monitoring") or {}
        self.freshness = timedelta(seconds=monitoring.get("freshness_seconds", 180))
        self.analytics = SqliteAnalyticsRepository(analytics_schema, connection, retention_days=self.retention["analytics_raw_days"])

    # ---------- sessions ----------
    def create_session(self, identity: Identity, now: datetime | None = None) -> Session:
        now = now or self.now()
        token = secrets.token_urlsafe(32)
        expires = now + self.session_ttl
        with self.db:
            self.db.execute(
                "INSERT INTO web_sessions VALUES (?, ?, ?, ?, ?, ?, NULL)",
                (_sha(token), identity.role, _sha(f"{self.pepper}:{identity.telegram_user_id}"), _iso(now), _iso(expires), _iso(now)),
            )
        return Session(token, identity, expires)

    def get_session(self, token: str | None, now: datetime | None = None) -> Session | None:
        if not token:
            return None
        now = now or self.now()
        row = self.db.execute("SELECT role, expires_at, revoked_at FROM web_sessions WHERE id_hash = ?", (_sha(token),)).fetchone()
        if row is None or row[2] is not None:
            return None
        expires = _dt(row[1])
        if expires is None or expires <= now:
            return None
        # the Telegram id is stored only as a hash; the session carries the role, which is all routes need
        return Session(token, Identity(0, row[0]), expires)

    def revoke_session(self, token: str | None, now: datetime | None = None) -> None:
        if not token:
            return
        with self.db:
            self.db.execute("UPDATE web_sessions SET revoked_at = ? WHERE id_hash = ? AND revoked_at IS NULL", (_iso(now or self.now()), _sha(token)))

    # ---------- enrollment codes ----------
    def create_enrollment(self, kind: str, capabilities: list[str], created_by: str, now: datetime | None = None, via_server_id: str | None = None) -> tuple[str, datetime]:
        now = now or self.now()
        code = secrets.token_urlsafe(24)
        expires = now + self.enrollment_ttl
        with self.db:
            self.db.execute(
                "INSERT INTO probe_enrollments(code_hash, kind, capabilities_json, expires_at, used_at, created_by_hash, created_at, via_server_id) VALUES (?, ?, ?, ?, NULL, ?, ?, ?)",
                (_sha(code), kind, json.dumps(capabilities), _iso(expires), _sha(f"{self.pepper}:{created_by}"), _iso(now), via_server_id),
            )
        return code, expires

    def consume_enrollment(self, code: str, now: datetime | None = None) -> dict | None:
        now = now or self.now()
        row = self.db.execute("SELECT kind, capabilities_json, expires_at, used_at, via_server_id FROM probe_enrollments WHERE code_hash = ?", (_sha(code),)).fetchone()
        if row is None or row[3] is not None:
            return None
        expires = _dt(row[2])
        if expires is None or expires <= now:
            return None
        with self.db:
            self.db.execute("UPDATE probe_enrollments SET used_at = ? WHERE code_hash = ?", (_iso(now), _sha(code)))
        enrollment = {"kind": row[0], "capabilities": json.loads(row[1])}
        if row[4] is not None:
            enrollment["via_server_id"] = row[4]
        return enrollment

    # ---------- probes ----------
    def register_probe(self, kind: str, capabilities: list[str], agent_version: str, now: datetime | None = None, via_server_id: str | None = None) -> tuple[str, dict]:
        now = now or self.now()
        token = secrets.token_urlsafe(32)
        public_id = f"{kind}-{uuid.uuid4().hex[:12]}"
        with self.db:
            self.db.execute(
                "INSERT INTO probes(id, public_id, kind, status, capabilities_json, token_hash, token_prefix, schema_major, agent_version, enrolled_at, last_seen_at, revoked_at, via_server_id) VALUES (?, ?, ?, 'active', ?, ?, ?, 1, ?, ?, NULL, NULL, ?)",
                (public_id, public_id, kind, json.dumps(capabilities), _sha(token), token[:6], agent_version, _iso(now), via_server_id),
            )
        return token, self.probe_summary(public_id)

    def probe_by_token(self, token: str) -> dict | None:
        row = self.db.execute("SELECT public_id, kind, status FROM probes WHERE token_hash = ?", (_sha(token),)).fetchone()
        if row is None or row[2] == "revoked":
            return None
        return self.probe_summary(row[0])

    def probe_summary(self, public_id: str) -> dict | None:
        row = self.db.execute(
            "SELECT id, public_id, kind, status, capabilities_json, agent_version, last_seen_at, via_server_id FROM probes WHERE public_id = ?", (public_id,)
        ).fetchone()
        if row is None:
            return None
        report = self.db.execute(
            "SELECT route_verified, network_type FROM probe_reports WHERE probe_id = ? ORDER BY received_at DESC LIMIT 1", (row[0],)
        ).fetchone()
        return {
            "id": row[1], "kind": row[2], "status": row[3], "last_seen_at": _iso(_dt(row[6])),
            "capabilities": json.loads(row[4] or "[]"), "agent_version": row[5],
            "route_verified": bool(report[0]) if report else None, "queued_reports": None,
            "network_type": report[1] if report else None, "via_server_id": row[7], "_internal_id": row[0],
        }

    def list_probes(self) -> list[dict]:
        rows = self.db.execute("SELECT public_id FROM probes ORDER BY enrolled_at").fetchall()
        out = []
        for (public_id,) in rows:
            summary = self.probe_summary(public_id)
            summary.pop("_internal_id", None)
            out.append(summary)
        return out

    def revoke_probe(self, public_id: str, now: datetime | None = None) -> bool:
        with self.db:
            cursor = self.db.execute(
                "UPDATE probes SET status = 'revoked', revoked_at = ? WHERE public_id = ? AND status != 'revoked'", (_iso(now or self.now()), public_id)
            )
        return cursor.rowcount > 0

    def probe_config(self, kind: str, via_server_id: str | None = None) -> dict:
        monitoring = self.config.get("monitoring") or {}
        targets = [{"id": s["id"], "checks": PROBE_CHECKS.get(kind, [])} for s in self.config.get("servers", []) if s.get("enabled", True) and s["id"] != via_server_id]
        return {"schema_version": 1, "interval_seconds": int(monitoring.get("pc_target_interval_seconds", 60)), "targets": targets}

    # ---------- reports → observations ----------
    def accept_report(self, probe: dict, payload: dict, now: datetime | None = None) -> tuple[bool, int]:
        """Store one report idempotently. Returns (duplicate, observations written)."""
        now = now or self.now()
        network = payload["network"]
        results = payload["results"]
        summary = "success" if all(r["result"] == "success" for r in results) else "failure" if any(r["result"] == "failure" for r in results) else "not_run"
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        with self.db:
            cursor = self.db.execute(
                "INSERT OR IGNORE INTO probe_reports VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (payload["report_id"], probe["_internal_id"], payload["schema_version"], payload["agent_version"], _iso(_dt(payload["observed_at"])),
                 _iso(now), network["type"], network["ip_family"], 1 if network["route_verified"] else 0, hashlib.sha256(body).digest(), summary,
                 next((r.get("not_run_reason") for r in results if r.get("not_run_reason")), None)),
            )
            if cursor.rowcount == 0:
                existing = self.db.execute("SELECT payload_hash FROM probe_reports WHERE report_id = ?", (payload["report_id"],)).fetchone()
                if existing is not None and not hmac.compare_digest(existing[0], hashlib.sha256(body).digest()):
                    raise ValueError("report_id already exists with a different payload")
                return True, 0
            known = {row[0] for row in self.db.execute("SELECT id FROM servers").fetchall()}
            observed_at = _dt(payload["observed_at"]) or now
            written = 0
            by_target: dict[str, list[dict]] = {}
            for item in results:
                by_target.setdefault(item["target_id"], []).append(item)
            for target_id, items in by_target.items():
                if target_id not in known:
                    continue  # a target that is not one of our servers is ignored, never invented
                checks = {item["check"]: item["result"] for item in items}
                ran = [item for item in items if item["result"] != "not_run"]
                if not ran:
                    result = "not_run"
                elif any(item["result"] == "failure" for item in ran):
                    result = "failure"
                else:
                    result = "success"
                control = checks.get("control_internet")
                metrics = {
                    "checks": checks,
                    "full_vpn_test": FULL_TEST_CHECKS <= set(checks),
                    "control_internet_ok": None if control is None else control == "success",
                    "route_verified": bool(network["route_verified"]),
                    "network_type": network["type"],
                }
                if probe["kind"] == "abroad":
                    metrics["via_server_id"] = probe.get("via_server_id")
                error = next((item.get("error_code") or item.get("not_run_reason") for item in items if item["result"] != "success" and (item.get("error_code") or item.get("not_run_reason"))), None)
                self.db.execute(
                    "INSERT INTO observations VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)",
                    (str(uuid.uuid5(uuid.NAMESPACE_URL, f"report:{payload['report_id']}:{target_id}")), target_id, SOURCE_OF_PROBE.get(probe["kind"], probe["kind"]),
                     SCOPE_OF_PROBE.get(probe["kind"], "country"), _iso(observed_at), _iso(now), result, _iso(observed_at + self.freshness),
                     "sufficient" if network["route_verified"] else "partial", json.dumps(metrics, separators=(",", ":")), error, payload["report_id"]),
                )
                written += 1
            self.db.execute("UPDATE probes SET last_seen_at = ? WHERE id = ?", (_iso(now), probe["_internal_id"]))
        return False, written

    # ---------- administrator note ----------
    def put_note(self, text: str, expires_at: datetime | None, server_id: str | None, created_by_role: str, now: datetime | None = None) -> dict:
        now = now or self.now()
        note_id = str(uuid.uuid4())
        with self.db:
            self.db.execute("UPDATE admin_notes SET status = 'replaced', updated_at = ? WHERE status = 'active'", (_iso(now),))
            self.db.execute(
                "INSERT INTO admin_notes VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?)",
                (note_id, server_id, text, _iso(now), _iso(expires_at), created_by_role, _iso(now), _iso(now)),
            )
        return {"id": note_id, "server_id": server_id, "text": text, "expires_at": _iso(expires_at), "created_at": _iso(now)}

    def delete_note(self, now: datetime | None = None) -> bool:
        with self.db:
            cursor = self.db.execute("UPDATE admin_notes SET status = 'deleted', updated_at = ? WHERE status = 'active'", (_iso(now or self.now()),))
        return cursor.rowcount > 0

    def note_state(self, now: datetime | None = None) -> tuple[str, dict | None]:
        """('none', None) when nobody ever wrote a note; otherwise ('active', note) or ('cleared', None)."""
        now = now or self.now()
        if self.db.execute("SELECT count(*) FROM admin_notes").fetchone()[0] == 0:
            return "none", None
        row = self.db.execute(
            "SELECT id, server_id, text, expires_at, created_at FROM admin_notes WHERE status = 'active' AND starts_at <= ? AND (expires_at IS NULL OR expires_at > ?) ORDER BY created_at DESC LIMIT 1",
            (_iso(now), _iso(now)),
        ).fetchone()
        if row is None:
            return "cleared", None
        return "active", {"id": row[0], "server_id": row[1], "text": row[2], "expires_at": _iso(_dt(row[3])), "created_at": _iso(_dt(row[4]))}

    # ---------- audit ----------
    def audit(self, *, actor: str, role: str, action: str, target_type: str, target_id: str, result: str = "ok", details: dict | None = None, trace_id: str | None = None, now: datetime | None = None) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO audit_entries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), _sha(f"{self.pepper}:{actor}"), role, action, target_type, target_id, result, _iso(now or self.now()), trace_id or uuid.uuid4().hex, json.dumps(details or {}, separators=(",", ":"))),
            )

    # ---------- retention ----------
    def sweep(self, now: datetime | None = None) -> dict[str, int]:
        now = now or self.now()
        counts: dict[str, int] = {}
        with self.db:
            counts["sessions"] = self.db.execute("DELETE FROM web_sessions WHERE expires_at <= ? OR revoked_at IS NOT NULL", (_iso(now),)).rowcount
            counts["enrollments"] = self.db.execute("DELETE FROM probe_enrollments WHERE expires_at <= ? OR used_at IS NOT NULL", (_iso(now),)).rowcount
            horizon = _iso(now - timedelta(days=self.retention["observations_days"]))
            counts["observations"] = self.db.execute("DELETE FROM observations WHERE observed_at < ?", (horizon,)).rowcount
            counts["reports"] = self.db.execute(
                "DELETE FROM probe_reports WHERE observed_at < ? AND report_id NOT IN (SELECT probe_report_id FROM observations WHERE probe_report_id IS NOT NULL)", (horizon,)
            ).rowcount
            counts["events"] = self.db.execute("DELETE FROM events WHERE occurred_at < ?", (_iso(now - timedelta(days=self.retention["events_days"])),)).rowcount
            counts["audit"] = self.db.execute("DELETE FROM audit_entries WHERE occurred_at < ?", (_iso(now - timedelta(days=self.retention["audit_days"])),)).rowcount
        counts["analytics"] = self.analytics.delete_expired(now)
        return counts
