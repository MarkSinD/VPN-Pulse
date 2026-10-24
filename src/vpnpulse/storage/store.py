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
import base64
import json
import secrets
import sqlite3
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.fernet import Fernet

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
        identity_key: str | bytes | None = None,
        now: Callable[[], datetime] | None = None,
        session_minutes: int = 30,
        enrollment_minutes: int = 10,
    ) -> None:
        self.db = connection
        self.config = config or {}
        self.pepper = pepper
        raw_identity_key = identity_key.encode() if isinstance(identity_key, str) else identity_key
        self.identity_cipher = Fernet(base64.urlsafe_b64encode(hashlib.sha256(raw_identity_key).digest())) if raw_identity_key else None
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
    @staticmethod
    def _cipher(key: str | bytes) -> Fernet:
        raw = key.encode() if isinstance(key, str) else key
        return Fernet(base64.urlsafe_b64encode(hashlib.sha256(raw).digest()))

    def _member_hash(self, telegram_user_id: int) -> bytes:
        return hmac.new(self.pepper.encode(), str(telegram_user_id).encode(), hashlib.sha256).digest()

    def upsert_member(self, identity: Identity, now: datetime | None = None, *, source: str = "session") -> str:
        if self.identity_cipher is None:
            raise RuntimeError("member registry requires a separate identity encryption key")
        now = now or self.now()
        lookup = self._member_hash(identity.telegram_user_id)
        row = self.db.execute("SELECT id, membership_state FROM members WHERE telegram_user_hash = ?", (lookup,)).fetchone()
        member_id = row[0] if row else str(uuid.uuid4())
        previous = row[1] if row else None
        ciphertext = self.identity_cipher.encrypt(str(identity.telegram_user_id).encode())
        with self.db:
            self.db.execute(
                """
                INSERT INTO members(id, telegram_id_ciphertext, telegram_user_hash, display_name, username,
                                    membership_state, first_seen_at, last_seen_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)
                ON CONFLICT(telegram_user_hash) DO UPDATE SET
                  telegram_id_ciphertext=excluded.telegram_id_ciphertext,
                  display_name=COALESCE(excluded.display_name, members.display_name),
                  username=COALESCE(excluded.username, members.username),
                  membership_state='active', last_seen_at=excluded.last_seen_at, updated_at=excluded.updated_at
                """,
                (member_id, ciphertext, lookup, identity.display_name, identity.username, _iso(now), _iso(now), _iso(now)),
            )
            if previous != "active":
                self.db.execute(
                    "INSERT INTO membership_events VALUES (?, ?, ?, ?, 'active', NULL, ?, ?)",
                    (str(uuid.uuid4()), member_id, source, previous, _iso(now), _iso(now)),
                )
            self.db.execute("UPDATE access_lifecycle_jobs SET state='cancelled',updated_at=? WHERE member_id=? AND state='pending'",
                            (_iso(now), member_id))
        return member_id

    def record_membership(
        self,
        identity: Identity,
        state: str,
        *,
        source: str,
        external_event_id: str | None = None,
        now: datetime | None = None,
    ) -> str:
        """Apply an idempotent Telegram/admin membership event and return the member id."""
        if state not in {"active", "left", "banned", "unknown"}:
            raise ValueError("invalid membership state")
        if source not in {"session", "chat_member", "admin_import"}:
            raise ValueError("invalid membership source")
        if self.identity_cipher is None:
            raise RuntimeError("member registry requires a separate identity encryption key")
        if external_event_id:
            existing = self.db.execute("SELECT member_id FROM membership_events WHERE external_event_id = ?", (external_event_id,)).fetchone()
            if existing:
                return existing[0]
        now = now or self.now()
        lookup = self._member_hash(identity.telegram_user_id)
        row = self.db.execute("SELECT id, membership_state FROM members WHERE telegram_user_hash = ?", (lookup,)).fetchone()
        member_id = row[0] if row else str(uuid.uuid4())
        previous = row[1] if row else None
        ciphertext = self.identity_cipher.encrypt(str(identity.telegram_user_id).encode())
        with self.db:
            self.db.execute(
                """
                INSERT INTO members(id, telegram_id_ciphertext, telegram_user_hash, display_name, username,
                                    membership_state, first_seen_at, last_seen_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(telegram_user_hash) DO UPDATE SET
                  telegram_id_ciphertext=excluded.telegram_id_ciphertext,
                  display_name=COALESCE(excluded.display_name, members.display_name),
                  username=COALESCE(excluded.username, members.username),
                  membership_state=excluded.membership_state,
                  last_seen_at=excluded.last_seen_at, updated_at=excluded.updated_at
                """,
                (member_id, ciphertext, lookup, identity.display_name, identity.username,
                 state, _iso(now), _iso(now), _iso(now)),
            )
            if previous != state or external_event_id:
                self.db.execute(
                    "INSERT INTO membership_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), member_id, source, previous, state, external_event_id, _iso(now), _iso(now)),
                )
            if state == "active":
                self.db.execute("UPDATE access_lifecycle_jobs SET state='cancelled',updated_at=? WHERE member_id=? AND state='pending'",
                                (_iso(now), member_id))
            elif state in {"left", "banned"} and previous != state:
                grace = 0 if state == "banned" else int((self.config.get("access") or {}).get("leave_grace_hours", 24))
                due = now + timedelta(hours=grace)
                self.db.execute(
                    "INSERT OR IGNORE INTO access_lifecycle_jobs(id,member_id,kind,due_at,state,created_at,updated_at) VALUES (?,?,'revoke_all',?,'pending',?,?)",
                    (str(uuid.uuid4()), member_id, _iso(due), _iso(now), _iso(now)),
                )
        return member_id

    def telegram_id_for_member(self, member_id: str) -> int | None:
        if self.identity_cipher is None:
            return None
        row = self.db.execute("SELECT telegram_id_ciphertext FROM members WHERE id = ?", (member_id,)).fetchone()
        return int(self.identity_cipher.decrypt(row[0]).decode()) if row else None

    def rotate_identity_key(self, new_key: str | bytes) -> int:
        if self.identity_cipher is None:
            raise RuntimeError("member registry requires the current identity encryption key")
        replacement = self._cipher(new_key)
        rows = self.db.execute("SELECT id, telegram_id_ciphertext FROM members").fetchall()
        with self.db:
            for member_id, ciphertext in rows:
                plaintext = self.identity_cipher.decrypt(ciphertext)
                self.db.execute("UPDATE members SET telegram_id_ciphertext = ? WHERE id = ?", (replacement.encrypt(plaintext), member_id))
        self.identity_cipher = replacement
        return len(rows)

    def create_session(self, identity: Identity, now: datetime | None = None) -> Session:
        now = now or self.now()
        token = secrets.token_urlsafe(32)
        expires = now + self.session_ttl
        member_id = identity.member_id
        if (self.config.get("access") or {}).get("member_registry_enabled") is True:
            member_id = self.upsert_member(identity, now)
            identity = Identity(identity.telegram_user_id, identity.role, member_id, identity.display_name, identity.username)
        with self.db:
            self.db.execute(
                "INSERT INTO web_sessions(id_hash, role, telegram_user_hash, created_at, expires_at, last_membership_check_at, revoked_at, member_id) VALUES (?, ?, ?, ?, ?, ?, NULL, ?)",
                (_sha(token), identity.role, self._member_hash(identity.telegram_user_id), _iso(now), _iso(expires), _iso(now), member_id),
            )
        return Session(token, identity, expires)

    def get_session(self, token: str | None, now: datetime | None = None) -> Session | None:
        if not token:
            return None
        now = now or self.now()
        row = self.db.execute("SELECT role, expires_at, revoked_at, member_id FROM web_sessions WHERE id_hash = ?", (_sha(token),)).fetchone()
        if row is None or row[2] is not None:
            return None
        expires = _dt(row[1])
        if expires is None or expires <= now:
            return None
        # the Telegram id is stored only as a hash; the session carries the role, which is all routes need
        return Session(token, Identity(0, row[0], row[3]), expires)

    def revoke_session(self, token: str | None, now: datetime | None = None) -> None:
        if not token:
            return
        with self.db:
            self.db.execute("UPDATE web_sessions SET revoked_at = ? WHERE id_hash = ? AND revoked_at IS NULL", (_iso(now or self.now()), _sha(token)))

    # ---------- member access ----------
    def request_access(self, member_id: str, now: datetime | None = None) -> dict:
        now = now or self.now()
        existing = self.db.execute(
            "SELECT id, state, created_at FROM access_requests WHERE member_id = ? AND state = 'pending'", (member_id,)
        ).fetchone()
        if existing:
            return {"id": existing[0], "state": existing[1], "created_at": existing[2]}
        request_id = str(uuid.uuid4())
        with self.db:
            self.db.execute(
                "INSERT INTO access_requests(id, member_id, state, message, created_at) VALUES (?, ?, 'pending', NULL, ?)",
                (request_id, member_id, _iso(now)),
            )
        return {"id": request_id, "state": "pending", "created_at": _iso(now)}

    def grant_access(
        self, member_id: str, server_id: str, *, actor: str, reason: str,
        valid_until: datetime | None = None, now: datetime | None = None,
    ) -> dict:
        now = now or self.now()
        if valid_until is not None and valid_until <= now:
            raise ValueError("grant expiry must be in the future")
        existing = self.db.execute(
            "SELECT id, state, valid_until FROM access_grants WHERE member_id = ? AND server_id = ? AND state IN ('active','suspended')",
            (member_id, server_id),
        ).fetchone()
        if existing:
            return {"id": existing[0], "state": existing[1], "valid_until": existing[2]}
        grant_id = str(uuid.uuid4())
        with self.db:
            self.db.execute(
                """INSERT INTO access_grants(id, member_id, server_id, state, reason, valid_until,
                   granted_by_hash, created_at, updated_at, revoked_at)
                   VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, NULL)""",
                (grant_id, member_id, server_id, reason[:240], _iso(valid_until), _sha(f"{self.pepper}:{actor}"), _iso(now), _iso(now)),
            )
            self.db.execute(
                "UPDATE access_requests SET state='approved', decided_at=?, decided_by_hash=? WHERE member_id=? AND state='pending'",
                (_iso(now), _sha(f"{self.pepper}:{actor}"), member_id),
            )
        return {"id": grant_id, "state": "active", "valid_until": _iso(valid_until)}

    def set_grant_state(self, grant_id: str, state: str, *, now: datetime | None = None) -> bool:
        if state not in {"active", "suspended", "revoked"}:
            raise ValueError("invalid grant state")
        now = now or self.now()
        with self.db:
            changed = self.db.execute(
                "UPDATE access_grants SET state=?, updated_at=?, revoked_at=? WHERE id=? AND state != 'expired'",
                (state, _iso(now), _iso(now) if state == "revoked" else None, grant_id),
            ).rowcount
        return changed == 1

    def grant_context(self, grant_id: str) -> dict | None:
        row = self.db.execute("SELECT member_id,server_id,state FROM access_grants WHERE id=?", (grant_id,)).fetchone()
        return {"member_id": row[0], "server_id": row[1], "state": row[2]} if row else None

    def member_access(self, member_id: str, now: datetime | None = None) -> list[dict]:
        now = now or self.now()
        with self.db:
            self.db.execute(
                "UPDATE access_grants SET state='expired', updated_at=? WHERE member_id=? AND state='active' AND valid_until IS NOT NULL AND valid_until <= ?",
                (_iso(now), member_id, _iso(now)),
            )
        return [
            {"id": row[0], "server_id": row[1], "state": row[2], "valid_until": row[3], "reason": row[4]}
            for row in self.db.execute(
                "SELECT id, server_id, state, valid_until, reason FROM access_grants WHERE member_id=? ORDER BY server_id", (member_id,)
            ).fetchall()
        ]

    def pending_access_request(self, member_id: str) -> dict | None:
        row = self.db.execute(
            "SELECT id,state,created_at FROM access_requests WHERE member_id=? AND state='pending' ORDER BY created_at DESC LIMIT 1",
            (member_id,),
        ).fetchone()
        return {"id": row[0], "state": row[1], "created_at": row[2]} if row else None

    def member_coverage(self) -> dict:
        rows = dict(self.db.execute("SELECT membership_state, count(*) FROM members GROUP BY membership_state").fetchall())
        return {"known": sum(rows.values()), "active": rows.get("active", 0), "left": rows.get("left", 0),
                "banned": rows.get("banned", 0), "unknown": rows.get("unknown", 0)}

    def list_members(self) -> list[dict]:
        items = [
            {"id": row[0], "display_name": row[1], "username": row[2], "membership_state": row[3],
             "first_seen_at": row[4], "last_seen_at": row[5], "grants": [], "access_request": None}
            for row in self.db.execute(
                "SELECT id, display_name, username, membership_state, first_seen_at, last_seen_at FROM members ORDER BY COALESCE(display_name, username, id)"
            ).fetchall()
        ]
        by_id = {item["id"]: item for item in items}
        for row in self.db.execute(
            "SELECT id,member_id,server_id,state,valid_until,reason FROM access_grants ORDER BY server_id"
        ).fetchall():
            if row[1] in by_id:
                by_id[row[1]]["grants"].append({"id": row[0], "server_id": row[2], "state": row[3],
                                                 "valid_until": row[4], "reason": row[5]})
        for row in self.db.execute(
            "SELECT member_id,id,state,created_at FROM access_requests WHERE state='pending' ORDER BY created_at"
        ).fetchall():
            if row[0] in by_id:
                by_id[row[0]]["access_request"] = {"id": row[1], "state": row[2], "created_at": row[3]}
        return items

    # ---------- profile reservations (no secret material) ----------
    def reserve_profile(
        self, member_id: str, server_id: str, public_key: str, addresses: list[str],
        *, idempotency_key: str, now: datetime | None = None,
    ) -> dict:
        """Reserve one profile and address atomically; safe to retry with the same key."""
        now = now or self.now()
        existing_op = self.db.execute(
            "SELECT p.id, p.address, p.state, o.id, o.state, p.member_id, o.operation FROM profile_operations o JOIN vpn_profiles p ON p.id=o.profile_id WHERE o.idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        if existing_op:
            if existing_op[5] != member_id or existing_op[6] != "issue":
                raise ValueError("idempotency key conflict")
            return {"profile_id": existing_op[0], "address": existing_op[1], "profile_state": existing_op[2],
                    "operation_id": existing_op[3], "operation_state": existing_op[4], "replayed": True}
        grant = self.db.execute(
            "SELECT id FROM access_grants WHERE member_id=? AND server_id=? AND state='active' AND (valid_until IS NULL OR valid_until>?)",
            (member_id, server_id, _iso(now)),
        ).fetchone()
        if not grant:
            raise ValueError("active grant required")
        current = self.db.execute(
            "SELECT id, address, state FROM vpn_profiles WHERE member_id=? AND server_id=? AND state IN ('reserved','applied','delivered','connected','revoking','needs_review')",
            (member_id, server_id),
        ).fetchone()
        if current:
            return {"profile_id": current[0], "address": current[1], "profile_state": current[2],
                    "operation_id": None, "operation_state": "completed", "replayed": True}
        unavailable = {
            row[0] for row in self.db.execute(
                "SELECT address FROM address_leases WHERE server_id=? AND (state='leased' OR quarantine_until>?)",
                (server_id, _iso(now)),
            ).fetchall()
        }
        address = next((candidate for candidate in addresses if candidate not in unavailable), None)
        if not address:
            raise ValueError("address pool exhausted")
        profile_id, operation_id = str(uuid.uuid4()), str(uuid.uuid4())
        fp = hashlib.sha256(public_key.encode()).hexdigest()[:12]
        try:
            with self.db:
                self.db.execute(
                    "INSERT INTO vpn_profiles(id,member_id,server_id,grant_id,public_key,public_key_fingerprint,address,state,created_at,updated_at) VALUES (?,?,?,?,?,?,?,'reserved',?,?)",
                    (profile_id, member_id, server_id, grant[0], public_key, fp, address, _iso(now), _iso(now)),
                )
                self.db.execute(
                    "INSERT INTO address_leases(server_id,address,profile_id,state,leased_at) VALUES (?, ?, ?, 'leased', ?)",
                    (server_id, address, profile_id, _iso(now)),
                )
                self.db.execute(
                    "INSERT INTO profile_operations(id,idempotency_key,profile_id,operation,state,created_at,updated_at) VALUES (?, ?, ?, 'issue', 'reserved', ?, ?)",
                    (operation_id, idempotency_key, profile_id, _iso(now), _iso(now)),
                )
        except sqlite3.IntegrityError:
            current = self.db.execute(
                "SELECT id,address,state FROM vpn_profiles WHERE member_id=? AND server_id=? AND state IN ('reserved','applied','delivered','connected','revoking','needs_review')",
                (member_id, server_id),
            ).fetchone()
            if not current:
                raise
            return {"profile_id": current[0], "address": current[1], "profile_state": current[2],
                    "operation_id": None, "operation_state": "completed", "replayed": True}
        return {"profile_id": profile_id, "address": address, "profile_state": "reserved",
                "operation_id": operation_id, "operation_state": "reserved", "replayed": False}

    def set_profile_operation(self, operation_id: str, state: str, *, error_code: str | None = None,
                              now: datetime | None = None) -> None:
        if state not in {"applying", "applied", "delivered", "completed", "failed", "needs_review"}:
            raise ValueError("invalid operation state")
        now = now or self.now()
        profile_state = {"applied": "applied", "delivered": "delivered",
                         "failed": "failed", "needs_review": "needs_review"}.get(state)
        with self.db:
            self.db.execute("UPDATE profile_operations SET state=?, error_code=?, updated_at=? WHERE id=?",
                            (state, error_code, _iso(now), operation_id))
            if profile_state:
                self.db.execute("UPDATE vpn_profiles SET state=?, updated_at=?, delivered_at=CASE WHEN ?='delivered' THEN ? ELSE delivered_at END WHERE id=(SELECT profile_id FROM profile_operations WHERE id=?)",
                                (profile_state, _iso(now), profile_state, _iso(now), operation_id))

    def fail_profile_issue(self, operation_id: str, *, error_code: str,
                           now: datetime | None = None, quarantine_hours: int = 24) -> None:
        """Fail a known-unsuccessful issue and quarantine its address atomically."""
        now = now or self.now()
        until = now + timedelta(hours=quarantine_hours)
        with self.db:
            self.db.execute(
                "UPDATE profile_operations SET state='failed', error_code=?, updated_at=? WHERE id=? AND operation='issue'",
                (error_code, _iso(now), operation_id),
            )
            self.db.execute(
                "UPDATE vpn_profiles SET state='failed', updated_at=? WHERE id=(SELECT profile_id FROM profile_operations WHERE id=? AND operation='issue')",
                (_iso(now), operation_id),
            )
            self.db.execute(
                "UPDATE address_leases SET state='quarantine', released_at=?, quarantine_until=? WHERE profile_id=(SELECT profile_id FROM profile_operations WHERE id=? AND operation='issue')",
                (_iso(now), _iso(until), operation_id),
            )

    def mark_profile_connected(self, profile_id: str, handshake_at: datetime, *, now: datetime | None = None) -> bool:
        now = now or self.now()
        with self.db:
            changed = self.db.execute(
                "UPDATE vpn_profiles SET state='connected', first_handshake_at=COALESCE(first_handshake_at, ?), updated_at=? WHERE id=? AND state IN ('applied','delivered','connected')",
                (_iso(handshake_at), _iso(now), profile_id),
            ).rowcount
        return changed == 1

    def release_profile(self, profile_id: str, *, now: datetime | None = None, quarantine_hours: int = 24) -> bool:
        now = now or self.now()
        until = now + timedelta(hours=quarantine_hours)
        with self.db:
            changed = self.db.execute(
                "UPDATE vpn_profiles SET state='revoked', revoked_at=?, updated_at=? WHERE id=? AND state NOT IN ('revoked','failed')",
                (_iso(now), _iso(now), profile_id),
            ).rowcount
            if changed:
                self.db.execute(
                    "UPDATE address_leases SET state='quarantine', released_at=?, quarantine_until=? WHERE profile_id=?",
                    (_iso(now), _iso(until), profile_id),
                )
        return changed == 1

    def profile_pool_status(self, server_id: str, addresses: list[str], *, now: datetime | None = None) -> dict:
        now = now or self.now()
        unavailable = self.db.execute(
            "SELECT count(*) FROM address_leases WHERE server_id=? AND (state='leased' OR quarantine_until>?)",
            (server_id, _iso(now)),
        ).fetchone()[0]
        total = len(addresses)
        free = max(0, total - unavailable)
        return {"total": total, "free": free, "used_or_quarantined": unavailable,
                "exhausted": free == 0, "low": total > 0 and free / total <= 0.10}

    def member_profiles(self, member_id: str) -> list[dict]:
        return [
            {"id": row[0], "server_id": row[1], "address": row[2], "state": row[3],
             "created_at": row[4], "first_handshake_at": row[5]}
            for row in self.db.execute(
                "SELECT id,server_id,address,state,created_at,first_handshake_at FROM vpn_profiles WHERE member_id=? ORDER BY created_at DESC",
                (member_id,),
            ).fetchall()
        ]

    def managed_profile_fingerprints(self, server_id: str) -> dict[str, str]:
        return {
            row[0]: row[1]
            for row in self.db.execute(
                "SELECT public_key_fingerprint,state FROM vpn_profiles WHERE server_id=? AND state NOT IN ('revoked','failed')",
                (server_id,),
            ).fetchall()
        }

    def due_lifecycle_jobs(self, *, now: datetime | None = None, limit: int = 20) -> list[dict]:
        now = now or self.now()
        rows = self.db.execute(
            "SELECT id,member_id,kind,attempts FROM access_lifecycle_jobs WHERE state IN ('pending','failed') AND due_at<=? AND attempts<5 ORDER BY due_at LIMIT ?",
            (_iso(now), limit),
        ).fetchall()
        jobs = []
        with self.db:
            for row in rows:
                changed = self.db.execute(
                    "UPDATE access_lifecycle_jobs SET state='running',attempts=attempts+1,updated_at=? WHERE id=? AND state IN ('pending','failed')",
                    (_iso(now), row[0]),
                ).rowcount
                if changed:
                    jobs.append({"id": row[0], "member_id": row[1], "kind": row[2], "attempt": row[3] + 1})
        return jobs

    def finish_lifecycle_job(self, job_id: str, *, error: str | None = None, now: datetime | None = None) -> None:
        now = now or self.now()
        with self.db:
            if error:
                row = self.db.execute("SELECT attempts FROM access_lifecycle_jobs WHERE id=?", (job_id,)).fetchone()
                delay_minutes = min(60, 2 ** max(0, (row[0] if row else 1) - 1))
                self.db.execute(
                    "UPDATE access_lifecycle_jobs SET state='failed',last_error=?,due_at=?,updated_at=? WHERE id=?",
                    (error[:120], _iso(now + timedelta(minutes=delay_minutes)), _iso(now), job_id),
                )
            else:
                self.db.execute("UPDATE access_lifecycle_jobs SET state='completed',last_error=NULL,updated_at=? WHERE id=?",
                                (_iso(now), job_id))

    def reserve_profile_revoke(self, member_id: str, profile_id: str, *, idempotency_key: str,
                               now: datetime | None = None) -> dict:
        now = now or self.now()
        existing = self.db.execute(
            "SELECT o.id,o.state,p.server_id,p.public_key,p.state,p.member_id,o.operation FROM profile_operations o JOIN vpn_profiles p ON p.id=o.profile_id WHERE o.idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        if existing:
            if existing[5] != member_id or existing[6] != "revoke":
                raise ValueError("idempotency key conflict")
            return {"operation_id": existing[0], "operation_state": existing[1], "server_id": existing[2],
                    "public_key": existing[3], "profile_state": existing[4], "replayed": True}
        profile = self.db.execute(
            "SELECT server_id,public_key,state FROM vpn_profiles WHERE id=? AND member_id=?", (profile_id, member_id)
        ).fetchone()
        if not profile:
            raise ValueError("profile not found")
        if profile[2] in {"revoked", "failed"}:
            return {"operation_id": None, "operation_state": "completed", "server_id": profile[0],
                    "public_key": profile[1], "profile_state": profile[2], "replayed": True}
        operation_id = str(uuid.uuid4())
        with self.db:
            self.db.execute("UPDATE vpn_profiles SET state='revoking',updated_at=? WHERE id=?", (_iso(now), profile_id))
            self.db.execute(
                "INSERT INTO profile_operations(id,idempotency_key,profile_id,operation,state,created_at,updated_at) VALUES (?, ?, ?, 'revoke', 'reserved', ?, ?)",
                (operation_id, idempotency_key, profile_id, _iso(now), _iso(now)),
            )
        return {"operation_id": operation_id, "operation_state": "reserved", "server_id": profile[0],
                "public_key": profile[1], "profile_state": "revoking", "replayed": False}

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
