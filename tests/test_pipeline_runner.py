"""The monitoring loop end to end on a scripted world and a frozen clock.

A transition produces exactly one message, delivered to the right chat, once — through retries,
restarts and the way back to operational.
"""
from datetime import UTC, datetime, timedelta
from pathlib import Path

from vpnpulse.collectors import FixtureCollector
from vpnpulse.dev.scenarios import ScenarioCatalog
from vpnpulse.dev.seed import config_for
from vpnpulse.notify import ConsoleNotifier, FakeNotifier, MessageFormatter
from vpnpulse.pipeline import Pipeline
from vpnpulse.storage import SqliteReadModel, apply_migrations, connect

ROOT = Path(__file__).parents[1]
NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
CATALOG = ScenarioCatalog.load()
# two quiet minutes, an outage of the second server, then everything works again
PHASES = (("operational", 2), ("unavailable", 10), ("operational", 10))


class Clock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at

    def tick(self, seconds: int = 60) -> datetime:
        self.at += timedelta(seconds=seconds)
        return self.at


def make(tmp_path, *, notifier=None, phases=PHASES, clock=None):
    clock = clock or Clock(NOW)
    connection = connect(tmp_path / "run.sqlite3")
    apply_migrations(connection, ROOT / "migrations")
    config = config_for(CATALOG, CATALOG.build("operational", NOW))
    notifier = notifier or FakeNotifier(MessageFormatter(config))
    pipeline = Pipeline(connection, config, collectors=[FixtureCollector(CATALOG, phases, start=NOW)], notifier=notifier, now=clock)
    return pipeline, clock, notifier, connection, config


def run_minutes(pipeline, clock, minutes: int) -> list[dict]:
    summaries = []
    for _ in range(minutes):
        summaries.append(pipeline.run_once(clock()))
        clock.tick(60)
    return summaries


def group(notifier):
    return [(t, p["server_id"], p["state"]) for t, _, p in notifier.sent if p["destination"] == "group"]


def admin(notifier):
    return [(t, p["server_id"], p["state"]) for t, _, p in notifier.sent if p["destination"] == "admin"]


def test_first_evaluation_tells_nobody(tmp_path):
    pipeline, clock, notifier, connection, _ = make(tmp_path)
    summary = pipeline.run_once(clock())
    assert [t["to"] for t in summary["transitions"]] == ["operational"] * 3
    assert notifier.sent == []
    assert connection.execute("SELECT count(*) FROM notification_queue").fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM events").fetchone()[0] == 3
    assert connection.execute("SELECT result FROM collection_runs").fetchone()[0] == "ok"


def test_outage_is_reported_once_and_recovery_once(tmp_path):
    pipeline, clock, notifier, connection, _ = make(tmp_path)
    run_minutes(pipeline, clock, 22)

    # the group: one outage message, one recovery — nothing else, no repeats
    assert group(notifier) == [("bot.unavailable", "s2", "unavailable"), ("bot.recovered", "s2", "operational")]
    # the administrator: the unconfirmed phases on the way down and up (conflicting fresh evidence)
    assert admin(notifier) == [("bot.degraded", "s2", "degraded"), ("bot.degraded", "s2", "degraded")]
    assert connection.execute("SELECT count(*) FROM notification_queue WHERE state != 'sent'").fetchone()[0] == 0

    states = connection.execute(
        "SELECT from_state, to_state FROM state_transitions WHERE scope_key = 'server:s2' ORDER BY confirmed_at, rowid"
    ).fetchall()
    assert [tuple(r) for r in states] == [
        ("unknown", "operational"), ("operational", "degraded"), ("degraded", "unavailable"), ("unavailable", "degraded"), ("degraded", "operational"),
    ]
    # only the last open transition stays open
    assert connection.execute("SELECT count(*) FROM state_transitions WHERE scope_key = 'server:s2' AND closed_at IS NULL").fetchone()[0] == 1
    events = connection.execute("SELECT kind, severity, title_key, params_json FROM events WHERE server_id = 's2' ORDER BY occurred_at, rowid").fetchall()
    assert [e[0] for e in events] == ["state_change", "state_change", "state_change", "state_change", "recovery"]
    assert [e[1] for e in events] == ["info", "warning", "critical", "warning", "info"]
    assert events[-1][2] == "events.recovered" and '"state": "operational"' in events[-1][3]
    # servers that stayed operational never made noise
    assert connection.execute("SELECT count(*) FROM state_transitions WHERE scope_key != 'server:s2'").fetchone()[0] == 2

    # the message texts carry public names only
    texts = [text for _, text, _ in notifier.sent]
    assert any("снова работает" in t for t in texts) and all("s2" not in t for t in texts)


def test_messenger_failure_retries_with_backoff_without_duplicates(tmp_path):
    pipeline, clock, notifier, connection, _ = make(tmp_path, notifier=FakeNotifier(fail_times=2))
    run_minutes(pipeline, clock, 4)  # minutes 0-3: operational, operational, degraded (attempt 1 fails), retry after 30 s fails too
    assert notifier.sent == []
    row = connection.execute("SELECT state, attempts, last_error_code, next_attempt_at FROM notification_queue").fetchone()
    assert tuple(row)[:3] == ("pending", 2, "SEND_FAILED")
    assert row[3] == "2026-09-15T12:04:00+00:00"  # back-off grows with the attempts: 30 s, then 60 s
    run_minutes(pipeline, clock, 4)  # minute 4: the retry succeeds and the confirmed outage goes out right after it
    rows = connection.execute("SELECT template_key, destination_kind, state, attempts FROM notification_queue ORDER BY created_at").fetchall()
    assert [tuple(r) for r in rows] == [("bot.degraded", "admin", "sent", 3), ("bot.unavailable", "group", "sent", 1)]
    assert [t for t, _, _ in notifier.sent] == ["bot.degraded", "bot.unavailable"]


def test_restart_over_the_same_database_does_not_resend(tmp_path):
    pipeline, clock, notifier, connection, config = make(tmp_path)
    run_minutes(pipeline, clock, 6)
    assert group(notifier) == [("bot.unavailable", "s2", "unavailable")]
    # a new process: fresh pipeline, fresh collector state, same file and clock
    again = FakeNotifier(MessageFormatter(config))
    restarted = Pipeline(connection, config, collectors=[FixtureCollector(CATALOG, PHASES, start=NOW)], notifier=again, now=clock)
    run_minutes(restarted, clock, 3)
    assert again.sent == []
    assert connection.execute("SELECT count(*) FROM notification_queue").fetchone()[0] == 2
    assert connection.execute("SELECT count(*) FROM state_transitions WHERE scope_key = 'server:s2'").fetchone()[0] == 3


def test_read_model_sees_what_the_loop_wrote(tmp_path):
    pipeline, clock, notifier, connection, config = make(tmp_path)
    run_minutes(pipeline, clock, 6)
    read_model = SqliteReadModel(connection, config, now=clock)
    status = read_model.status("member")
    by_id = {c["id"]: c for c in status["servers"]}
    assert status["state"] == "unavailable"
    assert by_id["s2"]["state"] == "unavailable" and by_id["s1"]["state"] == "operational"
    assert status["recommended_server_id"] in ("s1", "s3")
    assert {s["source"] for s in status["sources"]} == {"pc", "mobile", "abroad"}
    assert all(s["state"] == "active" for s in status["sources"])
    pc = next(e for e in by_id["s2"]["sources"] if e["source"] == "pc")
    assert pc["state"] == "unavailable" and pc["freshness"]["is_stale"] is False
    detail = read_model.server("s2", "member")
    assert detail["components"] and detail["resources"]["cpu_percent"] is not None
    assert detail["uptime_24h"] is not None and detail["coverage_24h"] > 0
    events = read_model.events("problems", None, 10, "member")["items"]
    assert [e["kind"] for e in events][:2] == ["state_change", "state_change"]
    assert read_model.readiness()["ready"] is True

    # and through the API with its strict response models
    from fastapi.testclient import TestClient
    from test_api import ANALYTICS_SCHEMA, BOT_TOKEN, Membership, init_data
    from vpnpulse.api import create_app

    app = create_app(bot_token=BOT_TOKEN, membership=Membership(), read_model=read_model, analytics_schema=ANALYTICS_SCHEMA, config=config, now=clock)
    api = TestClient(app, base_url="https://testserver")
    assert api.post("/api/v1/sessions", json={"init_data": init_data(2, at=clock())}).status_code == 204
    for path in ("/api/v1/status", "/api/v1/servers/s2", "/api/v1/servers/s2/metrics?period=24h", "/api/v1/servers/s2/metrics?period=7d",
                 "/api/v1/events?filter=all&limit=20", "/api/v1/admin/servers/s2", "/api/v1/admin/overview", "/api/v1/admin/probes", "/api/v1/health/ready"):
        response = api.get(path)
        assert response.status_code == 200, (path, response.text)
    assert api.get("/api/v1/status").json()["servers"][1]["state"] == "unavailable"
    assert len(api.get("/api/v1/servers/s2/metrics?period=24h").json()["points"]) == 48


def test_maintenance_runs_hourly_and_aggregates(tmp_path):
    pipeline, clock, notifier, connection, _ = make(tmp_path, phases=(("operational", 60),))
    summaries = run_minutes(pipeline, clock, 125)
    maintained = [i for i, s in enumerate(summaries) if s["maintenance"] is not None]
    assert maintained == [0, 60, 120]
    rows = connection.execute("SELECT server_id, protocol_id, samples, unknown_seconds FROM metric_hourly ORDER BY bucket_at, server_id").fetchall()
    assert len(rows) == 6  # two complete hours × three servers
    assert all(r[2] == 60 and r[3] == 0 for r in rows)
    assert {r[1] for r in rows} == {"s1:amneziawg", "s2:amneziawg", "s3:amneziawg"}


def test_broken_collector_marks_the_run_and_the_loop_goes_on(tmp_path):
    class Broken:
        name = "broken"

        def collect(self, now):
            raise RuntimeError("ssh: host unreachable 203.0.113.9")

    pipeline, clock, notifier, connection, config = make(tmp_path)
    pipeline.collectors.append(Broken())
    summary = pipeline.run_once(clock())
    assert summary["collected"]["result"] == "partial" and summary["collected"]["failed_collectors"] == ["broken"]
    assert connection.execute("SELECT result, error_code FROM collection_runs").fetchone() == ("partial", "COLLECTOR_FAILED")
    pipeline.collectors[:] = [Broken()]
    clock.tick()
    assert pipeline.run_once(clock())["collected"]["result"] == "error"
    assert SqliteReadModel(connection, config, now=clock).readiness()["checks"]["collector"]["ok"] is False


def test_console_notifier_prints_public_text_only(tmp_path):
    lines = []
    pipeline, clock, notifier, connection, _ = make(tmp_path, notifier=ConsoleNotifier(MessageFormatter(config_for(CATALOG, CATALOG.build("operational", NOW))), out=lines.append))
    run_minutes(pipeline, clock, 6)
    assert lines and lines[-1].startswith("[group] 🔴 ") and "s2" not in lines[-1]


def test_run_forever_stops_when_asked_and_two_collectors_share_a_run(tmp_path):
    pipeline, clock, notifier, connection, _ = make(tmp_path)
    pipeline.collectors.append(FixtureCollector(CATALOG, PHASES, start=NOW, probes=False))
    naps = []

    def nap(seconds):
        naps.append(seconds)
        clock.tick(int(seconds))
        if len(naps) >= 3:
            pipeline.stop()

    assert pipeline.run_forever(timedelta(seconds=2), sleep=nap) == 2
    assert naps == [1.0, 1.0, 1.0]  # one-second naps, so a stop request is honoured within a second, not an interval
    run_id = connection.execute("SELECT id FROM collection_runs ORDER BY started_at LIMIT 1").fetchone()[0]
    assert connection.execute("SELECT count(*) FROM observations WHERE collection_run_id = ?", (run_id,)).fetchone()[0] > 14
