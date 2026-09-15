from __future__ import annotations

import hashlib
import sqlite3
import threading
from pathlib import Path


class _Rows:
    """Result of a statement, fully fetched under the connection lock (safe to read in any thread)."""

    __slots__ = ("_rows", "rowcount", "lastrowid", "_index")

    def __init__(self, rows: list, rowcount: int, lastrowid: int | None) -> None:
        self._rows = rows
        self.rowcount = rowcount
        self.lastrowid = lastrowid
        self._index = 0

    def fetchone(self):
        if self._index >= len(self._rows):
            return None
        row = self._rows[self._index]
        self._index += 1
        return row

    def fetchall(self) -> list:
        rows = self._rows[self._index:]
        self._index = len(self._rows)
        return rows

    def __iter__(self):
        return iter(self.fetchall())


class SerializedConnection(sqlite3.Connection):
    """One SQLite connection shared by the API worker threads.

    The Python sqlite3 module is not safe for concurrent statements on one connection, so every
    statement runs under a re-entrant lock and its rows are fetched before the lock is released;
    `with connection:` transactions hold the lock for their whole body. Cross-process concurrency
    (several API workers, the collector) is handled by SQLite itself with WAL and busy_timeout.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._lock = threading.RLock()

    def execute(self, sql, parameters=()):  # type: ignore[override]
        with self._lock:
            cursor = super().execute(sql, parameters)
            rows = cursor.fetchall() if cursor.description else []
            return _Rows(rows, cursor.rowcount, cursor.lastrowid)

    def executemany(self, sql, seq_of_parameters):  # type: ignore[override]
        with self._lock:
            cursor = super().executemany(sql, seq_of_parameters)
            return _Rows([], cursor.rowcount, cursor.lastrowid)

    def executescript(self, sql_script):  # type: ignore[override]
        with self._lock:
            return super().executescript(sql_script)

    def commit(self) -> None:
        with self._lock:
            super().commit()

    def rollback(self) -> None:
        with self._lock:
            super().rollback()

    def __enter__(self):
        self._lock.acquire()
        return super().__enter__()

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self._lock.release()


def connect(path: str | Path) -> sqlite3.Connection:
    # FastAPI executes synchronous handlers in a worker thread; the connection is shared between
    # them and serializes its own statements (see SerializedConnection).
    connection = sqlite3.connect(path, check_same_thread=False, factory=SerializedConnection)
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
