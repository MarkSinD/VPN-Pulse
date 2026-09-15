"""The SQLite read model answers every read route, for every demo scenario, in contract shape.

Each scenario is seeded into a fresh database (vpnpulse.dev.seed) — servers, observations,
snapshots, transitions, events, note, probes — and the API is served by SqliteReadModel only.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from vpnpulse.api import create_app
from vpnpulse.dev.seed import seed_scenario
from vpnpulse.storage import SqliteReadModel, apply_migrations, connect
from test_api import ANALYTICS_SCHEMA, BOT_TOKEN, Membership, init_data
from test_dev_server import AUTH, CATALOG, OFFLINE, response_schema, validate

ROOT = Path(__file__).parents[1]
NOW = datetime(2026, 9, 15, 14, 45, tzinfo=UTC)
SCENARIOS = sorted(set(CATALOG.ids) - OFFLINE - AUTH)


def make_client(tmp_path, scenario: str, role: str):
    tmp_path.mkdir(parents=True, exist_ok=True)
    connection = connect(tmp_path / f"{scenario}.sqlite3")
    apply_migrations(connection, ROOT / "migrations")
    config = seed_scenario(connection, CATALOG, scenario, NOW)
    model = SqliteReadModel(connection, config, now=lambda: NOW, mode="demo" if scenario == "demo" else "live")
    app = create_app(bot_token=BOT_TOKEN, membership=Membership(), read_model=model, analytics_schema=ANALYTICS_SCHEMA, now=lambda: NOW)
    client = TestClient(app, base_url="https://testserver")
    assert client.post("/api/v1/sessions", json={"init_data": init_data(2 if role == "admin" else 1, at=NOW)}).status_code == 204
    return client, connection, model


@pytest.mark.parametrize("scenario", SCENARIOS)
@pytest.mark.parametrize("role", ["member", "admin"])
def test_every_read_route_from_sqlite_is_contract_valid(tmp_path, scenario, role):
    client, _, _ = make_client(tmp_path, scenario, role)
    status = client.get("/api/v1/status")
    assert status.status_code == 200, status.text
    payload = status.json()
    validate(response_schema("/status", "get", "200"), payload)
    expected = CATALOG.build(scenario, NOW)
    assert [c["id"] for c in payload["servers"]] == [s["id"] for s in expected.servers]
    for card in payload["servers"]:
        assert card["state"] == expected.server(card["id"])["state"], card["id"]
        for path, schema in (
            ("/api/v1/servers/" + card["id"], response_schema("/servers/{serverId}", "get", "200")),
            ("/api/v1/servers/" + card["id"] + "/metrics?period=24h", response_schema("/servers/{serverId}/metrics", "get", "200")),
            ("/api/v1/servers/" + card["id"] + "/metrics?period=7d", response_schema("/servers/{serverId}/metrics", "get", "200")),
        ):
            r = client.get(path)
            assert r.status_code == 200, (path, r.text)
            validate(schema, r.json())
        if role == "admin":
            r = client.get("/api/v1/admin/servers/" + card["id"])
            assert r.status_code == 200, r.text
            validate(response_schema("/admin/servers/{serverId}", "get", "200"), r.json())
    for flt in ("all", "problems", "notes"):
        r = client.get("/api/v1/events?filter=" + flt + "&limit=6")
        assert r.status_code == 200, r.text
        validate(response_schema("/events", "get", "200"), r.json())
    validate(response_schema("/help", "get", "200"), client.get("/api/v1/help").json())
    validate(response_schema("/health/ready", "get", "200"), client.get("/api/v1/health/ready").json())
    if role == "admin":
        validate(response_schema("/admin/probes", "get", "200"), client.get("/api/v1/admin/probes").json())
        validate(response_schema("/admin/overview", "get", "200"), client.get("/api/v1/admin/overview").json())
    # presence follows the probes table, exactly like the demo catalogue says
    assert {s["source"]: s["state"] for s in payload["sources"]} == {k: v for k, v in expected.presence.items() if v != "none"}


def test_availability_and_metrics_follow_the_timeline(tmp_path):
    client, _, _ = make_client(tmp_path, "degraded", "member")
    payload = client.get("/api/v1/status").json()
    s3 = next(c for c in payload["servers"] if c["id"] == "s3")
    s1 = next(c for c in payload["servers"] if c["id"] == "s1")
    assert s1["uptime_24h"] == 1.0 and s1["coverage_24h"] == 1.0
    assert s3["uptime_24h"] is not None and 0.9 < s3["uptime_24h"] < 1.0  # one degraded stretch counts half
    day = client.get("/api/v1/servers/s3/metrics?period=24h").json()
    week = client.get("/api/v1/servers/s3/metrics?period=7d").json()
    assert len(day["points"]) == 48 and len(week["points"]) == 168
    assert day["coverage"] == 1.0 and all(p["connections"] is not None for p in day["points"])
    assert day["points"][-1]["state"] == "degraded" and day["points"][0]["state"] == "operational"
    assert day["points"][0]["at"] < day["points"][-1]["at"]


def test_unknown_scenario_shows_gaps_and_stale_evidence(tmp_path):
    client, _, _ = make_client(tmp_path, "unknown", "member")
    payload = client.get("/api/v1/status").json()
    s1 = next(c for c in payload["servers"] if c["id"] == "s1")
    assert s1["state"] == "unknown" and s1["freshness"]["is_stale"]
    assert s1["coverage_24h"] is not None and s1["coverage_24h"] < 1.0
    day = client.get("/api/v1/servers/s1/metrics?period=24h").json()
    assert day["points"][-1]["state"] == "unknown" and day["points"][-1]["connections"] is None
    assert {s["source"]: s["state"] for s in payload["sources"]} == {"pc": "silent", "mobile": "silent", "abroad": "active"}
    detail = client.get("/api/v1/servers/s1").json()
    pc = next(e for e in detail["checks"] if e["source"] == "pc")
    assert pc["state"] == "unknown" and pc["reason_code"] == "pcSilent"


def test_language_note_events_and_role_visibility(tmp_path):
    client, connection, _ = make_client(tmp_path, "unavailable", "admin")
    ru = client.get("/api/v1/status", headers={"Accept-Language": "ru"}).json()
    en = client.get("/api/v1/status", headers={"Accept-Language": "en-GB,en;q=0.8"}).json()
    assert ru["servers"][0]["name"] == "Сервер 1" and en["servers"][0]["name"] == "Server 1"
    assert ru["note"]["text"].startswith("Похоже") and en["note"]["text"] == ru["note"]["text"]  # a note is written once, as is
    assert ru["recommended_server_id"] == "s1"
    notes = client.get("/api/v1/events?filter=notes").json()["items"]
    assert notes and all(e["kind"] == "note" for e in notes) and isinstance(notes[0]["params"]["text"], str)
    problems = client.get("/api/v1/events?filter=problems").json()["items"]
    assert problems and all(e["severity"] in ("warning", "critical") for e in problems)
    # an admin-only event is invisible to members
    connection.execute(
        "INSERT INTO events VALUES ('adm-1', 'monitoring', 'info', NULL, NULL, 'events.probeSilent', ?, ?, 'admin', ?)",
        ('{"source": "pc"}', NOW.isoformat(), NOW.isoformat()),
    )
    connection.commit()
    assert any(e["id"] == "adm-1" for e in client.get("/api/v1/events?limit=100").json()["items"])
    member, _, _ = make_client(tmp_path / "m", "unavailable", "member")
    assert not any(e["id"] == "adm-1" for e in member.get("/api/v1/events?limit=100").json()["items"])
    # blocked-in-country diagnosis reaches the administrator only
    admin_detail = client.get("/api/v1/admin/servers/s2").json()
    assert admin_detail["diagnostics"]["code"] == "BLOCKED_IN_COUNTRY"
    assert any(a["code"] == "BLOCKED_IN_COUNTRY" for a in admin_detail["attention_items"])


def test_doctor_and_readiness_derive_from_the_database(tmp_path):
    client, _, _ = make_client(tmp_path, "clean_install", "admin")
    overview = client.get("/api/v1/admin/overview", headers={"Accept-Language": "en"}).json()
    assert overview["doctor"]["result"] == "fail"
    assert [i["check"] for i in overview["doctor"]["items"]][:2] == ["servers", "probes"]
    assert overview["next_command"] == "vpn-pulse server add"
    assert overview["doctor"]["items"][0]["next"] == "Connect the first server"
    assert any(a["code"] == "PROBES_NOT_ENROLLED" for a in overview["attention_items"])
    ready = client.get("/api/v1/health/ready").json()
    assert ready["checks"]["database"]["ok"] and not ready["checks"]["collector"]["ok"]
    silent, _, _ = make_client(tmp_path / "u", "unknown", "admin")
    overview = silent.get("/api/v1/admin/overview").json()
    assert any(a["code"] == "PROBE_SILENT" and a["server_id"] is None for a in overview["attention_items"])
    assert any(i["check"] == "probes" and i["state"] == "warn" for i in overview["doctor"]["items"])


def test_no_read_route_touches_in_memory_state(tmp_path):
    """The same database answers identically from two independent API processes."""
    connection = connect(tmp_path / "shared.sqlite3")
    apply_migrations(connection, ROOT / "migrations")
    config = seed_scenario(connection, CATALOG, "degraded", NOW)
    payloads = []
    for _ in range(2):
        model = SqliteReadModel(connect(tmp_path / "shared.sqlite3"), config, now=lambda: NOW)
        app = create_app(bot_token=BOT_TOKEN, membership=Membership(), read_model=model, analytics_schema=ANALYTICS_SCHEMA, now=lambda: NOW)
        client = TestClient(app, base_url="https://testserver")
        client.post("/api/v1/sessions", json={"init_data": init_data(2, at=NOW)})
        payloads.append((client.get("/api/v1/status").json(), client.get("/api/v1/admin/overview").json(), client.get("/api/v1/servers/s2").json()))
    assert payloads[0] == payloads[1]


def test_seeded_collector_payloads_match_the_schema(tmp_path):
    import json
    import jsonschema
    schema = json.loads((ROOT / "contracts" / "collector-observation.schema.json").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    _, connection, _ = make_client(tmp_path, "degraded", "admin")
    rows = connection.execute("SELECT metrics_json FROM observations WHERE source_kind = 'collector'").fetchall()
    assert rows
    for (metrics_json,) in rows:
        validator.validate(json.loads(metrics_json))


def test_dev_server_can_serve_a_scenario_from_sqlite(tmp_path):
    from vpnpulse.dev import create_dev_app
    app = create_dev_app(catalog=CATALOG, default_scenario="degraded", sqlite_path=tmp_path / "dev.sqlite3", now=lambda: NOW)
    client = TestClient(app)
    assert client.post("/api/v1/dev/session?role=admin").status_code == 204
    payload = client.get("/api/v1/status?scenario=unavailable").json()  # a database holds one scenario
    assert payload["state"] == "degraded" and [s["id"] for s in payload["servers"]] == ["s1", "s2", "s3"]
    validate(response_schema("/status", "get", "200"), payload)
    # a second start reuses the seeded database instead of seeding twice
    again = create_dev_app(catalog=CATALOG, default_scenario="degraded", sqlite_path=tmp_path / "dev.sqlite3", now=lambda: NOW)
    assert TestClient(again).get("/api/v1/health/live").status_code == 200
