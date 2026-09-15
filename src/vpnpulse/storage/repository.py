"""State snapshots, transitions and the notification queue (monitoring policy → SQLite).

`save_evaluation` stores the evaluated state of a scope and, when it changed, one transition and
at most one queued notification. Who gets told follows the monitoring policy: the group hears
about a confirmed failure once and about the recovery that follows it (even when the way back
passes through `degraded`); unconfirmed problems and data gaps go to the administrator only; the
first evaluation after a data gap tells nobody. `NotificationWorker` delivers the queue, one
message per scope with the newest state (older pending messages for the same scope are
superseded, and an unsent failure/recovery pair cancels out), retrying with back-off when the
messenger is unavailable.
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from vpnpulse.domain import Evaluation, State

MAX_ATTEMPTS = 20


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def notification_for(previous: State, current: State, *, group_alerted: bool = False) -> tuple[str, str] | None:
    """(destination, template) for a transition, or None when nobody needs a message.

    `group_alerted` says the group was told the scope is unavailable and has not heard about a
    recovery yet; the recovery then goes to the group whatever the intermediate states were.
    """
    if current is State.UNAVAILABLE:
        return ("admin" if group_alerted else "group"), "bot.unavailable"
    if current is State.OPERATIONAL and group_alerted:
        return "group", "bot.recovered"
    if current is State.DEGRADED:
        return "admin", "bot.degraded"
    if current is State.UNKNOWN:
        return "admin", "bot.unknown"
    if current is State.OPERATIONAL and previous is not State.UNKNOWN:
        return "admin", "bot.recovered"
    return None


class StateRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def group_alerted(self, scope_key: str) -> bool:
        """True while the group's last message about the scope (sent or still pending) says it is unavailable."""
        row = self.connection.execute(
            """
            SELECT q.template_key FROM notification_queue q
            JOIN state_transitions t ON t.id = q.transition_id
            WHERE t.scope_key = ? AND q.destination_kind = 'group' AND q.state IN ('pending', 'sent')
            ORDER BY q.created_at DESC, q.rowid DESC LIMIT 1
            """,
            (scope_key,),
        ).fetchone()
        return bool(row) and row[0] == "bot.unavailable"

    def save_evaluation(
        self,
        *,
        scope_key: str,
        server_id: str,
        network_scope: str,
        evaluation: Evaluation,
        evaluated_at: datetime,
    ) -> str | None:
        previous_row = self.connection.execute(
            "SELECT state, version FROM state_snapshots WHERE scope_key = ?", (scope_key,)
        ).fetchone()
        previous_state = State(previous_row[0]) if previous_row else State.UNKNOWN
        version = (previous_row[1] + 1) if previous_row else 1
        evidence = json.dumps({"count": evaluation.evidence_count, "coverage": evaluation.coverage})

        transition_id: str | None = None
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO state_snapshots(
                  scope_key, server_id, protocol_id, network_scope, state, reason_code,
                  confidence, observed_at, evaluated_at, fresh_until, evidence_json, version
                ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(scope_key) DO UPDATE SET
                  state=excluded.state, reason_code=excluded.reason_code,
                  confidence=excluded.confidence, observed_at=excluded.observed_at,
                  evaluated_at=excluded.evaluated_at, fresh_until=excluded.fresh_until,
                  evidence_json=excluded.evidence_json, version=excluded.version
                """,
                (
                    scope_key,
                    server_id,
                    network_scope,
                    evaluation.state.value,
                    evaluation.reason_code,
                    "sufficient" if evaluation.coverage >= 1 else "partial",
                    _iso(evaluation.observed_at),
                    _iso(evaluated_at),
                    _iso(evaluation.fresh_until),
                    evidence,
                    version,
                ),
            )
            if evaluation.state != previous_state:
                key_material = f"{scope_key}:{previous_state.value}:{evaluation.state.value}:{_iso(evaluation.observed_at)}"
                dedupe_key = str(uuid5(NAMESPACE_URL, key_material))
                transition_id = str(uuid5(NAMESPACE_URL, "transition:" + dedupe_key))
                self.connection.execute(
                    """
                    INSERT OR IGNORE INTO state_transitions(
                      id, scope_key, from_state, to_state, reason_code, opened_at,
                      confirmed_at, closed_at, dedupe_key, evidence_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                    """,
                    (transition_id, scope_key, previous_state.value, evaluation.state.value, evaluation.reason_code,
                     _iso(evaluated_at), _iso(evaluated_at), dedupe_key, evidence),
                )
                self.connection.execute(
                    "UPDATE state_transitions SET closed_at = ? WHERE scope_key = ? AND closed_at IS NULL AND id != ?",
                    (_iso(evaluated_at), scope_key, transition_id),
                )
                target = notification_for(previous_state, evaluation.state, group_alerted=self.group_alerted(scope_key))
                if target is not None:
                    destination, template = target
                    notification_id = str(uuid5(NAMESPACE_URL, "notification:" + dedupe_key))
                    self.connection.execute(
                        """
                        INSERT OR IGNORE INTO notification_queue(
                          id, transition_id, destination_kind, template_key, params_json,
                          state, attempts, next_attempt_at, locked_until, sent_at,
                          last_error_code, dedupe_key, created_at
                        ) VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, NULL, NULL, NULL, ?, ?)
                        """,
                        (notification_id, transition_id, destination, template,
                         json.dumps({"server_id": server_id, "scope_key": scope_key, "state": evaluation.state.value, "from_state": previous_state.value}),
                         _iso(evaluated_at), dedupe_key, _iso(evaluated_at)),
                    )
        return transition_id


class NotificationWorker:
    """Delivers the queue through `send(template_key, params) -> bool`."""

    def __init__(self, connection: sqlite3.Connection, send: Callable[[str, dict], bool | None], *, backoff_seconds: int = 30) -> None:
        self.connection = connection
        self.send = send
        self.backoff = backoff_seconds

    def deliver_one(self, now: datetime) -> bool:
        row = self.connection.execute(
            "SELECT id, template_key, params_json, attempts, destination_kind FROM notification_queue WHERE state = 'pending' AND next_attempt_at <= ? ORDER BY created_at LIMIT 1",
            (_iso(now),),
        ).fetchone()
        if row is None:
            return False
        self._deliver(row, now)
        return True

    def deliver_pending(self, now: datetime) -> dict[str, int]:
        """Deliver everything due; several pending messages for one scope collapse into the newest."""
        rows = self.connection.execute(
            "SELECT id, template_key, params_json, attempts, destination_kind FROM notification_queue WHERE state = 'pending' AND next_attempt_at <= ? ORDER BY created_at",
            (_iso(now),),
        ).fetchall()
        newest: dict[tuple[str, str], tuple] = {}
        superseded = 0
        for row in rows:
            params = json.loads(row[2])
            key = (params.get("scope_key") or params.get("server_id") or row[0], row[4])
            previous = newest.pop(key, None)
            if previous is not None:
                with self.connection:
                    self.connection.execute("UPDATE notification_queue SET state = 'superseded' WHERE id = ?", (previous[0],))
                superseded += 1
                if row[4] == "group" and previous[1] == "bot.unavailable" and row[1] == "bot.recovered":
                    # the group never heard about the outage, so a recovery message would only puzzle it
                    with self.connection:
                        self.connection.execute("UPDATE notification_queue SET state = 'superseded' WHERE id = ?", (row[0],))
                    superseded += 1
                    continue
            newest[key] = row
        sent = failed = 0
        for row in newest.values():
            if self._deliver(row, now):
                sent += 1
            else:
                failed += 1
        return {"sent": sent, "failed": failed, "superseded": superseded}

    def _deliver(self, row, now: datetime) -> bool:
        notification_id, template_key, params_json, attempts, destination = row
        ok = True
        try:
            result = self.send(template_key, {**json.loads(params_json), "destination": destination})
            ok = result is not False
        except Exception:  # noqa: BLE001 - a messenger failure must never stop the pipeline
            ok = False
        with self.connection:
            if ok:
                self.connection.execute(
                    "UPDATE notification_queue SET state='sent', attempts=attempts+1, sent_at=?, last_error_code=NULL WHERE id=?",
                    (_iso(now), notification_id),
                )
            else:
                attempts += 1
                state = "failed" if attempts >= MAX_ATTEMPTS else "pending"
                self.connection.execute(
                    "UPDATE notification_queue SET state=?, attempts=?, next_attempt_at=?, last_error_code='SEND_FAILED' WHERE id=?",
                    (state, attempts, _iso(now + timedelta(seconds=self.backoff * attempts)), notification_id),
                )
        return ok
