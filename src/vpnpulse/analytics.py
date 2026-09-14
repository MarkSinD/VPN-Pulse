from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jsonschema


class AnalyticsRegistry:
    def __init__(self, schema_path: Path) -> None:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self._validator = jsonschema.Draft202012Validator(schema)
        self._seen: set[str] = set()
        self.events: list[dict] = []

    def accept_batch(self, events: list[dict]) -> int:
        if not 1 <= len(events) <= 50:
            raise jsonschema.ValidationError("batch must contain 1..50 events")
        accepted = 0
        for event in events:
            self._validator.validate(event)
            if event["event_id"] in self._seen:
                continue
            self._seen.add(event["event_id"])
            self.events.append(event)
            accepted += 1
        return accepted


class SqliteAnalyticsRepository(AnalyticsRegistry):
    def __init__(self, schema_path: Path, connection: sqlite3.Connection, retention_days: int = 30) -> None:
        super().__init__(schema_path)
        self.connection = connection
        self.retention_days = retention_days

    def accept_batch(self, events: list[dict], received_at: datetime | None = None) -> int:
        if not 1 <= len(events) <= 50:
            raise jsonschema.ValidationError("batch must contain 1..50 events")
        received_at = received_at or datetime.now(UTC)
        accepted = 0
        with self.connection:
            for event in events:
                self._validator.validate(event)
                expires_at = received_at + timedelta(days=self.retention_days)
                cursor = self.connection.execute(
                    """
                    INSERT OR IGNORE INTO product_events(
                      event_id, name, occurred_at, received_at, session_id, surface,
                      schema_version, properties_json, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event["event_id"], event["name"], event["occurred_at"],
                        received_at.isoformat(), event["session_id"], event["surface"],
                        event["schema_version"], json.dumps(event["properties"], separators=(",", ":")),
                        expires_at.isoformat(),
                    ),
                )
                accepted += cursor.rowcount
        return accepted

    def delete_expired(self, now: datetime, batch_size: int = 500) -> int:
        with self.connection:
            cursor = self.connection.execute(
                "DELETE FROM product_events WHERE event_id IN "
                "(SELECT event_id FROM product_events WHERE expires_at <= ? LIMIT ?)",
                (now.astimezone(UTC).isoformat(), batch_size),
            )
        return cursor.rowcount
