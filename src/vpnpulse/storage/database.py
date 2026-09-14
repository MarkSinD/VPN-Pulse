from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path


def connect(path: str | Path) -> sqlite3.Connection:
    # FastAPI executes synchronous handlers in a worker thread. Application writes
    # remain serialized by the repository/writer queue; this flag only permits the
    # connection to cross that boundary.
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def apply_migrations(connection: sqlite3.Connection, migrations_dir: Path) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, checksum TEXT NOT NULL)"
    )
    applied = {
        row[0]: row[1]
        for row in connection.execute("SELECT version, checksum FROM schema_migrations")
    }
    for path in sorted(migrations_dir.glob("[0-9][0-9][0-9][0-9]_*.sql")):
        version = int(path.name.split("_", 1)[0])
        sql = path.read_text(encoding="utf-8")
        checksum = hashlib.sha256(sql.encode()).hexdigest()
        if version in applied:
            if applied[version] != checksum:
                raise RuntimeError(f"migration {version} checksum changed")
            continue
        with connection:
            connection.executescript(sql)
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at, checksum) "
                "VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ','now'), ?)",
                (version, checksum),
            )
