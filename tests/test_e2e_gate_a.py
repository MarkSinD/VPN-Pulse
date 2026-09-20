"""Gate A — the local vertical slice in one test, on the production code paths.

    scripted world → `vpn-pulse run` (collect → evaluate → SQLite) → Telegram Bot API adapter on a
    fake transport → `vpn-pulse serve` (the API from config.yaml) → the Mini App in a real browser,
    opened the way Telegram opens it → the page's analytics back into the same database.

Nothing here is a test double of our own code: the loop, the store, the read model, the API, the
page and the Bot API adapter are the shipped ones. Only the outside world is faked — the clock, the
servers (`FixtureCollector`), Telegram's two endpoints (`sendMessage`, `getChatMember`).

The browser step needs Playwright with Chromium (`pip install playwright && playwright install
chromium`); without them the test is skipped, and CI runs it in the `browser` job.
"""
from __future__ import annotations

import json
import os
import socket
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import pytest
import yaml
from fastapi.testclient import TestClient

from test_api import init_data
from test_dev_server import response_schema, validate
from test_notify import BotApi
from test_pipeline_runner import PHASES, Clock, run_minutes
from test_serve import FakeTelegram
from vpnpulse.cli.common import Output, load_public_config, open_database
from vpnpulse.cli.run import make_notifier
from vpnpulse.collectors import FixtureCollector
from vpnpulse.dev.scenarios import ScenarioCatalog
from vpnpulse.dev.seed import config_for
from vpnpulse.notify import ConsoleNotifier, TelegramNotifier
from vpnpulse.pipeline import Pipeline
from vpnpulse.serve import build_app

TOKEN = "123456:e2e-token-not-a-real-secret"
GROUP = "-1001234567890"
ADMIN = 99
MEMBER = 10
CATALOG = ScenarioCatalog.load()
# the loop's 22 minutes end a minute before the real clock, so the page (real time) sees fresh data
START = (datetime.now(UTC) - timedelta(minutes=23)).replace(second=0, microsecond=0)
STATE_RU = {"operational": "Работает", "degraded": "Есть проблемы", "unavailable": "Не проходит проверка", "unknown": "Нет свежих данных"}

# how a Telegram client opens a Mini App: the signed initData (and the client's version and platform) in
# the location hash; telegram-web-app.js — vendored, served next to the page — turns it into
# window.Telegram.WebApp. No stub: the real bridge is part of what the gate checks.
def telegram_url(base: str, init: str) -> str:
    return f"{base}#tgWebAppData={quote(init, safe='')}&tgWebAppVersion=8.0&tgWebAppPlatform=android"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def install(tmp_path: Path) -> tuple[Path, dict, Path]:
    """What `vpn-pulse init` + `server add` leave behind: config.yaml, an empty database, a 0600 token."""
    config = config_for(CATALOG, CATALOG.build("operational", START))
    db = tmp_path / "data" / "vpnpulse.sqlite3"
    token_file = tmp_path / "secrets" / "bot.token"
    token_file.parent.mkdir(parents=True)
    token_file.write_text(TOKEN + "\n", encoding="utf-8")
    os.chmod(token_file, 0o600)
    config["storage"] = {"database": str(db)}
    config["telegram"] = {"bot_token_file": str(token_file), "group_chat_id": GROUP, "admin_chat_id": ADMIN}
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return cfg, load_public_config(cfg), db  # validated against the contract, like every command does


def wait_for(predicate, timeout: float = 10.0, what: str = "condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {what}")


REQUIRE_BROWSER = os.environ.get("VPNPULSE_REQUIRE_BROWSER") == "1"  # CI's browser job: a skip would hide a broken gate


def browser_or_skip():
    """Playwright's sync API and a launchable Chromium, or a skip — a failure when the browser is required."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        if REQUIRE_BROWSER:
            pytest.fail("VPNPULSE_REQUIRE_BROWSER=1 but Playwright is not installed")
        pytest.skip("Playwright is not installed; stages 1-2 passed, the browser stage is skipped")
    return sync_playwright


def test_gate_a_vertical_slice(tmp_path):
    uvicorn = pytest.importorskip("uvicorn")
    cfg, config, db = install(tmp_path)
    names = {s["id"]: s["name"]["ru"] for s in config["servers"]}

    # ---- 1. the loop: fixtures → evaluation → SQLite → the Bot API adapter on a fake transport ----
    bot = BotApi()
    out = Output(out=lambda _line: None, err=lambda _line: None)
    notifier = make_notifier(config, out, opener=bot)
    assert isinstance(notifier, TelegramNotifier)  # the flag: a token file and a group select the real adapter
    assert isinstance(make_notifier({**config, "telegram": None}, out), ConsoleNotifier)  # without them, the console
    clock = Clock(START)
    connection = open_database(db, create=True)
    pipeline = Pipeline(connection, config, collectors=[FixtureCollector(CATALOG, PHASES, start=START)], notifier=notifier, now=clock)
    run_minutes(pipeline, clock, 22)  # two quiet minutes, ten minutes of outage on s2, ten minutes back

    group = [body for _, body, _ in bot.requests if body["chat_id"] == GROUP]
    admin = [body for _, body, _ in bot.requests if body["chat_id"] == ADMIN]
    assert [b["text"].split(":")[0] for b in group] == [f"🔴 {names['s2']}", f"🟢 {names['s2']}"]  # the group: outage once, recovery once
    assert [b["text"][0] for b in admin] == ["🟡", "🟡"] and all(b["disable_notification"] for b in admin)  # the way down and up: admin, silent
    assert all(not b["disable_notification"] for b in group)
    assert all(url == f"https://api.telegram.org/bot{TOKEN}/sendMessage" for url, _, _ in bot.requests)
    assert all("s2" not in b["text"] and "203.0.113" not in b["text"] for b in group + admin)  # public names only
    assert connection.execute("SELECT count(*) FROM notification_queue WHERE state != 'sent'").fetchone()[0] == 0
    assert [r[0] for r in connection.execute("SELECT to_state FROM state_transitions WHERE scope_key = 'server:s2' ORDER BY confirmed_at, rowid")] == [
        "operational", "degraded", "unavailable", "degraded", "operational"]

    # ---- 2. the API process over the same file: `vpn-pulse serve` built from config.yaml ----
    telegram = FakeTelegram({MEMBER: "member"})
    app = build_app(cfg, now=clock, opener=telegram)
    assert app.state.mode == "live"
    api = TestClient(app, base_url="https://testserver")
    member_init = init_data(MEMBER, at=clock(), token=TOKEN, language="ru")
    assert api.post("/api/v1/sessions", json={"init_data": member_init}).status_code == 204
    assert api.get("/api/v1/sessions/current").json()["role"] == "member"
    status = api.get("/api/v1/status").json()
    validate(response_schema("/status", "get", "200"), status)
    cards = {c["id"]: c for c in status["servers"]}
    assert status["state"] == "operational" and cards["s2"]["state"] == "operational"
    assert cards["s1"]["uptime_24h"] == 1.0 and 0.0 < cards["s2"]["uptime_24h"] < 1.0  # the outage is in the 24-hour figure
    assert {s["source"] for s in status["sources"]} == {"pc", "mobile", "abroad"}
    events = api.get("/api/v1/events?filter=all&limit=50").json()
    validate(response_schema("/events", "get", "200"), events)
    s2_events = [e for e in events["items"] if e["server_id"] == "s2"]
    assert s2_events[0]["kind"] == "recovery" and [e["kind"] for e in s2_events[1:]].count("state_change") == 4
    for path, contract in (("/servers/s2", "/servers/{serverId}"), ("/servers/s2/metrics?period=24h", "/servers/{serverId}/metrics"), ("/help", "/help")):
        response = api.get("/api/v1" + path)
        assert response.status_code == 200, (path, response.text)
        validate(response_schema(contract, "get", "200"), response.json())
    denied = TestClient(app, base_url="https://testserver").post("/api/v1/sessions", json={"init_data": init_data(555, at=clock(), token=TOKEN)})
    assert denied.status_code == 403  # not in the group → no session (getChatMember was asked)
    assert telegram.calls and all(TOKEN in url for url in telegram.calls)

    # ---- 3. the Mini App in a browser, from that API, the way Telegram opens it ----
    sync_playwright = browser_or_skip()
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        wait_for(lambda: server.started, what="the API to start")
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch()
            except Exception as error:  # noqa: BLE001 - a missing Chromium is a tooling gap, not a code path
                if REQUIRE_BROWSER:
                    raise
                pytest.skip(f"Chromium for Playwright is not installed ({type(error).__name__}); run: playwright install chromium")
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.goto(telegram_url(f"http://127.0.0.1:{port}/app/mvp.html", member_init))
            page.wait_for_selector('body[data-load="ready"]', timeout=15000)
            assert page.get_attribute("body", "data-source") == "api"
            assert page.get_attribute("body", "data-showcase") == "hidden"  # the prototype's bar is not part of the product
            assert page.evaluate("window.Telegram.WebApp.initDataUnsafe.user.id") == MEMBER  # the bridge parsed the hash

            # the status screen shows what the loop wrote, under the public names, in the member's role
            rows = page.locator(".srow[data-server]")
            assert rows.count() == len(status["servers"])
            for card in status["servers"]:
                label = page.get_attribute(f'.srow[data-server="{card["id"]}"]', "aria-label")
                assert label.startswith(names[card["id"]]) and STATE_RU[card["state"]] in label, label
            assert page.locator('#app-nav [data-tab="admin"]').count() == 0

            # the feed shows the outage and the confirmed recovery of the second server
            page.click('#app-nav [data-tab="events"]')
            page.wait_for_selector(".ev .t")
            texts = page.locator(".ev .t").all_inner_texts()
            assert any(t.startswith(names["s2"]) and "работа подтверждена" in t for t in texts), texts
            assert any(t.startswith(names["s2"]) and STATE_RU["unavailable"] in t for t in texts), texts
            assert all("s2" not in t for t in texts)

            # what the page did comes back through POST /analytics/events:batch, shaped by the contract
            page.evaluate("window.VPNPulseShowcase.flush()")
            rows = wait_for(lambda: (
                r if len(r := connection.execute("SELECT name, surface, session_id, properties_json FROM product_events ORDER BY received_at, name").fetchall()) >= 3 else None
            ), what="analytics events in the database")
            assert {r[0] for r in rows} >= {"app_opened", "status_ready", "events_viewed"}
            assert {r[1] for r in rows} == {"mini_app"} and len({r[2] for r in rows}) == 1
            assert json.loads(next(r[3] for r in rows if r[0] == "app_opened"))["role"] == "member"
            assert all(str(MEMBER) not in r[3] and "s2" not in r[3] for r in rows)  # no identity, no ids beyond the allowlist
            assert page.evaluate("window.VPNPulseShowcase.analytics()")["queued"] == 0
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
