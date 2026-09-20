"""`vpn-pulse probe enroll | list | revoke` — the check sources' lifecycle.

`enroll` prints a single-use code (ten minutes by default); the agent exchanges it at
`POST /api/v1/probe/enroll` for its own token, which nobody else ever sees. The code is shown once
on the terminal and is stored only as a hash; the audit entry records the kind, not the code.
"""
from __future__ import annotations

import argparse

from vpnpulse.cli.common import CliError, Output, config_path_of, confirm, load_public_config, make_read_model, make_store, open_database, resolve_db

KINDS = ("pc", "android", "abroad", "watchdog")
CAPABILITY = {"pc": ["report_pc"], "android": ["report_mobile"], "abroad": ["report_abroad"], "watchdog": ["read_watchdog"]}
GUIDE = {"pc": "docs/probes/pc.md", "android": "docs/probes/android.md", "abroad": "docs/probes/abroad.md", "watchdog": "docs/operations/doctor.md"}


def add_parser(commands, parents) -> None:
    probe = commands.add_parser("probe", parents=parents, help="check sources: enroll, list, revoke")
    sub = probe.add_subparsers(dest="action", required=True)
    enroll = sub.add_parser("enroll", parents=parents, help="print a single-use enrollment code")
    enroll.add_argument("kind", choices=KINDS)
    enroll.add_argument("--via", metavar="SERVER_ID", help="server that hosts an abroad probe")
    enroll.add_argument("--minutes", type=int, default=10, help="how long the code stays valid (default 10)")
    enroll.set_defaults(handler=command_enroll)
    ls = sub.add_parser("list", parents=parents, help="enrolled probes and their last reports")
    ls.add_argument("--json", action="store_true")
    ls.set_defaults(handler=command_list)
    revoke = sub.add_parser("revoke", parents=parents, help="revoke a probe's token")
    revoke.add_argument("id")
    revoke.add_argument("--yes", action="store_true")
    revoke.set_defaults(handler=command_revoke)


def _open(args):
    config = load_public_config(config_path_of(args))
    connection = open_database(resolve_db(args, config))
    return config, connection


def command_enroll(args: argparse.Namespace, out: Output) -> int:
    if args.minutes < 1 or args.minutes > 60:
        raise CliError("--minutes must be between 1 and 60")
    config, connection = _open(args)
    if args.via and args.kind != "abroad":
        raise CliError("--via is only valid for an abroad probe")
    if args.kind == "abroad" and not args.via:
        raise CliError("an abroad probe requires --via SERVER_ID")
    if args.via and args.via not in {s["id"] for s in config.get("servers", []) if s.get("enabled", True)}:
        raise CliError(f"server {args.via} not found")
    store = make_store(connection, config, enrollment_minutes=args.minutes)
    code, expires = store.create_enrollment(args.kind, CAPABILITY[args.kind], "cli", via_server_id=args.via)
    store.audit(actor="cli", role="admin", action="probe.enroll_code", target_type="probe", target_id=args.kind, details={"minutes": args.minutes})
    out.line(f"Enrollment code for the {args.kind} probe (single use, valid until {expires.strftime('%H:%M UTC')}):")
    out.line("")
    out.line(f"    {code}")
    out.line("")
    out.line("Enter it in the probe; it exchanges the code at POST /api/v1/probe/enroll for its own token.")
    out.line(f"Setup guide: {GUIDE[args.kind]}. Afterwards: vpn-pulse probe list")
    return 0


def command_list(args: argparse.Namespace, out: Output) -> int:
    config, connection = _open(args)
    probes = make_read_model(connection, config).admin_probes()
    if args.json:
        out.json(probes)
        return 0
    if not probes:
        out.line("no probes enrolled — vpn-pulse probe enroll pc")
        return 0
    width = max(len(p["id"]) for p in probes)
    for p in probes:
        last = p["last_seen_at"] or "never"
        route = {True: "route ok", False: "route NOT verified", None: ""}[p["route_verified"]]
        out.line(f"{p['id']:<{width}}  {p['kind']:<8}  {p['status']:<8}  last report {last}  {p['network_type'] or ''} {route}  v{p['agent_version'] or '?'}")
    return 0


def command_revoke(args: argparse.Namespace, out: Output) -> int:
    config, connection = _open(args)
    store = make_store(connection, config)
    if store.probe_summary(args.id) is None:
        raise CliError(f"probe {args.id} not found (vpn-pulse probe list)", exit_code=1)
    if not confirm(args, f"Revoke {args.id}? Its token stops working immediately", out):
        out.line("nothing changed")
        return 1
    revoked = store.revoke_probe(args.id)
    store.audit(actor="cli", role="admin", action="probe.revoke", target_type="probe", target_id=args.id, result="ok" if revoked else "noop")
    out.line(f"revoked {args.id}" if revoked else f"{args.id} was already revoked")
    return 0
