"""`vpn-pulse` — the command line of the monitoring process.

`vpn-pulse run` owns the loop (collect → evaluate → snapshots → transitions → notifications) over
one SQLite file that the API reads. Without Telegram credentials the messages are printed; with
`--demo` a scripted collector plays the demo scenarios so a fresh installation shows states
changing within minutes. Other commands (init, doctor, server, probe, note) arrive with the CLI
increment.
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from vpnpulse.observability import configure_logging


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "contracts" / "config.schema.json").exists():
            return parent
    raise FileNotFoundError("contracts/ not found: run from a repository checkout")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vpn-pulse", description="VPN Pulse — monitoring loop and tools")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="collect → evaluate → notify, forever or once")
    run.add_argument("--config", type=Path, default=None, help="public config.yaml (required unless --demo)")
    run.add_argument("--db", type=Path, default=Path("vpnpulse.sqlite3"), help="SQLite file shared with the API (default: ./vpnpulse.sqlite3)")
    run.add_argument("--once", action="store_true", help="one run, then exit (systemd timers, tests)")
    run.add_argument("--interval", type=int, default=None, help="seconds between runs (default: monitoring.collection_interval_seconds)")
    run.add_argument("--demo", action="store_true", help="scripted collector over the demo scenarios; the messenger prints unless Telegram is configured")
    run.add_argument("--demo-speed", type=float, default=1.0, help="play the demo phases N times faster than the clock (default 1: a 40-minute cycle; freshness and confirmations still follow the real clock)")
    run.add_argument("--telegram-token-file", type=Path, default=None, help="file with the bot token (0600); with --group-chat-id enables Telegram delivery")
    run.add_argument("--group-chat-id", default=None, help="chat that hears about confirmed outages and recoveries")
    run.add_argument("--admin-chat-id", default=None, help="chat for unconfirmed problems and data gaps (default: the group)")
    run.add_argument("--quiet", action="store_true", help="no JSON log lines on stderr")
    return parser


def _load_config(path: Path | None, demo: bool, now: datetime):
    from vpnpulse.config import load_config

    if path is not None:
        return load_config(path, _repo_root() / "contracts" / "config.schema.json")
    if not demo:
        raise SystemExit("vpn-pulse run: --config is required (or --demo)")
    from vpnpulse.dev.scenarios import ScenarioCatalog
    from vpnpulse.dev.seed import config_for

    catalog = ScenarioCatalog.load()
    return config_for(catalog, catalog.build("operational", now))


def command_run(args: argparse.Namespace) -> int:
    from vpnpulse.notify import ConsoleNotifier, MessageFormatter, TelegramNotifier
    from vpnpulse.pipeline import Pipeline
    from vpnpulse.storage import apply_migrations, connect

    if not args.quiet:
        configure_logging(logging.INFO)
    now = lambda: datetime.now(UTC)  # noqa: E731
    config = _load_config(args.config, args.demo, now())
    connection = connect(args.db)
    apply_migrations(connection, _repo_root() / "migrations")

    collectors = []
    if args.demo:
        from vpnpulse.collectors import FixtureCollector
        from vpnpulse.dev.scenarios import ScenarioCatalog

        collectors.append(FixtureCollector(ScenarioCatalog.load(), speed=args.demo_speed))

    formatter = MessageFormatter(config)
    if args.telegram_token_file and args.group_chat_id:
        notifier = TelegramNotifier(formatter, token_file=args.telegram_token_file, group_chat_id=args.group_chat_id, admin_chat_id=args.admin_chat_id)
    else:
        notifier = ConsoleNotifier(formatter)

    pipeline = Pipeline(connection, config, collectors=collectors, notifier=notifier, now=now)
    if args.once:
        summary = pipeline.run_once()
        _print_summary(summary)
        return 0

    def stop(*_):
        pipeline.stop()

    for name in ("SIGINT", "SIGTERM"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), stop)
    mode = "demo" if args.demo else "live"
    print(f"vpn-pulse run ({mode}): db={args.db} interval={args.interval or pipeline.interval.total_seconds():.0f}s collectors={len(collectors)} messenger={type(notifier).__name__}", file=sys.stderr)
    pipeline.run_forever(timedelta(seconds=args.interval) if args.interval else None, on_run=_print_summary)
    return 0


def _print_summary(summary: dict) -> None:
    for t in summary["transitions"]:
        print(f"{summary['at']} {t['server_id']}: {t['from']} → {t['to']} ({t['reason']})", flush=True)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        return command_run(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
