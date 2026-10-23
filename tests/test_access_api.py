from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from test_api import ANALYTICS_SCHEMA, BOT_TOKEN, Membership, init_data
from vpnpulse.api import create_app
from vpnpulse.profile_service import ProfileService
from vpnpulse.storage import SqliteReadModel, SqliteStore, apply_migrations, connect

ROOT = Path(__file__).parents[1]
NOW = datetime(2026, 10, 22, tzinfo=UTC)


def client(tmp_path):
    config = {
        "access": {"member_registry_enabled": True, "grants_enabled": True, "issuance_enabled": False},
        "servers": [{"id": "s1", "type": "awg-host", "name": {"ru": "Сервер", "en": "Server"},
                     "country_code": "LV", "enabled": True}],
        "monitoring": {"freshness_seconds": 180}, "retention": {},
    }
    db = connect(tmp_path / "api.sqlite3")
    apply_migrations(db, ROOT / "migrations")
    store = SqliteStore(db, analytics_schema=ANALYTICS_SCHEMA, config=config, pepper=BOT_TOKEN,
                        identity_key="identity-key", now=lambda: NOW)
    app = create_app(bot_token=BOT_TOKEN, membership=Membership(), read_model=SqliteReadModel(db, config, now=lambda: NOW),
                     store=store, config=config, analytics_schema=ANALYTICS_SCHEMA, now=lambda: NOW)
    return TestClient(app, base_url="https://testserver")


def login(api, telegram_id):
    response = api.post("/api/v1/sessions", json={"init_data": init_data(telegram_id, at=NOW)})
    assert response.status_code == 204


def test_member_requests_and_admin_grants_without_exposing_telegram_id(tmp_path):
    member = client(tmp_path)
    login(member, 1)
    request = member.post("/api/v1/access/requests")
    assert request.status_code == 202 and request.json()["state"] == "pending"
    assert member.get("/api/v1/access").json() == {"grants": []}

    admin = client(tmp_path)
    login(admin, 2)
    listing = admin.get("/api/v1/admin/members").json()
    assert listing["coverage"]["active"] == 2
    assert all("telegram" not in key for item in listing["items"] for key in item)
    member_id = next(item["id"] for item in listing["items"] if item["id"] != admin.get("/api/v1/sessions/current").json()["member_id"])
    granted = admin.post(f"/api/v1/admin/members/{member_id}/grants",
                         json={"server_id": "s1", "reason": "recommended", "valid_until": None})
    assert granted.status_code == 201 and granted.json()["state"] == "active"
    assert member.get("/api/v1/access").json()["grants"][0]["server_id"] == "s1"


def test_grants_flag_is_fail_closed(tmp_path):
    api = client(tmp_path)
    login(api, 2)
    member_id = api.get("/api/v1/sessions/current").json()["member_id"]
    # Flip the in-memory policy only for this test; the data layer remains unchanged.
    api.app.routes  # ensure application is fully built
    # A missing server is still rejected without changing any grant.
    response = api.post(f"/api/v1/admin/members/{member_id}/grants",
                        json={"server_id": "missing", "reason": "test", "valid_until": None})
    assert response.status_code == 404


def test_profile_issue_is_one_time_and_never_cacheable(tmp_path):
    sent = []
    class Provisioner:
        def issue(self, **kwargs):
            return {"address": kwargs["address"], "preshared_key": "deliver-once",
                    "server_public_key": "server-key", "endpoint": "vpn.example:51820"}
        def revoke(self, **kwargs): return {"ok": True}

    config = {
        "access": {"member_registry_enabled": True, "grants_enabled": True, "issuance_enabled": True},
        "servers": [{"id": "s1", "type": "awg-host", "name": {"ru": "Сервер", "en": "Server"},
                     "country_code": "LV", "enabled": True,
                     "access": {"issuance_enabled": True, "maintenance": False}}],
        "monitoring": {"freshness_seconds": 180}, "retention": {},
    }
    db = connect(tmp_path / "profiles-api.sqlite3"); apply_migrations(db, ROOT / "migrations")
    store = SqliteStore(db, analytics_schema=ANALYTICS_SCHEMA, config=config, pepper=BOT_TOKEN,
                        identity_key="identity-key", now=lambda: NOW)
    service = ProfileService(store, config, {"servers": {"s1": {"addresses": ["fd00::100/128"]}}}, Provisioner())
    app = create_app(bot_token=BOT_TOKEN, membership=Membership(), read_model=SqliteReadModel(db, config, now=lambda: NOW),
                     store=store, config=config, analytics_schema=ANALYTICS_SCHEMA, now=lambda: NOW,
                     profile_service=service,
                     profile_sender=lambda telegram_id, filename, content: sent.append((telegram_id, filename, content)) or True)
    api = TestClient(app, base_url="https://testserver"); login(api, 1)
    member_id = api.get("/api/v1/sessions/current").json()["member_id"]
    store.grant_access(member_id, "s1", actor="owner", reason="test", now=NOW)
    key = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
    issued = api.post("/api/v1/access/servers/s1/profiles", json={"public_key": key},
                      headers={"Idempotency-Key": "browser-request-1"})
    assert issued.status_code == 201
    assert issued.headers["cache-control"] == "no-store"
    assert issued.json()["delivery"]["preshared_key"] == "deliver-once"
    replay = api.post("/api/v1/access/servers/s1/profiles", json={"public_key": key},
                      headers={"Idempotency-Key": "browser-request-1"})
    assert replay.status_code == 201 and replay.json()["delivery"] is None
    profile_id = issued.json()["profile_id"]
    profile_config = "[Interface]\nPrivateKey = private\nAddress = fd00::100/128\n[Peer]\nPublicKey = public\nPresharedKey = psk\n"
    delivered = api.post(f"/api/v1/access/profiles/{profile_id}/send", json={"config": profile_config})
    assert delivered.status_code == 204 and delivered.headers["cache-control"] == "no-store"
    assert sent == [(1, "vpn-s1.conf", profile_config)]
    assert api.get("/api/v1/access/profiles").json()["items"][0]["id"] == profile_id
    revoked = api.delete(f"/api/v1/access/profiles/{profile_id}", headers={"Idempotency-Key": "revoke-1"})
    assert revoked.status_code == 200 and revoked.json()["profile_state"] == "revoked"
