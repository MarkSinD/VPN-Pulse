"""Shared plumbing for the `vpn-pulse` commands: paths, configuration, database, secrets, output.

Every line a command prints goes through `Output`, which masks any secret value the process has
seen (a bot token read for `init`, for example). Secrets are written with `0600` and read back
never; configuration files are validated against the contract before they are written, and
written atomically so a failed command leaves the previous file intact.
"""
from __future__ import annotations

import json
import os
import stat
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import yaml

from vpnpulse.config import ConfigurationError, load_config

REDACTED = "[REDACTED]"
DEFAULT_DB = Path("vpnpulse.sqlite3")


class CliError(Exception):
    """A user-facing failure; the message is printed and the exit code returned."""

    def __init__(self, message: str, exit_code: int = 2) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "contracts" / "config.schema.json").exists() and (parent / "migrations").exists():
            return parent
    raise CliError("contracts/ and migrations/ not found: run from a repository checkout or an installed tree")


def contracts_dir() -> Path:
    return repo_root() / "contracts"


def migrations_dir() -> Path:
    return repo_root() / "migrations"


class Output:
    """stdout/stderr with redaction of every secret registered through `secret()`."""

    def __init__(self, out: Callable[[str], None] | None = None, err: Callable[[str], None] | None = None) -> None:
        self._out = out or (lambda line: print(line, flush=True))
        self._err = err or (lambda line: print(line, file=sys.stderr, flush=True))
        self.secrets: list[str] = []

    def secret(self, value: str | None) -> None:
        if value and len(value) >= 6 and value not in self.secrets:
            self.secrets.append(value)

    def redact(self, text: str) -> str:
        for value in self.secrets:
            text = text.replace(value, REDACTED)
        return text

    def line(self, text: str = "") -> None:
        self._out(self.redact(text))

    def error(self, text: str) -> None:
        self._err(self.redact(text))

    def json(self, payload) -> None:
        self.line(json.dumps(payload, ensure_ascii=False, indent=2))


def now_utc() -> datetime:
    return datetime.now(UTC)


# ---------- configuration ----------
def config_path_of(args) -> Path | None:
    value = getattr(args, "config", None) or os.environ.get("VPN_PULSE_CONFIG")
    return Path(value) if value else None


def load_public_config(path: Path | None) -> dict:
    if path is None:
        raise CliError("config.yaml is required: pass --config PATH or set VPN_PULSE_CONFIG (vpn-pulse init creates one)")
    if not path.exists():
        raise CliError(f"config not found: {path} (vpn-pulse init creates one)")
    try:
        return load_config(path, contracts_dir() / "config.schema.json")
    except ConfigurationError as error:
        raise CliError(f"config invalid: {path}\n{_first_line(str(error))}") from error


def _first_line(text: str) -> str:
    return text.strip().splitlines()[0] if text.strip() else text


def validate_public_config(config: dict) -> None:
    import jsonschema

    schema = json.loads((contracts_dir() / "config.schema.json").read_text(encoding="utf-8"))
    try:
        jsonschema.Draft202012Validator(schema).validate(config)
    except jsonschema.ValidationError as error:
        where = "/".join(str(p) for p in error.absolute_path) or "(root)"
        raise CliError(f"config would be invalid at {where}: {error.message}") from error


def write_config_atomic(path: Path, config: dict) -> None:
    """Validate, then replace the file in one step (a failed write leaves the old file intact)."""
    validate_public_config(config)
    text = yaml.safe_dump(config, allow_unicode=True, sort_keys=False, default_flow_style=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


# ---------- database ----------
def resolve_db(args, config: dict | None) -> Path:
    if getattr(args, "db", None):
        return Path(args.db)
    storage = (config or {}).get("storage") or {}
    if storage.get("database"):
        return Path(storage["database"])
    return DEFAULT_DB


def open_database(path: Path, *, create: bool = False):
    from vpnpulse.storage import apply_migrations, connect

    if not create and not path.exists():
        raise CliError(f"database not found: {path} (vpn-pulse init creates it, or pass --db)")
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect(path)
    apply_migrations(connection, migrations_dir())
    return connection


def make_store(connection, config: dict, **kwargs):
    from vpnpulse.storage import SqliteStore

    return SqliteStore(connection, analytics_schema=contracts_dir() / "analytics-events.schema.json", config=config, now=now_utc, **kwargs)


def make_read_model(connection, config: dict, **kwargs):
    from vpnpulse.storage import SqliteReadModel

    return SqliteReadModel(connection, config, now=now_utc, **kwargs)


# ---------- secrets ----------
def write_secret_file(path: Path, content: str) -> None:
    """Create or replace a secret file readable by its owner only (0600 in a 0700 directory)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content.strip() + "\n")
    finally:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def secret_file_status(path: Path) -> str:
    """'ok' | 'missing' | 'empty' | 'permissions' — never returns or logs the contents."""
    if not path.exists():
        return "missing"
    try:
        if path.stat().st_size == 0 or not path.read_text(encoding="utf-8").strip():
            return "empty"
    except OSError:
        return "missing"
    if os.name == "posix":
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            return "permissions"
    return "ok"


def lang_of(args, config: dict | None) -> str:
    lang = getattr(args, "lang", None)
    if lang:
        return lang
    return ((config or {}).get("app") or {}).get("default_language", "ru")


def confirm(args, question: str, out: Output) -> bool:
    if getattr(args, "yes", False):
        return True
    if not sys.stdin.isatty():
        raise CliError(f"{question} — pass --yes to confirm without a terminal")
    out.line(f"{question} [y/N]")
    return sys.stdin.readline().strip().lower() in ("y", "yes")
