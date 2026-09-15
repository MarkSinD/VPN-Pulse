"""Everything the API writes lives in SQLite: sessions, enrollment codes, probes, reports,
observations, the note, analytics and audit — and survives a process restart.

Two `create_app` instances over the same database file play the role of two processes.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from vpnpulse.api import create_app
from vpnpulse.storage import SqliteReadModel, SqliteStore, apply_migrations, connect
from test_api import ANALYTICS_SCHEMA, BOT_TOKEN, Membership, init_data

ROOT = Path(__file__).parents[1]
NOW = datetime(2026, 9, 15, 15, 0, tzinfo=UTC)
CONFIG = {
    "version": 1,
    "app": {"default_language": "ru", "languages": ["ru", "en"], "timezone": "UTC", "admin_contact_url": "https://t.me/example_admin"},
    "servers": [{"id": "s1", "type": "awg-host", "name": {"ru": "Сервер 1", "en": "Server 1"}, "country_code": "LV", "enabled": True, "recommended_priority": 10}],
    "monitoring": {"collection_interval_seconds": 60, "pc_target_interval_seconds": 60, "probe_deadline_seconds": 20, "confirmations": 2, "freshness_seconds": 180},
    "retention": {"observations_days": 7, "aggregates_days": 90, "events_days": 180, "analytics_raw_days": 30, "audit_days": 365},
}


class Clock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at


def new_database(path: Path):
    connection = connect(path)
    apply_migrations(connection, ROOT / "migrations")
    with connection:
        connection.execute("INSERT INTO servers VALUES ('s1', 's1', 'awg-host', 1, 1, ?, ?)", (NOW.isoformat(), NOW.isoformat()))
    return connection


def process(path: Path, clock: Clock) -> TestClient:
    """One API process over the shared database file."""
    connection = connect(path)
    store = SqliteStore(connection, analytics_schema=ANALYTICS_SCHEMA, config=CONFIG, pepper=BOT_TOKEN, now=clock)
    app = create_app(bot_token=BOT_TOKEN, membership=Membership(), read_model=SqliteReadModel(connection, CONFIG, now=clock),
                     store=store, config=CONFIG, analytics_schema=ANALYTICS_SCHEMA, now=clock)
    return TestClient(app, base_url="https://testserver")


def login(client: TestClient, user_id: int, at: datetime) -> str:
    response = client.post("/api/v1/sessions", json={"init_data": init_data(user_id, at=at)})
    assert response.status_code == 204, response.text
    return response.cookies["vpnpulse_session"]


def test_session_survives_a_restart_and_can_be_revoked(tmp_path):
    new_database(tmp_path / "db.sqlite3")
    clock = Clock(NOW)
    first = process(tmp_path / "db.sqlite3", clock)
    token = login(first, 2, NOW)
    second = process(tmp_path / "db.sqlite3", clock)
    second.cookies.set("vpnpulse_session", token)
    assert second.get("/api/v1/sessions/current").json()["role"] == "admin"
    clock.at = NOW + timedelta(minutes=31)
    assert second.get("/api/v1/sessions/current").status_code == 401  # expired
    clock.at = NOW
    assert second.delete("/api/v1/sessions/current").status_code == 204
    assert first.get("/api/v1/sessions/current").status_code == 401  # revoked everywhere


def test_enrollment_code_is_single_use_and_expires(tmp_path):
    new_database(tmp_path / "db.sqlite3")
    clock = Clock(NOW)
    admin = process(tmp_path / "db.sqlite3", clock)
    login(admin, 2, NOW)
    code = admin.post("/api/v1/admin/probe-enrollments", json={"kind": "pc", "capabilities": ["report_pc"]}).json()["code"]
    assert len(code) >= 20
    agent = process(tmp_path / "db.sqlite3", clock)  # the probe talks to another worker
    joined = agent.post("/api/v1/probe/enroll", json={"code": code, "agent_version": "0.1.0", "schema_version": 1})
    assert joined.status_code == 201
    assert joined.json()["config"]["targets"] == [{"id": "s1", "checks": ["control_internet", "handshake", "https"]}]
    assert agent.post("/api/v1/probe/enroll", json={"code": code, "agent_version": "0.1.0", "schema_version": 1}).status_code == 401
    late = admin.post("/api/v1/admin/probe-enrollments", json={"kind": "android", "capabilities": ["report_mobile"]}).json()["code"]
    clock.at = NOW + timedelta(minutes=11)
    assert agent.post("/api/v1/probe/enroll", json={"code": late, "agent_version": "0.1.0", "schema_version": 1}).status_code == 401


def test_report_is_idempotent_and_becomes_evidence(tmp_path):
    connection = new_database(tmp_path / "db.sqlite3")
    clock = Clock(NOW)
    admin = process(tmp_path / "db.sqlite3", clock)
    login(admin, 2, NOW)
    code = admin.post("/api/v1/admin/probe-enrollments", json={"kind": "pc", "capabilities": ["report_pc"]}).json()["code"]
    token = admin.post("/api/v1/probe/enroll", json={"code": code, "agent_version": "0.1.0", "schema_version": 1}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    report = {
        "report_id": str(uuid4()), "schema_version": 1, "agent_version": "0.1.0", "observed_at": NOW.isoformat(),
        "network": {"type": "home", "ip_family": "ipv4", "route_verified": True},
        "results": [
            {"target_id": "s1", "check": "control_internet", "result": "success", "duration_ms": 30},
            {"target_id": "s1", "check": "handshake", "result": "success", "duration_ms": 80},
            {"target_id": "s1", "check": "https", "result": "success", "duration_ms": 120},
            {"target_id": "ghost", "check": "handshake", "result": "failure", "duration_ms": 5000, "error_code": "timeout"},
        ],
    }
    worker = process(tmp_path / "db.sqlite3", clock)
    assert worker.post("/api/v1/probe/reports", json=report, headers=headers).json()["duplicate"] is False
    assert admin.post("/api/v1/probe/reports", json=report, headers=headers).json()["duplicate"] is True
    assert connection.execute("SELECT count(*) FROM probe_reports").fetchone()[0] == 1
    rows = connection.execute("SELECT server_id, source_kind, result, metrics_json FROM observations").fetchall()
    assert len(rows) == 1 and rows[0][0] == "s1" and rows[0][1] == "pc" and rows[0][2] == "success"
    assert '"full_vpn_test":true' in rows[0][3]
    status = admin.get("/api/v1/status").json()
    assert status["sources"] == [{"source": "pc", "state": "active", "last_report_at": NOW.isoformat().replace("+00:00", "Z")}]
    pc = next(e for e in status["servers"][0]["sources"] if e["source"] == "pc")
    assert pc["state"] == "operational" and not pc["freshness"]["is_stale"]
    probes = admin.get("/api/v1/admin/probes").json()
    assert probes[0]["status"] == "active" and probes[0]["route_verified"] is True and probes[0]["network_type"] == "home"


def test_revoked_probe_loses_access_everywhere(tmp_path):
    new_database(tmp_path / "db.sqlite3")
    clock = Clock(NOW)
    admin = process(tmp_path / "db.sqlite3", clock)
    login(admin, 2, NOW)
    code = admin.post("/api/v1/admin/probe-enrollments", json={"kind": "abroad", "capabilities": ["report_abroad"]}).json()["code"]
    joined = admin.post("/api/v1/probe/enroll", json={"code": code, "agent_version": "0.1.0", "schema_version": 1}).json()
    headers = {"Authorization": f"Bearer {joined['token']}"}
    assert admin.get("/api/v1/probe/config", headers=headers).status_code == 200
    assert admin.post(f"/api/v1/admin/probes/{joined['probe']['id']}/revoke").status_code == 204
    other = process(tmp_path / "db.sqlite3", clock)
    assert other.get("/api/v1/probe/config", headers=headers).status_code == 401
    assert admin.post("/api/v1/admin/probes/nope/revoke").status_code == 404
    assert [p["status"] for p in admin.get("/api/v1/admin/probes").json()] == ["revoked"]


def test_note_is_shared_between_processes(tmp_path):
    new_database(tmp_path / "db.sqlite3")
    clock = Clock(NOW)
    admin = process(tmp_path / "db.sqlite3", clock)
    login(admin, 2, NOW)
    member = process(tmp_path / "db.sqlite3", clock)
    login(member, 1, NOW)
    assert member.get("/api/v1/status").json()["note"] is None
    first = admin.put("/api/v1/admin/note", json={"text": "Первая", "expires_at": None}).json()
    second = admin.put("/api/v1/admin/note", json={"text": "Вторая", "expires_at": (NOW + timedelta(hours=2)).isoformat()}).json()
    note = member.get("/api/v1/status").json()["note"]
    assert note["id"] == second["id"] and note["text"] == "Вторая" and first["id"] != second["id"]
    clock.at = NOW + timedelta(hours=3)
    login(member, 1, clock.at)  # the session itself expired with the clock
    assert member.get("/api/v1/status").json()["note"] is None  # the note expired
    clock.at = NOW
    login(admin, 2, NOW)
    assert admin.delete("/api/v1/admin/note").status_code == 204
    assert member.get("/api/v1/status").json()["note"] is None


def test_analytics_audit_and_retention_sweep(tmp_path):
    connection = new_database(tmp_path / "db.sqlite3")
    clock = Clock(NOW)
    admin = process(tmp_path / "db.sqlite3", clock)
    login(admin, 2, NOW)
    event = {"event_id": str(uuid4()), "name": "app_opened", "occurred_at": NOW.isoformat(), "schema_version": 1,
             "session_id": str(uuid4()), "surface": "mini_app", "properties": {"role": "admin", "language": "ru", "theme": "dark", "viewport_bucket": "phone"}}
    assert admin.post("/api/v1/analytics/events:batch", json={"events": [event]}).json()["accepted"] == 1
    assert admin.post("/api/v1/analytics/events:batch", json={"events": [event]}).json()["accepted"] == 0
    admin.put("/api/v1/admin/note", json={"text": "x"})
    admin.post("/api/v1/admin/probe-enrollments", json={"kind": "pc", "capabilities": ["report_pc"]})
    actions = [row[0] for row in connection.execute("SELECT action FROM audit_entries ORDER BY rowid").fetchall()]
    assert actions == ["note.put", "probe.enroll_code"]
    assert connection.execute("SELECT count(*) FROM product_events").fetchone()[0] == 1
    store = SqliteStore(connection, analytics_schema=ANALYTICS_SCHEMA, config=CONFIG, pepper=BOT_TOKEN, now=clock)
    counts = store.sweep(NOW + timedelta(days=31))
    assert counts["sessions"] == 1 and counts["enrollments"] == 1 and counts["analytics"] == 1
    assert connection.execute("SELECT count(*) FROM web_sessions").fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM audit_entries").fetchone()[0] == 2  # audit is kept for a year


def test_one_connection_serves_many_threads(tmp_path):
    """API workers share one connection: concurrent reads and writes must not corrupt each other."""
    import threading
    connection = new_database(tmp_path / "db.sqlite3")
    clock = Clock(NOW)
    store = SqliteStore(connection, analytics_schema=ANALYTICS_SCHEMA, config=CONFIG, pepper=BOT_TOKEN, now=clock)
    model = SqliteReadModel(connection, CONFIG, now=clock)
    errors: list[BaseException] = []

    def worker(index: int) -> None:
        try:
            for _ in range(25):
                token = store.create_session(__import__("vpnpulse.auth", fromlist=["Identity"]).Identity(index, "member"), NOW).token
                assert store.get_session(token, NOW) is not None
                model.status("member", "ru")
                model.metrics("s1", "24h")
                store.put_note(f"note {index}", None, None, "admin", NOW)
        except BaseException as error:  # noqa: BLE001 - collected for the assertion below
            errors.append(error)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors[:3]
    assert connection.execute("SELECT count(*) FROM web_sessions").fetchone()[0] == 12 * 25
    assert connection.execute("SELECT count(*) FROM admin_notes WHERE status = 'active'").fetchone()[0] == 1
