"""The production API process: `vpn-pulse serve` (behind Caddy, next to `vpn-pulse run`).

Everything comes from `config.yaml`: the database (`storage.database`), the bot token file and
group for Telegram membership (`telegram`), names and languages. The Mini App is served from
`/app/` by the same process so the API and the page share one origin; there are no dev routes.
When the data directory carries a `demo-data` marker (written by `vpn-pulse demo seed`) the status
answers `mode: demo` and the Mini App shows its "Demo data" mark.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from vpnpulse.api import create_app
from vpnpulse.cli.common import CliError, contracts_dir, load_public_config, open_database, repo_root, resolve_db
from vpnpulse.storage import SqliteReadModel, SqliteStore
from vpnpulse.telegram import NoMembership, TelegramMembership

DEMO_MARKER = "demo-data"


def demo_marker(db_path: Path) -> Path:
    return db_path.parent / DEMO_MARKER


def build_app(config_path: Path, *, now=None, opener=None) -> FastAPI:
    """`opener` replaces urllib for the Telegram membership check (tests)."""
    now = now or (lambda: datetime.now(UTC))
    config = load_public_config(config_path)
    db_path = resolve_db(None, config)
    connection = open_database(db_path, create=True)
    telegram = config.get("telegram") or {}
    token = ""
    membership = NoMembership()
    if telegram:
        token_file = Path(telegram["bot_token_file"])
        if not token_file.exists() or not token_file.read_text(encoding="utf-8").strip():
            raise CliError(f"telegram token file {token_file}: missing or empty (vpn-pulse doctor telegram)")
        token = token_file.read_text(encoding="utf-8").strip()
        admin_ids: set[int] = set()
        admin = str(telegram.get("admin_chat_id") or "")
        if admin.lstrip("-").isdigit() and int(admin) > 0:
            admin_ids.add(int(admin))
        membership = TelegramMembership(token, telegram["group_chat_id"], admin_ids, now=now, opener=opener)
    mode = "demo" if demo_marker(db_path).exists() else "live"
    read_model = SqliteReadModel(connection, config, now=now, mode=mode)
    store = SqliteStore(connection, analytics_schema=contracts_dir() / "analytics-events.schema.json", config=config, pepper=token or "vpn-pulse", now=now)
    app_cfg = config.get("app") or {}
    app = create_app(
        bot_token=token,
        membership=membership,
        analytics_schema=contracts_dir() / "analytics-events.schema.json",
        read_model=read_model,
        store=store,
        config=config,
        contact_url=app_cfg.get("admin_contact_url"),
        default_language=app_cfg.get("default_language", "ru"),
        now=now,
    )
    static_dir = repo_root() / "docs" / "prototypes"
    if static_dir.exists():
        app.mount("/app", StaticFiles(directory=str(static_dir), html=True), name="app")

        @app.get("/", include_in_schema=False)
        def index():
            return RedirectResponse(url="/app/mvp.html")

    app.state.mode = mode
    return app


def app_from_environment() -> FastAPI:
    """Factory for `uvicorn vpnpulse.serve:app_from_environment --factory`."""
    config = os.environ.get("VPN_PULSE_CONFIG")
    if not config:
        raise CliError("VPN_PULSE_CONFIG is not set")
    return build_app(Path(config))
