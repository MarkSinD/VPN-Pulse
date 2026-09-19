"""`python -m vpnpulse.dev` — run the API on demo scenarios and serve the Mini App prototype."""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m vpnpulse.dev", description="VPN Pulse dev server on demo scenarios")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--scenario", default="operational", help="default scenario for requests without ?scenario=")
    parser.add_argument("--fixtures", type=Path, default=None, help="path to fixtures/ui/scenarios.json")
    parser.add_argument("--app", type=Path, default=None, help="directory with the built Mini App (default: docs/prototypes)")
    parser.add_argument("--contact-url", default="https://t.me/example_admin")
    parser.add_argument("--sqlite", type=Path, default=None, help="serve --scenario from a real SQLite file through SqliteReadModel (seeded on first run)")
    parser.add_argument("--config", type=Path, default=None, help="with --sqlite: a real config.yaml over that database (nothing seeded) — live data with dev sessions, no Telegram needed")
    args = parser.parse_args()
    try:
        import uvicorn
    except ImportError:  # pragma: no cover - dev dependency
        parser.error("uvicorn is missing: pip install -e '.[dev]'")
    from vpnpulse.dev.scenarios import ScenarioCatalog
    from vpnpulse.dev.server import create_dev_app

    catalog = ScenarioCatalog.load(args.fixtures)
    config = None
    if args.config is not None:
        if args.sqlite is None:
            parser.error("--config needs --sqlite (the database the loop writes)")
        from vpnpulse.cli.common import load_public_config

        config = load_public_config(args.config)
    app = create_dev_app(catalog=catalog, default_scenario=args.scenario, app_dir=args.app, contact_url=args.contact_url, sqlite_path=args.sqlite, config=config)
    backend = f"sqlite {args.sqlite} · config {args.config}" if config else f"sqlite {args.sqlite} · scenario {args.scenario}" if args.sqlite else "scenarios: " + ", ".join(catalog.ids)
    print(f"VPN Pulse dev server: http://{args.host}:{args.port}/app/mvp.html  ({backend})")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
