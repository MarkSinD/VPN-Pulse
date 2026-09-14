import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

from fastapi.testclient import TestClient
import jsonschema
import yaml

from vpnpulse.api import create_app
from vpnpulse.auth import AuthenticationError, validate_telegram_init_data


NOW = datetime(2026, 9, 13, 18, 0, tzinfo=UTC)
BOT_TOKEN = "test-token-not-a-real-secret"
def _contracts_dir():
    for parent in Path(__file__).resolve().parents:
        if (parent / "contracts" / "openapi.yaml").exists():
            return parent / "contracts"
    raise FileNotFoundError("contracts/ not found above tests/")

ANALYTICS_SCHEMA = _contracts_dir() / "analytics-events.schema.json"
OPENAPI = yaml.safe_load((_contracts_dir() / "openapi.yaml").read_text(encoding="utf-8"))


class Membership:
    def role_for(self, user_id: int):
        return {1: "member", 2: "admin"}.get(user_id)


def init_data(user_id: int, at: datetime = NOW, token: str = BOT_TOKEN) -> str:
    values = {
        "auth_date": str(int(at.timestamp())),
        "query_id": "test-query",
        "user": json.dumps({"id": user_id}, separators=(",", ":")),
    }
    check = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def status_fixture(role: str):
    payload = {
        "state": "operational",
        "freshness": {"observed_at": NOW.isoformat(), "fresh_until": (NOW + timedelta(minutes=3)).isoformat(), "is_stale": False},
        "coverage": 1,
        "recommended_server_id": "server-1",
        "note": None,
        "servers": [{"id": "server-1", "name": "Сервер 1", "country_code": "LV", "state": "operational", "recommended": True}]
    }
    payload["servers"][0].update({
        "freshness": payload["freshness"],
        "uptime_24h": 1.0,
        "coverage_24h": 1.0,
        "sources": []
    })
    assert "diagnostics" not in payload
    return payload


def client():
    app = create_app(
        bot_token=BOT_TOKEN,
        membership=Membership(),
        status_provider=status_fixture,
        analytics_schema=ANALYTICS_SCHEMA,
        now=lambda: NOW,
    )
    return TestClient(app, base_url="https://testserver")


def login(client: TestClient, user_id: int):
    response = client.post("/api/v1/sessions", json={"init_data": init_data(user_id)})
    assert response.status_code == 204
    assert response.cookies.get("vpnpulse_session")


def assert_schema(name: str, payload):
    def dereference(value):
        if isinstance(value, dict) and "$ref" in value:
            current = OPENAPI
            for part in value["$ref"].removeprefix("#/").split("/"):
                current = current[part]
            return dereference(current)
        if isinstance(value, dict):
            return {key: dereference(child) for key, child in value.items()}
        if isinstance(value, list):
            return [dereference(child) for child in value]
        return value

    jsonschema.Draft202012Validator(dereference(OPENAPI["components"]["schemas"][name])).validate(payload)


def test_member_session_and_status_projection():
    api = client()
    login(api, 1)
    response = api.get("/api/v1/status")
    assert response.status_code == 200
    assert response.json()["state"] == "operational"
    assert "diagnostics" not in response.json()
    assert_schema("StatusResponse", response.json())


def test_member_cannot_read_admin_projection():
    api = client()
    login(api, 1)
    response = api.get("/api/v1/admin/servers/server-1")
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "ROLE_REQUIRED"
    assert response.json()["trace_id"]


def test_admin_can_read_admin_projection():
    api = client()
    login(api, 2)
    response = api.get("/api/v1/admin/servers/server-1")
    assert response.status_code == 200
    assert "diagnostics" in response.json()
    assert_schema("AdminServerDetail", response.json())


def test_non_member_is_rejected():
    api = client()
    response = api.post("/api/v1/sessions", json={"init_data": init_data(3)})
    assert response.status_code == 403


def test_expired_and_tampered_init_data_are_rejected():
    api = client()
    expired = init_data(1, NOW - timedelta(minutes=6))
    assert api.post("/api/v1/sessions", json={"init_data": expired}).status_code == 401
    tampered = init_data(1).replace("test-query", "changed-query")
    assert api.post("/api/v1/sessions", json={"init_data": tampered}).status_code == 401
    malformed = api.post("/api/v1/sessions", json={"init_data": "not-a-query-field"})
    assert malformed.status_code == 401
    assert malformed.json()["code"] == "AUTH_MALFORMED"


def test_analytics_allowlist_and_deduplication():
    api = client()
    login(api, 1)
    event = {
        "event_id": str(uuid4()),
        "name": "server_row_pressed",
        "occurred_at": NOW.isoformat(),
        "schema_version": 1,
        "session_id": str(uuid4()),
        "surface": "mini_app",
        "properties": {"server_public_id": "server-1", "state": "operational", "recommended": True, "input": "touch"}
    }
    first = api.post("/api/v1/analytics/events:batch", json={"events": [event]})
    second = api.post("/api/v1/analytics/events:batch", json={"events": [event]})
    assert first.json() == {"accepted": 1}
    assert second.json() == {"accepted": 0}


def test_analytics_rejects_identity_field():
    api = client()
    login(api, 1)
    event = {
        "event_id": str(uuid4()),
        "name": "app_opened",
        "occurred_at": NOW.isoformat(),
        "schema_version": 1,
        "session_id": str(uuid4()),
        "surface": "mini_app",
        "properties": {"telegram_user_id": 1}
    }
    assert api.post("/api/v1/analytics/events:batch", json={"events": [event]}).status_code == 400


def test_runtime_route_surface_matches_openapi_contract():
    api = client()
    app_methods = {
        (route.path.removeprefix("/api/v1"), method.lower())
        for route in api.app.routes
        if route.path.startswith("/api/v1")
        for method in route.methods
        if method not in {"HEAD", "OPTIONS"}
    }
    contract_methods = {
        (path, method)
        for path, operations in OPENAPI["paths"].items()
        for method in operations
        if method in {"get", "post", "put", "delete", "patch"}
    }
    normalized_app = {(path.replace("{server_id}", "{serverId}").replace("{probe_id}", "{probeId}"), method) for path, method in app_methods}
    assert normalized_app == contract_methods


def test_admin_can_enroll_report_and_revoke_probe():
    api = client()
    login(api, 2)
    enrollment = api.post(
        "/api/v1/admin/probe-enrollments",
        json={"kind": "android", "capabilities": ["report_mobile"]},
    )
    assert enrollment.status_code == 201
    joined = api.post(
        "/api/v1/probe/enroll",
        json={"code": enrollment.json()["code"], "agent_version": "0.1.0", "schema_version": 1},
    )
    assert joined.status_code == 201
    assert_schema("ProbeSummary", joined.json()["probe"])
    assert_schema("ProbeConfig", joined.json()["config"])
    token = joined.json()["token"]
    probe_id = joined.json()["probe"]["id"]
    report = {
        "report_id": str(uuid4()),
        "schema_version": 1,
        "agent_version": "0.1.0",
        "observed_at": NOW.isoformat(),
        "network": {"type": "cellular", "ip_family": "ipv4", "route_verified": True},
        "results": [{"target_id": "server-1", "check": "dns", "result": "success", "duration_ms": 20}],
    }
    headers = {"Authorization": f"Bearer {token}"}
    assert api.post("/api/v1/probe/reports", json=report, headers=headers).json()["duplicate"] is False
    assert api.post("/api/v1/probe/reports", json=report, headers=headers).json()["duplicate"] is True
    assert api.post(f"/api/v1/admin/probes/{probe_id}/revoke").status_code == 204
    assert api.get("/api/v1/probe/config", headers=headers).status_code == 401


def test_admin_note_round_trip():
    api = client()
    login(api, 2)
    response = api.put("/api/v1/admin/note", json={"text": "Проверяем соединение", "server_id": None, "expires_at": None})
    assert response.status_code == 200
    assert response.json()["text"] == "Проверяем соединение"
    assert_schema("AdminNote", response.json())
    assert api.delete("/api/v1/admin/note").status_code == 204


def test_member_read_responses_match_contract_schemas():
    api = client()
    login(api, 1)
    assert_schema("ServerDetail", api.get("/api/v1/servers/server-1").json())
    metrics = api.get("/api/v1/servers/server-1/metrics?period=24h").json()
    assert metrics == {"server_id": "server-1", "period": "24h", "coverage": 0, "points": []}
    assert_schema("EventPage", api.get("/api/v1/events").json())
    assert_schema("Readiness", api.get("/api/v1/health/ready").json())
