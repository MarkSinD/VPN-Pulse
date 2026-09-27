"""Short spells must not wake the administrator.

Measured on the live installation: a `degraded` spell lasts three minutes on median — one lost
handshake among ten good checks — and produced ~130 messages a day about servers that were working.
The administrator's notice now waits, and a spell that ends inside the wait is dropped together
with its recovery. Outage messages to the group are never held.
"""
from datetime import UTC, datetime, timedelta
from pathlib import Path

from vpnpulse.domain import Evaluation, State
from vpnpulse.storage import NotificationWorker, StateRepository, apply_migrations, connect

ROOT = Path(__file__).parents[1]
NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
QUIET = 600


def database(tmp_path):
    connection = connect(tmp_path / "quiet.sqlite3")
    apply_migrations(connection, ROOT / "migrations")
    connection.execute("INSERT INTO servers VALUES (?, ?, ?, ?, ?, ?, ?)",
                       ("s1", "server-1", "awg-host", 1, 1, NOW.isoformat(), NOW.isoformat()))
    connection.commit()
    return connection


def evaluation(state: State, at: datetime) -> Evaluation:
    return Evaluation(state=state, reason_code="evidence.conflict" if state is State.DEGRADED else "ok", observed_at=at, fresh_until=at + timedelta(minutes=3),
                      evidence_count=3, coverage=1.0)


def save(repository, state, at):
    return repository.save_evaluation(scope_key="server:s1", server_id="s1", network_scope="all",
                                      evaluation=evaluation(state, at), evaluated_at=at)


def queue(connection):
    return connection.execute(
        "SELECT template_key, destination_kind, state, next_attempt_at FROM notification_queue ORDER BY created_at, rowid").fetchall()


def delivered(connection, now):
    sent = []
    worker = NotificationWorker(connection, lambda template, params: sent.append((template, params["destination"])) or True)
    worker.deliver_pending(now)
    return sent


def test_a_spell_shorter_than_the_wait_tells_nobody(tmp_path):
    connection = database(tmp_path)
    repository = StateRepository(connection, quiet_seconds=QUIET)
    save(repository, State.OPERATIONAL, NOW)
    save(repository, State.DEGRADED, NOW + timedelta(minutes=1))          # one bad check among ten
    assert delivered(connection, NOW + timedelta(minutes=2)) == []        # still waiting, nothing sent
    save(repository, State.OPERATIONAL, NOW + timedelta(minutes=4))       # three minutes later it is fine again
    assert delivered(connection, NOW + timedelta(hours=1)) == []          # neither half of the pair goes out
    assert [row[2] for row in queue(connection)] == ["superseded"]        # the notice was dropped, the recovery never queued


def test_a_spell_that_outlives_the_wait_is_reported_and_so_is_its_end(tmp_path):
    connection = database(tmp_path)
    repository = StateRepository(connection, quiet_seconds=QUIET)
    save(repository, State.OPERATIONAL, NOW)
    save(repository, State.DEGRADED, NOW + timedelta(minutes=1))
    assert delivered(connection, NOW + timedelta(minutes=5)) == []                 # inside the wait: silence
    assert delivered(connection, NOW + timedelta(minutes=12)) == [("bot.degraded", "admin")]
    save(repository, State.OPERATIONAL, NOW + timedelta(minutes=20))
    assert delivered(connection, NOW + timedelta(minutes=21)) == [("bot.recovered", "admin")]


def test_no_fresh_data_follows_the_same_rule(tmp_path):
    connection = database(tmp_path)
    repository = StateRepository(connection, quiet_seconds=QUIET)
    save(repository, State.OPERATIONAL, NOW)
    save(repository, State.UNKNOWN, NOW + timedelta(minutes=1))
    save(repository, State.OPERATIONAL, NOW + timedelta(minutes=3))
    assert delivered(connection, NOW + timedelta(hours=1)) == []
    save(repository, State.UNKNOWN, NOW + timedelta(minutes=30))
    assert delivered(connection, NOW + timedelta(minutes=45)) == [("bot.unknown", "admin")]


def test_an_outage_still_reaches_the_group_at_once(tmp_path):
    connection = database(tmp_path)
    repository = StateRepository(connection, quiet_seconds=QUIET)
    save(repository, State.OPERATIONAL, NOW)
    save(repository, State.UNAVAILABLE, NOW + timedelta(minutes=1))
    assert delivered(connection, NOW + timedelta(minutes=1, seconds=1)) == [("bot.unavailable", "group")]
    save(repository, State.OPERATIONAL, NOW + timedelta(minutes=6))
    assert delivered(connection, NOW + timedelta(minutes=6, seconds=1)) == [("bot.recovered", "group")]


def test_a_scope_that_keeps_flapping_speaks_up(tmp_path):
    connection = database(tmp_path)
    repository = StateRepository(connection, quiet_seconds=QUIET)
    save(repository, State.OPERATIONAL, NOW)
    at = NOW
    for _ in range(6):  # six dropped notices inside one hour
        at += timedelta(minutes=2)
        save(repository, State.DEGRADED, at)
        at += timedelta(minutes=2)
        save(repository, State.OPERATIONAL, at)
    assert delivered(connection, at) == []
    at += timedelta(minutes=2)
    save(repository, State.DEGRADED, at)  # the seventh is not held back
    assert delivered(connection, at + timedelta(seconds=1)) == [("bot.degraded", "admin")]


def test_the_wait_is_configurable_and_zero_means_send_at_once(tmp_path):
    connection = database(tmp_path)
    repository = StateRepository(connection, quiet_seconds=0)
    save(repository, State.OPERATIONAL, NOW)
    save(repository, State.DEGRADED, NOW + timedelta(minutes=1))
    assert delivered(connection, NOW + timedelta(minutes=1)) == [("bot.degraded", "admin")]
