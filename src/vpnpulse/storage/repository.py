from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from vpnpulse.domain import Evaluation, State


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None


class StateRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

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
                    (
                        transition_id,
                        scope_key,
                        previous_state.value,
                        evaluation.state.value,
                        evaluation.reason_code,
                        _iso(evaluated_at),
                        _iso(evaluated_at),
                        dedupe_key,
                        evidence,
                    ),
                )
                notification_id = str(uuid5(NAMESPACE_URL, "notification:" + dedupe_key))
                self.connection.execute(
                    """
                    INSERT OR IGNORE INTO notification_queue(
                      id, transition_id, destination_kind, template_key, params_json,
                      state, attempts, next_attempt_at, locked_until, sent_at,
                      last_error_code, dedupe_key, created_at
                    ) VALUES (?, ?, 'group', 'bot.stateChanged', ?, 'pending', 0, ?, NULL, NULL, NULL, ?, ?)
                    """,
                    (
                        notification_id,
                        transition_id,
                        json.dumps({"server_id": server_id, "state": evaluation.state.value}),
                        _iso(evaluated_at),
                        dedupe_key,
                        _iso(evaluated_at),
                    ),
                )
        return transition_id


class NotificationWorker:
    def __init__(self, connection: sqlite3.Connection, send) -> None:
        self.connection = connection
        self.send = send

    def deliver_one(self, now: datetime) -> bool:
        row = self.connection.execute(
            """
            SELECT id, template_key, params_json FROM notification_queue
            WHERE state = 'pending' AND next_attempt_at <= ? ORDER BY created_at LIMIT 1
            """,
            (_iso(now),),
        ).fetchone()
        if row is None:
            return False
        notification_id, template_key, params_json = row
        self.send(template_key, json.loads(params_json))
        with self.connection:
            self.connection.execute(
                "UPDATE notification_queue SET state='sent', attempts=attempts+1, sent_at=? WHERE id=?",
                (_iso(now), notification_id),
            )
        return True
