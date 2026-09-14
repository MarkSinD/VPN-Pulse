from datetime import UTC, datetime
from pathlib import Path

from vpnpulse.adapters import load_scenario
from vpnpulse.domain import evaluate_scope
from vpnpulse.storage import NotificationWorker, StateRepository, apply_migrations, connect


ROOT = Path(__file__).parents[1]
NOW = datetime(2026, 9, 13, 18, 0, tzinfo=UTC)


def prepared_database(tmp_path):
    connection = connect(tmp_path / "pipeline.sqlite3")
    apply_migrations(connection, ROOT / "migrations")
    connection.execute(
        "INSERT INTO servers VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("s1", "server-1", "awg-host", 1, 1, NOW.isoformat(), NOW.isoformat()),
    )
    connection.commit()
    return connection


def test_fixture_to_snapshot_transition_and_exactly_one_notification(tmp_path):
    connection = prepared_database(tmp_path)
    observations = load_scenario(ROOT / "fixtures" / "scenarios.json", "all-operational", NOW)
    evaluation = evaluate_scope(observations, now=NOW)
    repository = StateRepository(connection)

    first = repository.save_evaluation(
        scope_key="server:s1", server_id="s1", network_scope="all",
        evaluation=evaluation, evaluated_at=NOW,
    )
    second = repository.save_evaluation(
        scope_key="server:s1", server_id="s1", network_scope="all",
        evaluation=evaluation, evaluated_at=NOW,
    )
    assert first is not None
    assert second is None
    assert connection.execute("SELECT state FROM state_snapshots").fetchone()[0] == "operational"
    assert connection.execute("SELECT count(*) FROM state_transitions").fetchone()[0] == 1
    assert connection.execute("SELECT count(*) FROM notification_queue").fetchone()[0] == 1

    delivered = []
    worker = NotificationWorker(connection, lambda template, params: delivered.append((template, params)))
    assert worker.deliver_one(NOW) is True
    assert worker.deliver_one(NOW) is False
    assert delivered == [("bot.stateChanged", {"server_id": "s1", "state": "operational"})]
