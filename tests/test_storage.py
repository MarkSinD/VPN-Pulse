from pathlib import Path

import pytest

from vpnpulse.storage import apply_migrations, connect


MIGRATIONS = Path(__file__).parents[1] / "migrations"


def test_clean_migration_and_idempotent_reapply(tmp_path):
    connection = connect(tmp_path / "test.sqlite3")
    apply_migrations(connection, MIGRATIONS)
    apply_migrations(connection, MIGRATIONS)
    tables = {
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"observations", "state_snapshots", "notification_queue", "product_events"} <= tables
    assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_changed_applied_migration_is_rejected(tmp_path):
    connection = connect(tmp_path / "test.sqlite3")
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    migration = migrations / "0001_test.sql"
    migration.write_text("CREATE TABLE sample(id TEXT PRIMARY KEY);", encoding="utf-8")
    apply_migrations(connection, migrations)
    migration.write_text("CREATE TABLE changed(id TEXT PRIMARY KEY);", encoding="utf-8")
    with pytest.raises(RuntimeError, match="checksum changed"):
        apply_migrations(connection, migrations)
