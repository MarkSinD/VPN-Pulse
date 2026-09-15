"""Development server: the real API on demo scenarios, plus the built Mini App.

    python -m vpnpulse.dev                      # http://127.0.0.1:8765/app/mvp.html
    python -m vpnpulse.dev --scenario degraded  # default scenario for requests without ?scenario=

Every API request may carry `?scenario=<id>` (any id from fixtures/ui/scenarios.json except the
client-only `loading`), `?lang=ru|en` (server names, note text) and `?delay_ms=<n>` to see loading
states. Sessions come from `POST /api/v1/dev/session?role=member|admin` — Telegram init data cannot
be verified without a bot, so the dev server issues the cookie directly. Nothing here is shipped to
a real deployment: the dev routes live under /api/v1/dev/ and are not part of the contract.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from vpnpulse.api import create_app
from vpnpulse.auth import Identity
from vpnpulse.dev.scenarios import REQUEST, FixtureReadModel, ScenarioCatalog

DEV_BOT_TOKEN = "dev-server-not-a-real-token"


def repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "contracts" / "openapi.yaml").exists():
            return parent
    raise FileNotFoundError("run the dev server from a repository checkout (contracts/ not found)")


class DevMembership:
    """Everyone is a member; Telegram user 1 is the administrator (never used with real init data)."""

    def role_for(self, telegram_user_id: int) -> str | None:
        return "admin" if telegram_user_id == 1 else "member"


def create_dev_app(
    *,
    catalog: ScenarioCatalog | None = None,
    default_scenario: str = "operational",
    app_dir: Path | None = None,
    contact_url: str | None = "https://t.me/example_admin",
    now=None,
) -> FastAPI:
    root = repo_root()
    catalog = catalog or ScenarioCatalog.load()
    if default_scenario not in catalog.ids:
        raise ValueError(f"unknown scenario {default_scenario!r}; known: {', '.join(catalog.ids)}")
    now = now or (lambda: datetime.now(UTC))
    read_model = FixtureReadModel(catalog, default_scenario=default_scenario, contact_url=contact_url, now=now)
    app = create_app(
        bot_token=DEV_BOT_TOKEN,
        membership=DevMembership(),
        analytics_schema=root / "contracts" / "analytics-events.schema.json",
        read_model=read_model,
        contact_url=contact_url,
        now=now,
    )
    app.title = "VPN Pulse API — dev server"
    state = {"scenario": default_scenario}

    @app.middleware("http")
    async def scenario_context(request: Request, call_next):
        params = request.query_params
        scenario = params.get("scenario") or state["scenario"]
        if scenario not in catalog.ids:
            return Response(
                status_code=400,
                media_type="application/problem+json",
                content='{"type":"/problems/scenario_unknown","title":"Scenario Unknown","status":400,"code":"SCENARIO_UNKNOWN"}',
            )
        lang = params.get("lang") or (request.headers.get("accept-language") or "ru")[:2].lower()
        delay = params.get("delay_ms")
        if delay and delay.isdigit():
            await asyncio.sleep(min(int(delay), 10_000) / 1000)
        token = REQUEST.set({"scenario": scenario, "lang": lang})
        try:
            response = await call_next(request)
        finally:
            REQUEST.reset(token)
        response.headers["X-VPNPulse-Scenario"] = scenario
        return response

    @app.get("/api/v1/dev/scenarios", tags=["dev"])
    def list_scenarios():
        return {"default": state["scenario"], "scenarios": catalog.ids}

    @app.put("/api/v1/dev/scenario", tags=["dev"], status_code=204)
    def set_default_scenario(name: str):
        if name not in catalog.ids:
            raise HTTPException(status_code=400, detail={"code": "SCENARIO_UNKNOWN"})
        state["scenario"] = name

    @app.post("/api/v1/dev/session", tags=["dev"], status_code=204)
    def dev_session(response: Response, role: str = "member"):
        if role not in ("member", "admin"):
            raise HTTPException(status_code=400, detail={"code": "ROLE_INVALID"})
        req = REQUEST.get() or {}
        scenario = catalog.build(req.get("scenario") or state["scenario"], now())
        if scenario.raw.get("api") == "auth":
            raise HTTPException(status_code=403, detail={"code": scenario.raw.get("code", "MEMBERSHIP_REQUIRED")})
        session = app.state.sessions.create(Identity(1 if role == "admin" else 2, role), now())
        response.set_cookie("vpnpulse_session", session.token, httponly=True, samesite="lax", max_age=1800, path="/api/v1")

    static_dir = app_dir or (root / "docs" / "prototypes")
    if static_dir.exists():
        app.mount("/app", StaticFiles(directory=str(static_dir), html=True), name="app")

        @app.get("/", include_in_schema=False)
        def index():
            return RedirectResponse(url="/app/mvp.html")

    app.state.catalog = catalog
    app.state.dev_state = state
    return app
