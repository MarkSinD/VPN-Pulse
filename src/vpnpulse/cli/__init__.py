"""`vpn-pulse` — the administrator's command line.

    vpn-pulse init …                      an installation directory: config.yaml, database, secrets
    vpn-pulse run [--demo] [--once]       the monitoring loop
    vpn-pulse serve                       the API and the Mini App (behind Caddy)
    vpn-pulse bot                         /start → the Mini App button (long polling)
    vpn-pulse doctor [section] [--json]   one next step per warning — the Admin screen's texts
    vpn-pulse server add|list|remove      servers in config.yaml
    vpn-pulse probe enroll|list|revoke    check sources
    vpn-pulse collector keygen|pin|test|list   server helpers (the server side of connect-server)
    vpn-pulse note set|clear|show         the administrator's note
    vpn-pulse demo seed|clear             fictional data for a first look
    vpn-pulse backup                      complete on-demand backup archive
    vpn-pulse restore                     verify and restore an archive

`--config` (or `VPN_PULSE_CONFIG`), `--db` and `--lang` may go before or after the command.
Everything printed passes through a redactor; secrets are written with 0600 and never echoed.
"""
from __future__ import annotations

import argparse
import sys

from vpnpulse.cli import backup, bot, collector, demo, doctor, init, note, probe, run, serve, server
from vpnpulse.cli.common import CliError, Output


def _common(suppress: bool) -> argparse.ArgumentParser:
    default = argparse.SUPPRESS if suppress else None
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--config", default=default, help="public config.yaml (default: $VPN_PULSE_CONFIG)")
    p.add_argument("--db", default=default, help="SQLite file (default: storage.database from config, else ./vpnpulse.sqlite3)")
    p.add_argument("--lang", choices=("ru", "en"), default=default, help="language of doctor hints and names (default: app.default_language)")
    return p


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vpn-pulse", description="VPN Pulse — monitoring loop and administration", parents=[_common(False)])
    commands = parser.add_subparsers(dest="command", required=True)
    parents = [_common(True)]
    init.add_parser(commands, parents)
    run.add_parser(commands, parents)
    serve.add_parser(commands, parents)
    bot.add_parser(commands, parents)
    doctor.add_parser(commands, parents)
    server.add_parser(commands, parents)
    probe.add_parser(commands, parents)
    collector.add_parser(commands, parents)
    note.add_parser(commands, parents)
    demo.add_parser(commands, parents)
    backup.add_parsers(commands, parents)
    return parser


def main(argv: list[str] | None = None, out: Output | None = None) -> int:
    out = out or Output()
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 2
    try:
        return int(handler(args, out) or 0)
    except CliError as error:
        out.error(f"vpn-pulse: {error}")
        return error.exit_code
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
