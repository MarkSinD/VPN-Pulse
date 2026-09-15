"""`vpn-pulse server add | list | remove` — the servers block of config.yaml.

`add` and `remove` edit the public configuration atomically after validating it against the
contract; nothing is done on the VPN server itself (the read-only helper install is the real
collectors' increment). `list` shows the configured servers and, when the database is there,
their current state.
"""
from __future__ import annotations

import argparse
import re

from vpnpulse.cli.common import CliError, Output, config_path_of, confirm, lang_of, load_public_config, make_read_model, open_database, resolve_db, write_config_atomic
from vpnpulse.storage import sync_servers

ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
TYPES = ("awg-host", "awg-docker", "hiddify")


def add_parser(commands, parents) -> None:
    server = commands.add_parser("server", parents=parents, help="servers in config.yaml")
    sub = server.add_subparsers(dest="action", required=True)
    add = sub.add_parser("add", parents=parents, help="add a server to config.yaml")
    add.add_argument("--id", required=True, help="public id (^[a-z][a-z0-9-]{1,63}$) — never a hostname")
    add.add_argument("--type", required=True, choices=TYPES)
    add.add_argument("--name-ru", required=True)
    add.add_argument("--name-en", required=True)
    add.add_argument("--country", required=True, help="ISO 3166-1 alpha-2, e.g. NL")
    add.add_argument("--priority", type=int, default=None, help="recommended_priority (lower wins among equals)")
    add.add_argument("--collector-ref", default=None, help="name of the collector credential (not the credential)")
    add.add_argument("--disabled", action="store_true", help="add as enabled: false")
    add.set_defaults(handler=command_add)
    ls = sub.add_parser("list", parents=parents, help="configured servers and their state")
    ls.add_argument("--json", action="store_true")
    ls.set_defaults(handler=command_list)
    rm = sub.add_parser("remove", parents=parents, help="remove a server from config.yaml (history stays in the database)")
    rm.add_argument("id")
    rm.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    rm.set_defaults(handler=command_remove)


def _load(args):
    path = config_path_of(args)
    return path, load_public_config(path)


def command_add(args: argparse.Namespace, out: Output) -> int:
    path, config = _load(args)
    if not ID_PATTERN.match(args.id):
        raise CliError("--id must match ^[a-z][a-z0-9-]{1,63}$ (letters, digits, dashes; not a hostname)")
    if any(s["id"] == args.id for s in config.get("servers", [])):
        raise CliError(f"server {args.id} is already in {path}")
    country = args.country.upper()
    if not re.match(r"^[A-Z]{2}$", country):
        raise CliError("--country must be two letters (ISO 3166-1 alpha-2)")
    entry = {"id": args.id, "type": args.type, "name": {"ru": args.name_ru, "en": args.name_en}, "country_code": country, "enabled": not args.disabled}
    if args.priority is not None:
        entry["recommended_priority"] = args.priority
    if args.collector_ref:
        entry["collector_ref"] = args.collector_ref
    config.setdefault("servers", []).append(entry)
    write_config_atomic(path, config)
    _sync(args, config)
    out.line(f"added {args.id} ({args.type}, {country}) to {path}")
    out.line("The read-only collector helper for this server is installed by a later increment; until then")
    out.line("probe reports (PC, Android, cross-server) are the evidence for it. Next: vpn-pulse doctor servers")
    return 0


def _sync(args, config: dict) -> None:
    """Keep the servers table in step so notes and probe reports can reference the server right away."""
    db_path = resolve_db(args, config)
    if db_path.exists():
        sync_servers(open_database(db_path), config)


def command_list(args: argparse.Namespace, out: Output) -> int:
    path, config = _load(args)
    lang = lang_of(args, config)
    states: dict[str, dict] = {}
    db_path = resolve_db(args, config)
    if db_path.exists():
        try:
            status = make_read_model(open_database(db_path), config).status("admin", lang)
            states = {c["id"]: c for c in status["servers"]}
        except Exception:  # noqa: BLE001 - listing the configuration must work without a healthy database
            states = {}
    rows = []
    for s in config.get("servers", []):
        card = states.get(s["id"])
        rows.append({
            "id": s["id"], "type": s["type"], "country_code": s["country_code"], "name": s["name"].get(lang) or s["name"]["ru"],
            "enabled": bool(s.get("enabled", True)), "recommended_priority": s.get("recommended_priority", 0),
            "state": card["state"] if card else None, "is_stale": card["freshness"]["is_stale"] if card else None,
            "observed_at": card["freshness"]["observed_at"] if card else None,
            "recommended": card["recommended"] if card else None,
        })
    if args.json:
        out.json(rows)
        return 0
    if not rows:
        out.line(f"no servers in {path} — vpn-pulse server add")
        return 0
    width = max(len(r["id"]) for r in rows)
    for r in rows:
        state = r["state"] or "—"
        if r["state"] and r["observed_at"] is None:
            state = "no data yet"
        elif r["is_stale"] and r["state"]:
            state += " (stale)"
        flags = ("" if r["enabled"] else " disabled") + (" ★" if r["recommended"] else "")
        out.line(f"{r['id']:<{width}}  {r['type']:<10}  {r['country_code']}  {state:<20}  {r['name']}{flags}")
    return 0


def command_remove(args: argparse.Namespace, out: Output) -> int:
    path, config = _load(args)
    servers = config.get("servers", [])
    entry = next((s for s in servers if s["id"] == args.id), None)
    if entry is None:
        raise CliError(f"server {args.id} is not in {path}", exit_code=1)
    if not confirm(args, f"Remove {args.id} from {path}? Collection stops; history stays in the database", out):
        out.line("nothing changed")
        return 1
    config["servers"] = [s for s in servers if s["id"] != args.id]
    write_config_atomic(path, config)
    _sync(args, config)
    out.line(f"removed {args.id} from {path}; restart vpn-pulse run and the API to apply")
    out.line("The VPN itself is untouched. When a collector helper exists on the server, remove it there with the")
    out.line("command printed by the real-collectors increment (see docs/connect-server.md).")
    return 0
