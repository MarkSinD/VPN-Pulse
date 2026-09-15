from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from vpnpulse.adapters import load_scenario
from vpnpulse.api import create_app
from vpnpulse.domain import evaluate_scope
from vpnpulse.storage import NotificationWorker, SqliteReadModel, StateRepository, apply_migrations, connect
from test_api import ANALYTICS_SCHEMA, BOT_TOKEN, Membership, init_data


ROOT = Path(__file__).parents[1]
NOW = datetime(2026, 9, 13, 18, 0, tzinfo=UTC)


def test_observation_reaches_api_and_notification(tmp_path):
    connection = connect(tmp_path / "vertical.sqlite3")
    apply_migrations(connection, ROOT / "migrations")
    connection.execute(
        "INSERT INTO servers VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("s1", "server-1", "awg-host", 1, 1, NOW.isoformat(), NOW.isoformat()),
    )
    observations = load_scenario(ROOT / "fixtures" / "scenarios.json", "all-operational", NOW)
    evaluation = evaluate_scope(observations, now=NOW)
    StateRepository(connection).save_evaluation(
        scope_key="server:s1", server_id="s1", network_scope="all",
        evaluation=evaluation, evaluated_at=NOW,
    )

    config = {"app": {"default_language": "ru", "languages": ["ru", "en"], "timezone": "UTC"},
              "servers": [{"id": "s1", "type": "awg-host", "name": {"ru": "Сервер 1", "en": "Server 1"}, "country_code": "LV", "enabled": True, "recommended_priority": 10}],
              "monitoring": {"freshness_seconds": 180, "collection_interval_seconds": 60}}
    app = create_app(
        bot_token=BOT_TOKEN,
        membership=Membership(),
        read_model=SqliteReadModel(connection, config, now=lambda: NOW),
        analytics_schema=ANALYTICS_SCHEMA,
        now=lambda: NOW,
    )
    api = TestClient(app, base_url="https://testserver")
    assert api.post("/api/v1/sessions", json={"init_data": init_data(1)}).status_code == 204
    payload = api.get("/api/v1/status").json()
    assert payload["state"] == "operational"
    assert payload["recommended_server_id"] == "s1"
    assert payload["servers"][0]["uptime_24h"] is None

    # the first evaluation is not news for anybody; a confirmed failure two minutes later is
    sent = []
    worker = NotificationWorker(connection, lambda template, params: sent.append((template, params)))
    assert worker.deliver_one(NOW) is False
    later = NOW + timedelta(minutes=2)
    outage = evaluate_scope(load_scenario(ROOT / "fixtures" / "scenarios.json", "confirmed-pc-failure", later), now=later)
    StateRepository(connection).save_evaluation(scope_key="server:s1", server_id="s1", network_scope="all", evaluation=outage, evaluated_at=later)
    assert worker.deliver_one(later) is True and worker.deliver_one(later) is False
    assert sent == [("bot.unavailable", {"server_id": "s1", "scope_key": "server:s1", "state": "unavailable", "from_state": "operational", "destination": "group"})]
