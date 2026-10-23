"""Member registry operations used during staged self-service rollout."""
from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

from vpnpulse.auth import Identity
from vpnpulse.cli.common import CliError, Output, config_path_of, contracts_dir, load_public_config, open_database, resolve_db
from vpnpulse.storage import SqliteStore


def add_parser(commands, parents) -> None:
    root = commands.add_parser("access", parents=parents, help="member registry coverage and controlled import")
    sub = root.add_subparsers(dest="access_command", required=True)
    coverage = sub.add_parser("coverage", parents=parents, help="compare Telegram member count with the registry")
    coverage.add_argument("--json", action="store_true")
    coverage.set_defaults(handler=command_coverage)
    imp = sub.add_parser("import-member", parents=parents, help="import one known Telegram member")
    imp.add_argument("--telegram-id", required=True, type=int)
    imp.add_argument("--name", required=True)
    imp.add_argument("--username")
    imp.set_defaults(handler=command_import)


def _context(args):
    path = config_path_of(args)
    if path is None:
        raise CliError("vpn-pulse access: --config PATH is required")
    config = load_public_config(path)
    telegram = config.get("telegram") or {}
    token_file = Path(telegram.get("bot_token_file") or "")
    key_file = path.parent / "secrets" / "member-identity.key"
    if not token_file.exists() or not key_file.exists():
        raise CliError("access registry secrets are missing")
    token = token_file.read_text(encoding="utf-8").strip()
    db = open_database(resolve_db(None, config), create=True)
    store = SqliteStore(db, analytics_schema=contracts_dir() / "analytics-events.schema.json", config=config,
                        pepper=token, identity_key=key_file.read_text(encoding="utf-8").strip())
    return config, telegram, token, store


def command_import(args, out: Output) -> int:
    _, _, _, store = _context(args)
    member_id = store.record_membership(Identity(args.telegram_id, "member", display_name=args.name,
                                                  username=args.username), "active", source="admin_import")
    out.line(f"member imported: {member_id}")
    return 0


def command_coverage(args, out: Output) -> int:
    _, telegram, token, store = _context(args)
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/getChatMemberCount",
        data=json.dumps({"chat_id": telegram["group_chat_id"]}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read())
        if not payload.get("ok"):
            raise ValueError("Bot API rejected count")
        telegram_count = int(payload["result"])
    except Exception as error:
        raise CliError("Telegram member count is unavailable") from error
    registry = store.member_coverage()
    result = {"telegram": telegram_count, "registry_active": registry["active"],
              "difference": max(0, telegram_count - registry["active"]), "registry": registry,
              "complete": telegram_count == registry["active"]}
    out.line(json.dumps(result, ensure_ascii=False) if args.json else
             f"Telegram: {telegram_count}; registry active: {registry['active']}; remaining: {result['difference']}")
    return 0 if result["complete"] else 3
