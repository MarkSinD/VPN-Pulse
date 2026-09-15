"""`vpn-pulse init` — an installation directory: config.yaml, the database and the secrets folder.

Asks nothing; every value comes from a flag (the installer wizard collects them). The bot token
is taken from a file or from stdin and stored in `secrets/telegram-bot.token` with `0600`; it is
never echoed, logged or written into config.yaml.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from vpnpulse.cli.common import CliError, Output, open_database, write_config_atomic, write_secret_file

DEFAULT_MONITORING = {"collection_interval_seconds": 60, "pc_target_interval_seconds": 60, "probe_deadline_seconds": 20, "confirmations": 2, "freshness_seconds": 180}
DEFAULT_RETENTION = {"observations_days": 7, "aggregates_days": 90, "events_days": 180, "analytics_raw_days": 30, "audit_days": 365}


def add_parser(commands, parents) -> None:
    p = commands.add_parser("init", parents=parents, help="create config.yaml, the database and the secrets directory")
    p.add_argument("--dir", type=Path, default=Path("."), help="installation directory (default: current); config.yaml lives here")
    p.add_argument("--data-dir", type=Path, default=None, help="where the database lives (default: DIR/data)")
    p.add_argument("--secrets-dir", type=Path, default=None, help="0700 directory for secret files (default: DIR/secrets)")
    p.add_argument("--language", choices=("ru", "en"), default="ru", help="default language of the Mini App and the bot")
    p.add_argument("--timezone", default="UTC", help="IANA timezone for event grouping")
    p.add_argument("--contact-url", default=None, help="https://t.me/… link for the \"Contact administrator\" button")
    p.add_argument("--group-chat-id", default=None, help="the members' chat for outage and recovery messages")
    p.add_argument("--admin-chat-id", default=None, help="chat for administrator-only messages (default: the group)")
    token = p.add_mutually_exclusive_group()
    token.add_argument("--telegram-token-file", type=Path, default=None, help="file holding the bot token; copied into the secrets directory")
    token.add_argument("--telegram-token-stdin", action="store_true", help="read the bot token from stdin (no echo, nothing in the shell history)")
    p.add_argument("--force", action="store_true", help="overwrite an existing config.yaml")
    p.set_defaults(handler=command_init)


def command_init(args: argparse.Namespace, out: Output) -> int:
    base = args.dir
    config_path = base / "config.yaml"
    data_dir = args.data_dir or base / "data"
    secrets_dir = args.secrets_dir or base / "secrets"
    if config_path.exists() and not args.force:
        raise CliError(f"{config_path} exists; pass --force to overwrite it (servers and settings in it will be lost)")

    token: str | None = None
    if args.telegram_token_stdin:
        token = sys.stdin.readline().strip()
    elif args.telegram_token_file:
        if not args.telegram_token_file.exists():
            raise CliError(f"token file not found: {args.telegram_token_file}")
        token = args.telegram_token_file.read_text(encoding="utf-8").strip()
    if token is not None:
        out.secret(token)
        if not token:
            raise CliError("the bot token is empty")
    if (token is None) != (args.group_chat_id is None):
        raise CliError("Telegram needs both the bot token (--telegram-token-file or --telegram-token-stdin) and --group-chat-id; pass neither to configure it later")

    app: dict = {"default_language": args.language, "languages": ["ru", "en"] if args.language == "ru" else ["en", "ru"], "timezone": args.timezone}
    if args.contact_url:
        app["admin_contact_url"] = args.contact_url
    db_path = data_dir / "vpnpulse.sqlite3"
    config: dict = {"version": 1, "app": app, "storage": {"database": str(db_path)}}
    if token is not None:
        token_path = secrets_dir / "telegram-bot.token"
        write_secret_file(token_path, token)
        telegram = {"bot_token_file": str(token_path), "group_chat_id": args.group_chat_id}
        if args.admin_chat_id:
            telegram["admin_chat_id"] = args.admin_chat_id
        config["telegram"] = telegram
    else:
        secrets_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(secrets_dir, 0o700)
        except OSError:
            pass
    config["servers"] = []
    config["monitoring"] = dict(DEFAULT_MONITORING)
    config["retention"] = dict(DEFAULT_RETENTION)

    write_config_atomic(config_path, config)
    open_database(db_path, create=True).close()

    out.line(f"config:    {config_path}")
    out.line(f"database:  {db_path}")
    out.line(f"secrets:   {secrets_dir}  (0700; token file 0600)" if token is not None else f"secrets:   {secrets_dir}  (0700; Telegram not configured yet)")
    out.line("")
    out.line("Next:")
    out.line(f"  export VPN_PULSE_CONFIG={config_path}" if os.name == "posix" else f"  set VPN_PULSE_CONFIG={config_path}")
    out.line("  vpn-pulse server add --id my-vpn --type awg-host --name-ru \"Мой сервер\" --name-en \"My server\" --country NL")
    out.line("  vpn-pulse doctor")
    return 0
