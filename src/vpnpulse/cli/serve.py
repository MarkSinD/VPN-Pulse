"""`vpn-pulse serve` — the API process for an installation (systemd unit `vpn-pulse-api`)."""
from __future__ import annotations

import argparse

from vpnpulse.cli.common import CliError, Output, config_path_of


def add_parser(commands, parents) -> None:
    p = commands.add_parser("serve", parents=parents, help="run the API (and the Mini App at /app/) from config.yaml")
    p.add_argument("--host", default="127.0.0.1", help="bind address (default 127.0.0.1 — put Caddy in front)")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--log-level", default="info")
    p.set_defaults(handler=command_serve)


def command_serve(args: argparse.Namespace, out: Output) -> int:
    try:
        import uvicorn
    except ImportError as error:  # pragma: no cover - dependency
        raise CliError("uvicorn is missing: pip install vpn-pulse") from error
    from vpnpulse.serve import build_app

    config_path = config_path_of(args)
    if config_path is None:
        raise CliError("vpn-pulse serve: --config PATH is required (or VPN_PULSE_CONFIG)")
    app = build_app(config_path)
    out.error(f"vpn-pulse serve ({app.state.mode}): http://{args.host}:{args.port}/app/mvp.html")
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)
    return 0
