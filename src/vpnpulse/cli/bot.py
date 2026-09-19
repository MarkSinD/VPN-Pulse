"""`vpn-pulse bot` — the bot's listener: answers /start with the Mini App button (systemd unit `vpn-pulse-bot`).

Needs the `telegram` block and `app.public_url` in config.yaml; without them it explains and exits 0,
so an installation without Telegram has nothing to restart in a loop.
"""
from __future__ import annotations

import argparse
import logging
import signal
from pathlib import Path

from vpnpulse.cli.common import CliError, Output, config_path_of, load_public_config, secret_file_status
from vpnpulse.observability import configure_logging


def add_parser(commands, parents) -> None:
    p = commands.add_parser("bot", parents=parents, help="answer /start in Telegram with the Mini App button (long polling)")
    p.add_argument("--once", action="store_true", help="one poll, then exit (tests, cron)")
    p.add_argument("--quiet", action="store_true", help="no JSON log lines on stderr")
    p.set_defaults(handler=command_bot)


def command_bot(args: argparse.Namespace, out: Output) -> int:
    from vpnpulse.bot import TelegramBot

    if not args.quiet:
        configure_logging(logging.INFO)
    config_path = config_path_of(args)
    if config_path is None:
        raise CliError("vpn-pulse bot: --config PATH is required (or VPN_PULSE_CONFIG)")
    config = load_public_config(config_path)
    telegram = config.get("telegram") or {}
    app_url = (config.get("app") or {}).get("public_url")
    if not telegram:
        out.error("vpn-pulse bot: Telegram is not configured (telegram block in config.yaml) — nothing to listen to")
        return 0
    if not app_url:
        raise CliError("vpn-pulse bot: app.public_url is missing in config.yaml — the /start button needs the Mini App address")
    token_file = Path(telegram["bot_token_file"])
    status = secret_file_status(token_file)
    if status != "ok":
        raise CliError(f"telegram token file {token_file}: {status} (vpn-pulse doctor telegram)")
    token = token_file.read_text(encoding="utf-8").strip()
    out.secret(token)
    bot = TelegramBot(token, app_url, default_language=(config.get("app") or {}).get("default_language", "ru"))
    if args.once:
        out.line(f"replies: {bot.poll_once()}")
        return 0
    for name in ("SIGINT", "SIGTERM"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), lambda *_: bot.stop())
    out.error(f"vpn-pulse bot: listening for /start, button → {app_url}")
    bot.run_forever()
    return 0
