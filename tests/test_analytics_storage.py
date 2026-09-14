from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from vpnpulse.analytics import SqliteAnalyticsRepository
from vpnpulse.storage import apply_migrations, connect


ROOT = Path(__file__).parents[1]
NOW = datetime(2026, 9, 13, 18, 0, tzinfo=UTC)


def _contracts_dir():
    for parent in Path(__file__).resolve().parents:
        if (parent / "contracts" / "openapi.yaml").exists():
            return parent / "contracts"
    raise FileNotFoundError("contracts/ not found above tests/")


def event(event_id=None):
    return {
        "event_id": event_id or str(uuid4()),
        "name": "app_opened",
        "occurred_at": NOW.isoformat(),
        "schema_version": 1,
        "session_id": str(uuid4()),
        "surface": "mini_app",
        "properties": {"role": "member", "language": "ru"},
    }


def test_sqlite_analytics_is_idempotent_and_expires_in_batches(tmp_path):
    connection = connect(tmp_path / "analytics.sqlite3")
    apply_migrations(connection, ROOT / "migrations")
    repository = SqliteAnalyticsRepository(
        _contracts_dir() / "analytics-events.schema.json", connection
    )
    item = event()
    assert repository.accept_batch([item], NOW) == 1
    assert repository.accept_batch([item], NOW) == 0
    assert connection.execute("SELECT count(*) FROM product_events").fetchone()[0] == 1
    assert repository.delete_expired(NOW + timedelta(days=31)) == 1
    assert connection.execute("SELECT count(*) FROM product_events").fetchone()[0] == 0
