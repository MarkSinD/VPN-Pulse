"""The dev server answers every read route for every demo scenario with contract-valid payloads.

This is the gate for R-01 and the safety net for R-02: if a scenario, a schema or the presenter
drifts, the exact route and scenario are named here before the Mini App sees them.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
import jsonschema
import pytest
import yaml

from vpnpulse.dev import ScenarioCatalog, create_dev_app

NOW = datetime(2026, 9, 15, 14, 45, tzinfo=UTC)


def _root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "contracts" / "openapi.yaml").exists():
            return parent
    raise FileNotFoundError("repository root not found")


OPENAPI = yaml.safe_load((_root() / "contracts" / "openapi.yaml").read_text(encoding="utf-8"))
CATALOG = ScenarioCatalog.load(_root() / "fixtures" / "ui" / "scenarios.json")
OFFLINE = {sid for sid in CATALOG.ids if CATALOG.merged(sid).get("api") == "offline"}
AUTH = {sid for sid in CATALOG.ids if CATALOG.merged(sid).get("api") == "auth"}


def validate(schema, payload) -> None:
    root = {**schema, "components": OPENAPI["components"]} if "$ref" not in schema else {"$ref": schema["$ref"], "components": OPENAPI["components"]}
    jsonschema.Draft202012Validator(root).validate(payload)


def response_schema(path: str, method: str, code: str) -> dict:
    op = OPENAPI["paths"][path][method]
    return op["responses"][code]["content"]["application/json"]["schema"]


@pytest.fixture(scope="module")
def client() -> TestClient:
    app = create_dev_app(catalog=CATALOG, now=lambda: NOW, app_dir=_root() / "docs" / "prototypes")
    return TestClient(app)


def login(client: TestClient, role: str, scenario: str) -> None:
    client.cookies.clear()
    response = client.post(f"/api/v1/dev/session?role={role}&scenario={scenario}")
    assert response.status_code == 204, response.text


def test_scenario_list_excludes_client_only_states(client):
    ids = client.get("/api/v1/dev/scenarios").json()["scenarios"]
    assert "loading" not in ids and "operational" in ids and "no_pc" in ids
    assert client.get("/api/v1/status?scenario=nope").status_code == 400


@pytest.mark.parametrize("scenario", sorted(set(CATALOG.ids) - OFFLINE - AUTH))
@pytest.mark.parametrize("role", ["member", "admin"])
def test_every_read_route_is_contract_valid(client, scenario, role):
    login(client, role, scenario)
    q = f"?scenario={scenario}"
    status = client.get("/api/v1/status" + q)
    assert status.status_code == 200, status.text
    validate(response_schema("/status", "get", "200"), status.json())
    payload = status.json()
    # every existing source is one of the three kinds, and hidden kinds never appear on cards
    kinds = {s["source"] for s in payload.get("sources", [])}
    for card in payload["servers"]:
        assert {s["source"] for s in card["sources"]} - {"human_activity", "collector"} <= kinds
        for path, schema in (
            (f"/api/v1/servers/{card['id']}", response_schema("/servers/{serverId}", "get", "200")),
            (f"/api/v1/servers/{card['id']}/metrics?period=24h&", response_schema("/servers/{serverId}/metrics", "get", "200")),
            (f"/api/v1/servers/{card['id']}/metrics?period=7d&", response_schema("/servers/{serverId}/metrics", "get", "200")),
        ):
            sep = "&" if "?" in path else "?"
            r = client.get(path + sep + q[1:])
            assert r.status_code == 200, (path, r.text)
            validate(schema, r.json())
        if role == "admin":
            r = client.get(f"/api/v1/admin/servers/{card['id']}" + q)
            assert r.status_code == 200, r.text
            validate(response_schema("/admin/servers/{serverId}", "get", "200"), r.json())
    for flt in ("all", "problems", "notes"):
        r = client.get(f"/api/v1/events?filter={flt}&limit=6&scenario={scenario}")
        assert r.status_code == 200, r.text
        validate(response_schema("/events", "get", "200"), r.json())
    validate(response_schema("/help", "get", "200"), client.get("/api/v1/help" + q).json())
    validate(response_schema("/health/ready", "get", "200"), client.get("/api/v1/health/ready" + q).json())
    if role == "admin":
        r = client.get("/api/v1/admin/probes" + q)
        assert r.status_code == 200
        validate(response_schema("/admin/probes", "get", "200"), r.json())
        r = client.get("/api/v1/admin/overview" + q)
        assert r.status_code == 200, r.text
        validate(response_schema("/admin/overview", "get", "200"), r.json())
    else:
        assert client.get("/api/v1/admin/probes" + q).status_code == 403
        assert client.get("/api/v1/admin/overview" + q).status_code == 403


def test_offline_scenario_is_a_503_problem(client):
    login(client, "member", "operational")
    r = client.get("/api/v1/status?scenario=offline")
    assert r.status_code == 503
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == "STATUS_UNAVAILABLE"


def test_auth_scenario_refuses_the_session(client):
    client.cookies.clear()
    r = client.post("/api/v1/dev/session?role=member&scenario=auth")
    assert r.status_code == 403 and r.json()["code"] == "MEMBERSHIP_REQUIRED"


def test_events_paginate_and_filter(client):
    login(client, "member", "unavailable")
    first = client.get("/api/v1/events?limit=3&scenario=unavailable").json()
    assert len(first["items"]) == 3 and first["next_cursor"] == "3"
    second = client.get(f"/api/v1/events?limit=3&cursor={first['next_cursor']}&scenario=unavailable").json()
    assert {e["id"] for e in first["items"]}.isdisjoint({e["id"] for e in second["items"]})
    notes = client.get("/api/v1/events?filter=notes&scenario=unavailable").json()["items"]
    assert notes and all(e["kind"] == "note" for e in notes)
    problems = client.get("/api/v1/events?filter=problems&scenario=unavailable").json()["items"]
    assert problems and all(e["severity"] in ("warning", "critical") for e in problems)


def test_sources_follow_probe_presence(client):
    login(client, "member", "no_pc")
    payload = client.get("/api/v1/status?scenario=no_pc").json()
    assert [s["source"] for s in payload["sources"]] == ["mobile", "abroad"]
    assert all({s["source"] for s in card["sources"]} - {"human_activity"} == {"mobile", "abroad"} for card in payload["servers"])
    partial = client.get("/api/v1/status?scenario=partial_coverage").json()
    assert partial["sources"] == [] and partial["coverage"] == 0
    unknown = client.get("/api/v1/status?scenario=unknown").json()
    assert {s["source"]: s["state"] for s in unknown["sources"]} == {"pc": "silent", "mobile": "silent", "abroad": "active"}


def test_language_selects_names_and_note_text(client):
    login(client, "member", "unavailable")
    ru = client.get("/api/v1/status?scenario=unavailable&lang=ru").json()
    en = client.get("/api/v1/status?scenario=unavailable", headers={"Accept-Language": "en-GB,en;q=0.9"}).json()
    assert ru["servers"][0]["name"] == "Сервер 1" and en["servers"][0]["name"] == "Server 1"
    assert ru["note"]["text"] != en["note"]["text"]


def test_admin_note_override_and_probe_revoke(client):
    login(client, "admin", "operational")
    assert client.get("/api/v1/status?scenario=operational").json()["note"] is None
    put = client.put("/api/v1/admin/note?scenario=operational", json={"text": "Maintenance at 02:00"})
    assert put.status_code == 200
    assert client.get("/api/v1/status?scenario=operational").json()["note"]["text"] == "Maintenance at 02:00"
    assert client.delete("/api/v1/admin/note?scenario=operational").status_code == 204
    assert client.get("/api/v1/status?scenario=operational").json()["note"] is None
    assert client.post("/api/v1/admin/probes/probe-android/revoke?scenario=operational").status_code == 204
    probes = {p["id"]: p["status"] for p in client.get("/api/v1/admin/probes?scenario=operational").json()}
    assert probes["probe-android"] == "revoked" and probes["probe-pc"] == "active"
    assert client.post("/api/v1/admin/probes/nope/revoke?scenario=operational").status_code == 404


def test_metrics_shape_matches_period(client):
    login(client, "member", "unknown")
    day = client.get("/api/v1/servers/s1/metrics?period=24h&scenario=unknown").json()
    week = client.get("/api/v1/servers/s1/metrics?period=7d&scenario=unknown").json()
    assert len(day["points"]) == 48 and len(week["points"]) == 168
    assert day["coverage"] < 1 and day["points"][-1]["connections"] is None  # gap at the end of the day
    assert day["points"][0]["at"] < day["points"][-1]["at"]
    assert client.get("/api/v1/servers/s1/metrics?period=1h&scenario=unknown").status_code == 400
    assert client.get("/api/v1/servers/nope/metrics?period=24h&scenario=unknown").status_code == 404


def test_overview_carries_installation_wide_attention_and_doctor(client):
    login(client, "admin", "clean_install")
    o = client.get("/api/v1/admin/overview?scenario=clean_install").json()
    assert o["doctor"]["result"] == "fail" and o["next_command"] == "vpn-pulse server add"
    o = client.get("/api/v1/admin/overview?scenario=unknown&lang=en").json()
    assert any(a["server_id"] is None and a["code"] == "PROBE_SILENT" for a in o["attention_items"])
    assert o["doctor"]["items"][0]["next"].startswith("Wake the computer")


def test_session_info_reports_the_role(client):
    login(client, "admin", "operational")
    me = client.get("/api/v1/sessions/current").json()
    validate(response_schema("/sessions/current", "get", "200"), me)
    assert me["role"] == "admin"
    client.cookies.clear()
    assert client.get("/api/v1/sessions/current").status_code == 401


def test_static_app_is_served(client):
    r = client.get("/app/mvp.html")
    assert r.status_code == 200 and "VPN Pulse" in r.text
    assert client.get("/", follow_redirects=False).status_code == 307


def test_dev_server_serves_a_real_config_over_a_real_database(tmp_path):
    """--sqlite + --config: the loop's database as it is, with dev sessions instead of Telegram."""
    import yaml
    from vpnpulse.cli import main as cli_main
    from vpnpulse.cli.common import Output

    sink = Output(out=lambda _: None, err=lambda _: None)
    assert cli_main(["init", "--dir", str(tmp_path / "inst"), "--language", "en"], out=sink) == 0
    cfg = tmp_path / "inst" / "config.yaml"
    assert cli_main(["server", "add", "--config", str(cfg), "--id", "real-1", "--type", "awg-host", "--name-ru", "Первый", "--name-en", "First", "--country", "NL"], out=sink) == 0
    assert cli_main(["run", "--config", str(cfg), "--once", "--quiet"], out=sink) == 0
    config = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    app = create_dev_app(catalog=CATALOG, default_scenario="demo", sqlite_path=Path(config["storage"]["database"]), config=config)
    client = TestClient(app, base_url="https://testserver")
    assert client.post("/api/v1/dev/session?role=admin").status_code == 204
    status = client.get("/api/v1/status").json()
    assert status["mode"] == "live" and [s["id"] for s in status["servers"]] == ["real-1"]  # nothing seeded, no demo mark
    assert status["servers"][0]["name"] == "First"
    assert client.get("/api/v1/admin/overview").status_code == 200
