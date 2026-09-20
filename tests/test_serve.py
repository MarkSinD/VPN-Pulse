"""`vpn-pulse serve` (the production API process) and the Telegram membership check."""
import io
import json
import urllib.error
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from test_api import init_data
from test_cli import TOKEN, run_cli
from vpnpulse.serve import build_app
from vpnpulse.telegram import NoMembership, TelegramMembership

NOW = datetime(2026, 9, 16, 9, 0, tzinfo=UTC)


class FakeTelegram:
    """Answers getChatMember from a table; records the calls and can fail on demand."""

    def __init__(self, members: dict[int, str], fail: bool = False) -> None:
        self.members = members
        self.fail = fail
        self.calls: list[str] = []

    def __call__(self, request, timeout=None):
        self.calls.append(request.full_url)
        if self.fail:
            raise urllib.error.URLError("offline")
        user_id = int(request.full_url.rsplit("user_id=", 1)[1])
        status = self.members.get(user_id, "left")
        body = json.dumps({"ok": True, "result": {"status": status, "is_member": status == "restricted"}}).encode()

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        return Response(body)


def test_telegram_membership_roles_cache_and_outage():
    telegram = FakeTelegram({10: "member", 11: "administrator", 12: "restricted", 13: "left"})
    clock = {"at": NOW}
    membership = TelegramMembership(TOKEN, "-1001234567890", {99}, opener=telegram, now=lambda: clock["at"])
    assert membership.role_for(99) == "admin" and telegram.calls == []  # the configured administrator needs no request
    assert membership.role_for(10) == "member" and membership.role_for(11) == "member" and membership.role_for(12) == "member"
    assert membership.role_for(13) is None
    assert len(telegram.calls) == 4 and all(TOKEN in url and "chat_id=-1001234567890" in url for url in telegram.calls)
    assert membership.role_for(10) == "member" and len(telegram.calls) == 4  # cached
    clock["at"] = NOW + timedelta(minutes=6)
    telegram.fail = True
    assert membership.role_for(10) == "member"  # an outage keeps the last answer
    assert membership.role_for(42) is None  # a new face waits for Telegram
    assert NoMembership().role_for(10) is None


def test_serve_builds_the_api_and_the_mini_app_from_config(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(TOKEN + "\n"))
    code, sink = run_cli("init", "--dir", tmp_path / "inst", "--language", "en", "--telegram-token-stdin", "--group-chat-id", "-1001234567890", "--admin-chat-id", "99")
    assert code == 0, sink.text
    cfg = tmp_path / "inst" / "config.yaml"
    code, sink = run_cli("demo", "seed", "--config", cfg)
    assert code == 0, sink.text
    assert (tmp_path / "inst" / "data" / "demo-data").exists()
    assert [s["id"] for s in yaml.safe_load(cfg.read_text(encoding="utf-8"))["servers"]] == ["s1", "s2", "s3"]
    code, sink = run_cli("demo", "seed", "--config", cfg)
    assert code == 2 and "not empty" in sink.text

    telegram = FakeTelegram({10: "member"})
    app = build_app(cfg, opener=telegram)  # the real clock: the seed is anchored to it
    client = TestClient(app, base_url="https://testserver")
    now = datetime.now(UTC)
    assert client.get("/api/v1/health/live").status_code == 200
    page = client.get("/app/mvp.html").text
    assert client.get("/").status_code == 200 and "<html" in page.lower()
    # Telegram's bridge comes from our own origin, in <head>, before any script of the page: without it a
    # real client has no initData and every visitor sees "members only"
    head = page.split("</head>")[0]
    assert '<script src="telegram-web-app.js"></script>' in head and head.index("<script") == head.index('<script src="telegram-web-app.js">')
    bridge = client.get("/app/telegram-web-app.js")
    assert bridge.status_code == 200 and "javascript" in bridge.headers["content-type"] and "WebApp" in bridge.text
    # every open asks the server again (a WebView would otherwise keep a page for hours); unchanged → 304
    first = client.get("/app/mvp.html")
    assert first.headers["cache-control"] == "no-cache" and bridge.headers["cache-control"] == "no-cache"
    again = client.get("/app/mvp.html", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304 and again.headers["cache-control"] == "no-cache"
    assert client.get("/api/v1/dev/scenarios").status_code == 404  # no dev routes in production
    # membership: the configured administrator gets in without Telegram; an unknown user does not
    assert client.post("/api/v1/sessions", json={"init_data": init_data(99, at=now, token=TOKEN)}).status_code == 204
    status = client.get("/api/v1/status").json()
    assert status["mode"] == "demo" and [s["id"] for s in status["servers"]] == ["s1", "s2", "s3"]
    assert client.get("/api/v1/sessions/current").json()["role"] == "admin"
    assert client.get("/api/v1/admin/overview").json()["doctor"]["result"] == "ok"
    client.cookies.clear()
    assert client.post("/api/v1/sessions", json={"init_data": init_data(10, at=now, token=TOKEN)}).status_code == 204
    assert client.get("/api/v1/sessions/current").json()["role"] == "member"
    client.cookies.clear()
    denied = client.post("/api/v1/sessions", json={"init_data": init_data(555, at=now, token=TOKEN)})
    assert denied.status_code == 403 and len(telegram.calls) == 2

    code, sink = run_cli("demo", "clear", "--config", cfg, "--yes")
    assert code == 0 and yaml.safe_load(cfg.read_text(encoding="utf-8"))["servers"] == []
    assert build_app(cfg, opener=telegram).state.mode == "live"


def test_serve_without_telegram_serves_health_and_denies_sessions(tmp_path):
    code, sink = run_cli("init", "--dir", tmp_path / "inst")
    assert code == 0, sink.text
    app = build_app(tmp_path / "inst" / "config.yaml", now=lambda: NOW)
    client = TestClient(app, base_url="https://testserver")
    assert client.get("/api/v1/health/live").status_code == 200
    assert client.post("/api/v1/sessions", json={"init_data": init_data(1, at=NOW, token="")}).status_code in (401, 403)
    assert app.state.mode == "live"
