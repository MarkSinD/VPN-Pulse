from datetime import UTC, datetime, timedelta
from pathlib import Path

from vpnpulse.adapters import load_scenario
from vpnpulse.domain import State, evaluate_scope
from vpnpulse.storage import NotificationWorker, StateRepository, apply_migrations, connect
from vpnpulse.storage.repository import notification_for


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
    repository = StateRepository(connection)

    # the first evaluation after a data gap: a transition, but nobody is told
    healthy = evaluate_scope(load_scenario(ROOT / "fixtures" / "scenarios.json", "all-operational", NOW), now=NOW)
    first = repository.save_evaluation(scope_key="server:s1", server_id="s1", network_scope="all", evaluation=healthy, evaluated_at=NOW)
    assert first is not None
    assert repository.save_evaluation(scope_key="server:s1", server_id="s1", network_scope="all", evaluation=healthy, evaluated_at=NOW) is None
    assert connection.execute("SELECT count(*) FROM notification_queue").fetchone()[0] == 0

    # a confirmed failure: one transition, one message for the group — saving it again changes nothing
    later = NOW + timedelta(minutes=2)
    outage = evaluate_scope(load_scenario(ROOT / "fixtures" / "scenarios.json", "confirmed-pc-failure", later), now=later)
    second = repository.save_evaluation(scope_key="server:s1", server_id="s1", network_scope="all", evaluation=outage, evaluated_at=later)
    third = repository.save_evaluation(scope_key="server:s1", server_id="s1", network_scope="all", evaluation=outage, evaluated_at=later)
    assert second is not None and third is None
    assert connection.execute("SELECT state FROM state_snapshots").fetchone()[0] == "unavailable"
    assert connection.execute("SELECT count(*) FROM state_transitions").fetchone()[0] == 2
    assert connection.execute("SELECT count(*) FROM notification_queue").fetchone()[0] == 1

    delivered = []
    worker = NotificationWorker(connection, lambda template, params: delivered.append((template, params)))
    assert worker.deliver_one(later) is True
    assert worker.deliver_one(later) is False
    assert delivered == [("bot.unavailable", {"server_id": "s1", "scope_key": "server:s1", "state": "unavailable", "from_state": "operational", "destination": "group"})]


def test_notification_policy():
    S = State
    assert notification_for(S.UNKNOWN, S.OPERATIONAL) is None
    assert notification_for(S.OPERATIONAL, S.UNAVAILABLE) == ("group", "bot.unavailable")
    assert notification_for(S.DEGRADED, S.UNAVAILABLE) == ("group", "bot.unavailable")
    assert notification_for(S.UNAVAILABLE, S.OPERATIONAL, group_alerted=True) == ("group", "bot.recovered")
    assert notification_for(S.DEGRADED, S.OPERATIONAL, group_alerted=True) == ("group", "bot.recovered")
    assert notification_for(S.DEGRADED, S.OPERATIONAL) == ("admin", "bot.recovered")
    assert notification_for(S.OPERATIONAL, S.DEGRADED) == ("admin", "bot.degraded")
    assert notification_for(S.OPERATIONAL, S.UNKNOWN) == ("admin", "bot.unknown")
    assert notification_for(S.DEGRADED, S.UNAVAILABLE, group_alerted=True) == ("admin", "bot.unavailable")
