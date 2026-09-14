from __future__ import annotations

import sqlite3
from datetime import UTC, datetime


STATE_ORDER = {"unavailable": 3, "degraded": 2, "unknown": 1, "operational": 0}


class SqliteStatusProvider:
    """Build the member-safe status read model from snapshots and public config."""

    def __init__(self, connection: sqlite3.Connection, display: dict[str, dict], now) -> None:
        self.connection = connection
        self.display = display
        self.now = now

    def __call__(self, role: str) -> dict:
        rows = self.connection.execute(
            """
            SELECT s.id, s.public_id, s.display_order, x.state, x.observed_at,
                   x.fresh_until, x.evidence_json
            FROM servers s
            LEFT JOIN state_snapshots x ON x.scope_key = 'server:' || s.id
            WHERE s.enabled = 1 ORDER BY s.display_order
            """
        ).fetchall()
        cards = []
        for server_id, public_id, _, state, observed_at, fresh_until, _ in rows:
            meta = self.display[public_id]
            stale = fresh_until is None or datetime.fromisoformat(fresh_until) < self.now()
            effective_state = "unknown" if stale else state
            cards.append(
                {
                    "id": public_id,
                    "name": meta["name"],
                    "country_code": meta["country_code"],
                    "state": effective_state or "unknown",
                    "freshness": {
                        "observed_at": observed_at,
                        "fresh_until": fresh_until,
                        "is_stale": stale,
                    },
                    "recommended": False,
                    "uptime_24h": None,
                    "coverage_24h": None,
                    "sources": [],
                }
            )
        overall = max((card["state"] for card in cards), key=STATE_ORDER.get, default="unknown")
        recommended = next((card for card in cards if card["state"] == "operational"), None)
        if recommended:
            recommended["recommended"] = True
        freshness_values = [card["freshness"]["observed_at"] for card in cards if card["freshness"]["observed_at"]]
        fresh_until_values = [card["freshness"]["fresh_until"] for card in cards if card["freshness"]["fresh_until"]]
        return {
            "state": overall,
            "freshness": {
                "observed_at": max(freshness_values) if freshness_values else None,
                "fresh_until": min(fresh_until_values) if fresh_until_values else None,
                "is_stale": not cards or all(card["freshness"]["is_stale"] for card in cards),
            },
            "coverage": sum(not card["freshness"]["is_stale"] for card in cards) / len(cards) if cards else 0,
            "recommended_server_id": recommended["id"] if recommended else None,
            "note": None,
            "servers": cards,
        }
