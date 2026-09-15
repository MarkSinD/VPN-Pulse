"""The monitoring loop: collect → evaluate → snapshots → transitions → notification queue.

One process (`vpn-pulse run`) owns the loop; the API only reads what it leaves in SQLite.
Every run:

1. `collect`   — asks each collector for observations and stores them with a `collection_runs`
                 row (a failing collector marks the run `partial`/`error`, never stops the loop);
                 probe reports arrive separately through the API into the same `observations`
2. `evaluate`  — per enabled server, the fresh observations go through the domain evaluator;
                 `StateRepository.save_evaluation` upserts the snapshot and, on a change, writes the
                 transition, the queued notification and — here — the member-visible event
3. `notify`    — `NotificationWorker` delivers what is due (retries with back-off live in the queue)
4. maintenance — once an hour: `SqliteStore.sweep()` by retention and the hourly connection
                 aggregates in `metric_hourly`

The whole thing is deterministic given a clock and a scripted collector, which is how it is tested.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from vpnpulse.collectors import Collected, Collector
from vpnpulse.domain import Observation, ObservationResult, State, evaluate_scope
from vpnpulse.i18n import Translator
from vpnpulse.storage import NotificationWorker, SqliteStore, StateRepository, sync_servers

log = logging.getLogger("vpnpulse.pipeline")

PROBE_KIND_OF_SOURCE = {"pc": "pc", "mobile": "android", "abroad": "abroad"}
PROBE_CAPABILITIES = {"pc": ["control_internet", "handshake", "https"], "android": ["dns", "tcp"], "abroad": ["handshake"]}
EVENT_SEVERITY = {"unavailable": "critical", "degraded": "warning", "operational": "info", "unknown": "info"}
NAMESPACE = uuid.UUID("7d3a5f1c-2b8e-4c6d-9a0f-1e2d3c4b5a69")


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z") if value else None


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _contracts_dir() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "contracts"
        if (candidate / "analytics-events.schema.json").exists():
            return candidate
    raise FileNotFoundError("contracts/ not found; pass a store to Pipeline")


class Pipeline:
    def __init__(
        self,
        connection: sqlite3.Connection,
        config: dict,
        *,
        collectors: Iterable[Collector] = (),
        notifier: Callable[[str, dict], bool | None],
        now: Callable[[], datetime] | None = None,
        translator: Translator | None = None,
        store: SqliteStore | None = None,
        maintenance_interval: timedelta = timedelta(hours=1),
        backoff_seconds: int = 30,
    ) -> None:
        self.db = connection
        self.config = config
        self.collectors = list(collectors)
        self.notifier = notifier
        self.now = now or (lambda: datetime.now(UTC))
        self.i18n = translator or Translator()
        monitoring = config.get("monitoring") or {}
        self.freshness = timedelta(seconds=monitoring.get("freshness_seconds", 180))
        self.interval = timedelta(seconds=monitoring.get("collection_interval_seconds", 60))
        self.confirmations = int(monitoring.get("confirmations", 2))
        self.aggregates_days = int((config.get("retention") or {}).get("aggregates_days", 90))
        self.store = store or SqliteStore(connection, analytics_schema=_contracts_dir() / "analytics-events.schema.json", config=config, now=self.now)
        self.states = StateRepository(connection)
        self.worker = NotificationWorker(connection, notifier, backoff_seconds=backoff_seconds)
        self.maintenance_interval = maintenance_interval
        self.last_maintenance: datetime | None = None
        self.runs = 0
        self._stop = False

    # ---------- configuration → tables ----------
    def _servers(self) -> list[dict]:
        return [s for s in self.config.get("servers", []) if s.get("enabled", True)]

    def ensure_servers(self, now: datetime | None = None) -> None:
        """Mirror config servers/protocols into the tables observations reference (config stays the source of truth)."""
        sync_servers(self.db, self.config, now or self.now())

    # ---------- 1. collect ----------
    def collect(self, now: datetime) -> dict:
        run_id = str(uuid.uuid4())
        trace_id = uuid.uuid4().hex
        started = time.monotonic()
        known = {row[0] for row in self.db.execute("SELECT id FROM servers").fetchall()}
        written = 0
        failed: list[str] = []
        with self.db:
            self.db.execute("INSERT INTO collection_runs VALUES (?, ?, NULL, NULL, ?, NULL, NULL)", (run_id, _iso(now), trace_id))
        for collector in self.collectors:
            try:
                items = list(collector.collect(now))
            except Exception as error:  # noqa: BLE001 - one broken collector must not stop monitoring
                failed.append(getattr(collector, "name", type(collector).__name__))
                log.warning("collector failed", extra={"event": "collector.failed", "trace_id": trace_id, "details": {"collector": getattr(collector, "name", "?"), "error": type(error).__name__}})
                continue
            with self.db:
                for item in items:
                    if item.server_id not in known:
                        continue  # never invent a server the configuration does not know
                    self._write_observation(item, run_id, written, now)
                    written += 1
        result = "ok" if not failed else ("partial" if written else "error")
        with self.db:
            self.db.execute(
                "UPDATE collection_runs SET finished_at = ?, result = ?, duration_ms = ?, error_code = ? WHERE id = ?",
                (_iso(now), result, int((time.monotonic() - started) * 1000), "COLLECTOR_FAILED" if failed else None, run_id),
            )
        return {"run_id": run_id, "observations": written, "failed_collectors": failed, "result": result}

    def _write_observation(self, item: Collected, run_id: str, index: int, now: datetime) -> None:
        metrics = dict(item.metrics)
        if item.source != "collector":
            metrics["full_vpn_test"] = item.full_vpn_test
            metrics["control_internet_ok"] = item.control_internet_ok
        self.db.execute(
            "INSERT INTO observations VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
            (str(uuid.uuid5(NAMESPACE, f"{run_id}:{index}")), item.server_id, item.source, item.network_scope, _iso(item.observed_at), _iso(now),
             item.result, _iso(item.observed_at + self.freshness), "sufficient", json.dumps(metrics, separators=(",", ":")), item.error_code, run_id),
        )
        if item.probe_id:
            kind = PROBE_KIND_OF_SOURCE.get(item.source)
            if kind:
                self.db.execute(
                    """
                    INSERT INTO probes(id, public_id, kind, status, capabilities_json, token_hash, token_prefix, schema_major, agent_version, enrolled_at, last_seen_at, revoked_at)
                    VALUES (?, ?, ?, 'active', ?, X'00', 'script', 1, 'scripted', ?, ?, NULL)
                    ON CONFLICT(id) DO UPDATE SET last_seen_at = MAX(COALESCE(probes.last_seen_at, ''), excluded.last_seen_at)
                    """,
                    (item.probe_id, item.probe_id, kind, json.dumps(PROBE_CAPABILITIES.get(kind, [])), _iso(now), _iso(item.observed_at)),
                )

    # ---------- 2. evaluate ----------
    def _observations(self, server_id: str, now: datetime) -> list[Observation]:
        rows = self.db.execute(
            "SELECT source_kind, result, observed_at, fresh_until, metrics_json, error_code FROM observations WHERE server_id = ? AND fresh_until >= ? ORDER BY observed_at",
            (server_id, _iso(now)),
        ).fetchall()
        out = []
        for source, result, observed_at, fresh_until, metrics_json, error_code in rows:
            try:
                metrics = json.loads(metrics_json or "{}")
            except json.JSONDecodeError:
                metrics = {}
            try:
                parsed = ObservationResult(result)
            except ValueError:
                continue
            out.append(Observation(source, parsed, _dt(observed_at), _dt(fresh_until), bool(metrics.get("full_vpn_test", False)), metrics.get("control_internet_ok"), error_code))
        return out

    def _expected_sources(self, server_id: str, now: datetime) -> int:
        row = self.db.execute(
            "SELECT count(DISTINCT source_kind) FROM observations WHERE server_id = ? AND observed_at >= ?", (server_id, _iso(now - timedelta(hours=24)))
        ).fetchone()
        return max(1, int(row[0] or 0))

    def evaluate(self, now: datetime) -> list[dict]:
        transitions = []
        for s in self._servers():
            scope_key = f"server:{s['id']}"
            before = self.db.execute("SELECT state FROM state_snapshots WHERE scope_key = ?", (scope_key,)).fetchone()
            previous = State(before[0]) if before else State.UNKNOWN
            evaluation = evaluate_scope(self._observations(s["id"], now), now=now, expected_sources=self._expected_sources(s["id"], now), failure_confirmations=self.confirmations)
            transition_id = self.states.save_evaluation(scope_key=scope_key, server_id=s["id"], network_scope="all", evaluation=evaluation, evaluated_at=now)
            if transition_id is None:
                continue
            self._write_event(transition_id, s["id"], previous, evaluation.state, now)
            transitions.append({"server_id": s["id"], "from": previous.value, "to": evaluation.state.value, "reason": evaluation.reason_code})
        return transitions

    def _write_event(self, transition_id: str, server_id: str, previous: State, current: State, now: datetime) -> None:
        recovery = current is State.OPERATIONAL and previous in (State.DEGRADED, State.UNAVAILABLE)
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'member', ?)",
                (str(uuid.uuid5(NAMESPACE, "event:" + transition_id)), "recovery" if recovery else "state_change", EVENT_SEVERITY[current.value], server_id, transition_id,
                 "events.recovered" if recovery else "events.stateChanged", json.dumps({"state": current.value}), _iso(now), _iso(now)),
            )

    # ---------- 3. notify ----------
    def notify(self, now: datetime) -> dict[str, int]:
        return self.worker.deliver_pending(now)

    # ---------- 4. maintenance ----------
    def maintenance_due(self, now: datetime) -> bool:
        return self.last_maintenance is None or now - self.last_maintenance >= self.maintenance_interval

    def maintain(self, now: datetime) -> dict:
        swept = self.store.sweep(now)
        with self.db:
            swept["aggregates"] = self.db.execute("DELETE FROM metric_hourly WHERE bucket_at < ?", (_iso(now - timedelta(days=self.aggregates_days)),)).rowcount
        aggregated = self.aggregate_hourly(now)
        self.last_maintenance = now
        return {"swept": swept, "aggregated": aggregated}

    def aggregate_hourly(self, now: datetime, hours: int = 25) -> int:
        """Per protocol, min/max/avg connections for each complete hour of the last `hours` (idempotent)."""
        end = now.replace(minute=0, second=0, microsecond=0)
        start = end - timedelta(hours=hours)
        interval = self.interval.total_seconds()
        protocols = self.db.execute("SELECT id, server_id, kind FROM protocols WHERE enabled = 1").fetchall()
        rows = 0
        with self.db:
            for protocol_id, server_id, kind in protocols:
                buckets: dict[datetime, list[float]] = {}
                for observed_at, metrics_json in self.db.execute(
                    "SELECT observed_at, metrics_json FROM observations WHERE server_id = ? AND source_kind = 'collector' AND observed_at >= ? AND observed_at < ?",
                    (server_id, _iso(start), _iso(end)),
                ).fetchall():
                    try:
                        value = (json.loads(metrics_json or "{}").get("connections") or {}).get(kind)
                    except json.JSONDecodeError:
                        value = None
                    if value is None:
                        continue
                    at = _dt(observed_at).replace(minute=0, second=0, microsecond=0)
                    buckets.setdefault(at, []).append(float(value))
                self.db.execute("DELETE FROM metric_hourly WHERE server_id = ? AND protocol_id = ? AND metric = 'connections' AND bucket_at >= ? AND bucket_at < ?", (server_id, protocol_id, _iso(start), _iso(end)))
                for at, values in buckets.items():
                    unknown = max(0, int(3600 - len(values) * interval))
                    self.db.execute(
                        "INSERT INTO metric_hourly VALUES (?, ?, ?, 'connections', ?, ?, ?, ?, ?)",
                        (_iso(at), server_id, protocol_id, min(values), max(values), sum(values) / len(values), len(values), unknown),
                    )
                    rows += 1
        return rows

    # ---------- the loop ----------
    def run_once(self, now: datetime | None = None) -> dict:
        now = now or self.now()
        if self.runs == 0:
            self.ensure_servers(now)
        collected = self.collect(now)
        transitions = self.evaluate(now)
        delivered = self.notify(now)
        maintained = self.maintain(now) if self.maintenance_due(now) else None
        self.runs += 1
        summary = {"at": _iso(now), "collected": collected, "transitions": transitions, "notifications": delivered, "maintenance": maintained}
        log.info("pipeline run", extra={"event": "pipeline.run", "trace_id": collected["run_id"].replace("-", ""), "details": {
            "observations": collected["observations"], "result": collected["result"], "transitions": transitions, "notifications": delivered}})
        return summary

    def stop(self) -> None:
        self._stop = True

    def run_forever(self, interval: timedelta | None = None, *, sleep: Callable[[float], None] = time.sleep, on_run: Callable[[dict], None] | None = None) -> int:
        """Run until `stop()` (or Ctrl+C); the interval is measured from the start of each run."""
        interval = interval or self.interval
        runs = 0
        while not self._stop:
            started = self.now()
            try:
                summary = self.run_once(started)
                runs += 1
                if on_run:
                    on_run(summary)
            except KeyboardInterrupt:
                break
            except Exception as error:  # noqa: BLE001 - keep monitoring; the failure is logged with its type only
                log.error("pipeline run failed", extra={"event": "pipeline.failed", "details": {"error": type(error).__name__}})
            if self._stop:
                break
            remaining = max(0.0, interval.total_seconds() - (self.now() - started).total_seconds())
            try:
                while remaining > 0 and not self._stop:  # short naps so stop() and signals act within a second
                    step = min(1.0, remaining)
                    sleep(step)
                    remaining -= step
            except KeyboardInterrupt:
                break
        return runs
