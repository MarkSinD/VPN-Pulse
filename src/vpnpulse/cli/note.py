"""`vpn-pulse note set | clear | show` — the administrator's note on the status screen.

The same rows and audit entries as the Mini App's admin action; the Mini App and the bot pick the
change up on their next refresh.
"""
from __future__ import annotations

import argparse
import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from vpnpulse.cli.common import CliError, Output, config_path_of, load_public_config, make_store, now_utc, open_database, resolve_db
from vpnpulse.storage import sync_servers

MAX_TEXT = 500


def add_parser(commands, parents) -> None:
    note = commands.add_parser("note", parents=parents, help="administrator note on the status screen")
    sub = note.add_subparsers(dest="action", required=True)
    put = sub.add_parser("set", parents=parents, help="publish a note (replaces the current one)")
    put.add_argument("text")
    put.add_argument("--expires", default=None, help="HH:MM today in the app timezone, or an ISO 8601 time; omit to keep until cleared")
    put.add_argument("--server", default=None, help="attach to one server id (default: the whole installation)")
    put.set_defaults(handler=command_set)
    clear = sub.add_parser("clear", parents=parents, help="remove the current note")
    clear.set_defaults(handler=command_clear)
    show = sub.add_parser("show", parents=parents, help="print the current note")
    show.set_defaults(handler=command_show)


def _open(args):
    config = load_public_config(config_path_of(args))
    connection = open_database(resolve_db(args, config))
    return config, connection


def parse_expiry(value: str | None, timezone: str, now: datetime) -> datetime | None:
    if not value:
        return None
    try:
        zone = ZoneInfo(timezone or "UTC")
    except ZoneInfoNotFoundError:
        zone = UTC
    if re.match(r"^\d{1,2}:\d{2}$", value):
        hour, minute = (int(x) for x in value.split(":"))
        local = now.astimezone(zone).replace(hour=hour, minute=minute, second=0, microsecond=0)
        if local <= now.astimezone(zone):
            local += timedelta(days=1)
        return local.astimezone(UTC)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise CliError("--expires must be HH:MM or an ISO 8601 time") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    if parsed <= now:
        raise CliError("--expires is already in the past")
    return parsed.astimezone(UTC)


def command_set(args: argparse.Namespace, out: Output) -> int:
    text = args.text.strip()
    if not text or len(text) > MAX_TEXT:
        raise CliError(f"the note must be 1–{MAX_TEXT} characters")
    config, connection = _open(args)
    if args.server and not any(s["id"] == args.server for s in config.get("servers", [])):
        raise CliError(f"server {args.server} is not in the configuration")
    expires = parse_expiry(args.expires, (config.get("app") or {}).get("timezone", "UTC"), now_utc())
    if args.server:
        sync_servers(connection, config, now_utc())
    store = make_store(connection, config)
    note = store.put_note(text, expires, args.server, "admin")
    store.audit(actor="cli", role="admin", action="note.put", target_type="note", target_id=note["id"], details={"length": len(text)})
    until = f" until {expires.strftime('%Y-%m-%d %H:%M UTC')}" if expires else ""
    out.line(f"note published{until}" + (f" for {args.server}" if args.server else ""))
    return 0


def command_clear(args: argparse.Namespace, out: Output) -> int:
    config, connection = _open(args)
    store = make_store(connection, config)
    cleared = store.delete_note()
    store.audit(actor="cli", role="admin", action="note.delete", target_type="note", target_id="active", result="ok" if cleared else "noop")
    out.line("note cleared" if cleared else "there was no active note")
    return 0


def command_show(args: argparse.Namespace, out: Output) -> int:
    config, connection = _open(args)
    state, note = make_store(connection, config).note_state()
    if note is None:
        out.line("no active note" if state != "none" else "no note has ever been published")
        return 0
    scope = f" [{note['server_id']}]" if note.get("server_id") else ""
    until = f" (until {note['expires_at']})" if note.get("expires_at") else ""
    out.line(f"{note['text']}{scope}{until}")
    return 0
