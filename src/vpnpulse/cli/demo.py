"""`vpn-pulse demo seed | clear` — demo data in a real installation (nothing real in it).

`seed` writes one demo scenario (seven days of fictional history, three fictional servers) into
the configured database, adds those servers to config.yaml and drops a `demo-data` marker next to
the database so the API answers `mode: demo` and the Mini App shows its "Demo data" mark.
`vpn-pulse run --demo` then keeps the world moving. `clear` removes the data and the marker.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from vpnpulse.cli.common import CliError, Output, config_path_of, confirm, load_public_config, now_utc, open_database, resolve_db, write_config_atomic

TABLES_TO_CLEAR = (
    "notification_queue", "events", "state_transitions", "state_snapshots", "metric_hourly", "observations",
    "probe_reports", "probes", "probe_enrollments", "admin_notes", "collection_runs", "protocols", "servers",
)


def add_parser(commands, parents) -> None:
    demo = commands.add_parser("demo", parents=parents, help="demo data for an installation without real servers yet")
    sub = demo.add_subparsers(dest="action", required=True)
    seed = sub.add_parser("seed", parents=parents, help="write a demo scenario into the database and config.yaml")
    seed.add_argument("--scenario", default="demo", help="scenario id from fixtures/ui/scenarios.json (default: demo)")
    seed.set_defaults(handler=command_seed)
    clear = sub.add_parser("clear", parents=parents, help="remove the demo data and the demo marker")
    clear.add_argument("--yes", action="store_true")
    clear.set_defaults(handler=command_clear)


def marker_path(db_path: Path) -> Path:
    from vpnpulse.serve import demo_marker

    return demo_marker(db_path)


def command_seed(args: argparse.Namespace, out: Output) -> int:
    from vpnpulse.dev.scenarios import ScenarioCatalog
    from vpnpulse.dev.seed import seed_scenario

    config_path = config_path_of(args)
    config = load_public_config(config_path)
    db_path = resolve_db(args, config)
    connection = open_database(db_path, create=True)
    if connection.execute("SELECT count(*) FROM servers").fetchone()[0] or connection.execute("SELECT count(*) FROM observations").fetchone()[0]:
        raise CliError("the database is not empty — vpn-pulse demo clear first (or use a fresh --db)")
    catalog = ScenarioCatalog.load()
    if args.scenario not in catalog.ids:
        raise CliError(f"unknown scenario {args.scenario}; known: {', '.join(catalog.ids)}")
    seeded = seed_scenario(connection, catalog, args.scenario, now_utc(), contact_url=(config.get("app") or {}).get("admin_contact_url"))
    config["servers"] = seeded["servers"]
    write_config_atomic(config_path, config)
    marker = marker_path(db_path)
    marker.write_text(f"{args.scenario}\n", encoding="utf-8")
    out.line(f"demo scenario '{args.scenario}' seeded into {db_path}: {len(seeded['servers'])} fictional servers, seven days of history")
    out.line(f"config.yaml now lists those servers; marker {marker.name} makes the API answer mode=demo")
    out.line("Next: vpn-pulse run --demo   (keeps the demo world moving)   ·   vpn-pulse doctor")
    return 0


def command_clear(args: argparse.Namespace, out: Output) -> int:
    config_path = config_path_of(args)
    config = load_public_config(config_path)
    db_path = resolve_db(args, config)
    marker = marker_path(db_path)
    if not marker.exists():
        raise CliError("no demo marker next to the database — nothing to clear (this protects real data)", exit_code=1)
    if not confirm(args, f"Remove the demo data from {db_path} and the demo servers from {config_path}?", out):
        out.line("nothing changed")
        return 1
    connection = open_database(db_path)
    with connection:
        for table in TABLES_TO_CLEAR:
            connection.execute(f"DELETE FROM {table}")
    marker.unlink()
    config["servers"] = []
    write_config_atomic(config_path, config)
    out.line("demo data removed; config.yaml has no servers — vpn-pulse server add")
    return 0
