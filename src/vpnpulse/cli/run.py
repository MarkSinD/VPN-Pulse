"""`vpn-pulse run` — the monitoring loop (collect → evaluate → snapshots → transitions → notify).

Runs forever (systemd) or once (`--once`). The messenger comes from `telegram:` in config.yaml or
from the flags; without either, messages are printed. `--demo` plays the demo scenarios through a
scripted collector so a fresh installation shows states changing within minutes.
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
from datetime import timedelta
from pathlib import Path

from vpnpulse.cli.common import CliError, Output, config_path_of, load_public_config, now_utc, open_database, resolve_db, secret_file_status
from vpnpulse.observability import configure_logging


def add_parser(commands, parents) -> None:
    run = commands.add_parser("run", parents=parents, help="collect → evaluate → notify, forever or once")
    run.add_argument("--once", action="store_true", help="one run, then exit (timers, tests)")
    run.add_argument("--interval", type=int, default=None, help="seconds between runs (default: monitoring.collection_interval_seconds)")
    run.add_argument("--demo", action="store_true", help="scripted collector over the demo scenarios; the messenger prints unless Telegram is configured")
    run.add_argument("--demo-speed", type=float, default=1.0, help="play the demo phases N times faster than the clock (default 1: a 40-minute cycle; freshness and confirmations still follow the real clock)")
    run.add_argument("--telegram-token-file", type=Path, default=None, help="overrides telegram.bot_token_file from config.yaml")
    run.add_argument("--group-chat-id", default=None, help="overrides telegram.group_chat_id")
    run.add_argument("--admin-chat-id", default=None, help="overrides telegram.admin_chat_id")
    run.add_argument("--quiet", action="store_true", help="no JSON log lines on stderr")
    run.set_defaults(handler=command_run)


def demo_config(now) -> dict:
    from vpnpulse.dev.scenarios import ScenarioCatalog
    from vpnpulse.dev.seed import config_for

    catalog = ScenarioCatalog.load()
    return config_for(catalog, catalog.build("operational", now))


def make_notifier(config: dict, out: Output, *, telegram: dict | None = None, opener=None):
    """The messenger `vpn-pulse run` uses: Telegram when a token file and a group are configured
    (config.yaml `telegram:` or the flags), the console otherwise. `opener` replaces urllib (tests)."""
    from vpnpulse.notify import ConsoleNotifier, MessageFormatter, TelegramNotifier

    formatter = MessageFormatter(config)
    telegram = {**(config.get("telegram") or {}), **{k: v for k, v in (telegram or {}).items() if v}}
    if telegram.get("bot_token_file") and telegram.get("group_chat_id"):
        token_file = Path(telegram["bot_token_file"])
        status = secret_file_status(token_file)
        if status != "ok":
            raise CliError(f"telegram token file {token_file}: {status} (vpn-pulse doctor telegram)")
        return TelegramNotifier(formatter, token_file=token_file, group_chat_id=telegram["group_chat_id"], admin_chat_id=telegram.get("admin_chat_id"), opener=opener)
    return ConsoleNotifier(formatter, out=out.line)


def collectors_map_path(config: dict, config_path: Path | None) -> Path | None:
    """`storage.collectors_file` from config.yaml, relative to the config's directory."""
    value = (config.get("storage") or {}).get("collectors_file")
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute() and config_path is not None:
        path = config_path.parent / path
    return path


def real_collectors(config: dict, config_path: Path | None, out: Output) -> list:
    """SshCollectors for the servers that have a helper in the collectors map (none without the map)."""
    from vpnpulse.collectors import build_collectors, load_collectors_map
    from vpnpulse.config import ConfigurationError

    path = collectors_map_path(config, config_path)
    if path is None:
        return []
    if not path.exists():
        raise CliError(f"collectors map not found: {path} (storage.collectors_file; vpn-pulse collector keygen creates entries)")
    try:
        collectors_map = load_collectors_map(path)
    except ConfigurationError as error:
        raise CliError(str(error)) from error
    collectors = build_collectors(config, collectors_map, base_dir=path.parent)
    for collector in collectors:
        for secret in (collector.target.key_file, collector.target.known_hosts_file):
            status = secret_file_status(secret)
            if status != "ok":
                raise CliError(f"collector {collector.name}: {secret.name}: {status} (vpn-pulse collector keygen / pin)")
    return collectors


def command_run(args: argparse.Namespace, out: Output) -> int:
    from vpnpulse.pipeline import Pipeline

    if not args.quiet:
        configure_logging(logging.INFO)
    config_path = config_path_of(args)
    if config_path is not None:
        config = load_public_config(config_path)
    elif args.demo:
        config = demo_config(now_utc())
    else:
        raise CliError("vpn-pulse run: --config PATH is required (or --demo)")
    db_path = resolve_db(args, config)
    connection = open_database(db_path, create=True)

    collectors = []
    if args.demo:
        from vpnpulse.collectors import FixtureCollector
        from vpnpulse.dev.scenarios import ScenarioCatalog

        collectors.append(FixtureCollector(ScenarioCatalog.load(), speed=args.demo_speed))
    collectors.extend(real_collectors(config, config_path, out))

    notifier = make_notifier(config, out, telegram={
        "bot_token_file": str(args.telegram_token_file) if args.telegram_token_file else None,
        "group_chat_id": args.group_chat_id,
        "admin_chat_id": args.admin_chat_id,
    })

    pipeline = Pipeline(connection, config, collectors=collectors, notifier=notifier, now=now_utc)

    def print_summary(summary: dict) -> None:
        for t in summary["transitions"]:
            out.line(f"{summary['at']} {t['server_id']}: {t['from']} → {t['to']} ({t['reason']})")

    if args.once:
        print_summary(pipeline.run_once())
        return 0

    def stop(*_):
        pipeline.stop()

    for name in ("SIGINT", "SIGTERM"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), stop)
    mode = "demo" if args.demo else "live"
    interval = args.interval or int(pipeline.interval.total_seconds())
    out.error(f"vpn-pulse run ({mode}): db={db_path} interval={interval}s collectors={len(collectors)} messenger={type(notifier).__name__}")
    pipeline.run_forever(timedelta(seconds=args.interval) if args.interval else None, on_run=print_summary)
    return 0


if __name__ == "__main__":  # pragma: no cover - convenience
    from vpnpulse.cli import main

    sys.exit(main(["run", *sys.argv[1:]]))
