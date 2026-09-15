"""SqliteReadModel — the API read side over the real database (contracts/openapi.yaml shapes).

Where each answer comes from (see docs/architecture.md and the data model):

- servers, names, countries, priorities: the public configuration (`config.yaml`), never the DB
- state and freshness: `state_snapshots` (`server:<id>`), stale snapshots read as `unknown`
- evidence per source: the latest `observations` row per `source_kind` for the server
- uptime / coverage over 24 h and 7 d, metric points: `state_transitions` (state timeline) +
  `observations` (which buckets had data, connection counts from collector payloads)
- software, resources, profiles, service checks, per-server attention and diagnostics: the
  latest `collector` observation payload (contracts/collector-observation.schema.json)
- check sources (pc / mobile / abroad): `probes` — present after the first accepted report,
  silent when the last report is older than `silent_after_seconds`
- events: `events` filtered by `visible_to`; the note: the active row of `admin_notes`
- doctor and installation-wide attention: derived from the tables above, texts from i18n

Everything is computed at request time from indexed queries; there is no cache and no
in-memory state, so several API workers can share one database file.
"""
from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from vpnpulse.domain import Evaluation, ServerCandidate, State, recommend_server
from vpnpulse.i18n import Translator

KINDS = ("pc", "mobile", "abroad")
PROBE_KIND = {"pc": "pc", "mobile": "android", "abroad": "abroad"}
SOURCE_OF_PROBE = {"pc": "pc", "android": "mobile", "abroad": "abroad"}
RESULT_STATE = {"success": "operational", "failure": "unavailable", "not_run": "unknown", "degraded": "degraded"}
PROTOCOL_OF_TYPE = {"awg-host": "amneziawg", "awg-docker": "amneziawg", "hiddify": "xray_reality"}
PROBE_CAPABILITIES = {"pc": ["control_internet", "handshake", "https"], "android": ["dns", "tcp"], "abroad": ["handshake"], "watchdog": ["heartbeat"]}
PROBE_NETWORK = {"pc": "home", "android": "cellular", "abroad": "abroad", "watchdog": "unknown"}
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z") if value else None


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _minutes(since: datetime | None, now: datetime) -> int | None:
    return None if since is None else max(0, int((now - since).total_seconds() // 60))


class SqliteReadModel:
    def __init__(
        self,
        connection: sqlite3.Connection,
        config: dict,
        *,
        now: Callable[[], datetime] | None = None,
        translator: Translator | None = None,
        freshness_seconds: int = 180,
        silent_after_seconds: int = 900,
        collection_interval_seconds: int = 60,
        mode: str = "live",
    ) -> None:
        self.db = connection
        self.config = config
        self.now = now or (lambda: datetime.now(UTC))
        self.i18n = translator or Translator()
        self.freshness = timedelta(seconds=freshness_seconds)
        self.silent_after = timedelta(seconds=silent_after_seconds)
        self.collection_interval = timedelta(seconds=collection_interval_seconds)
        self.mode = mode
        monitoring = config.get("monitoring") or {}
        if monitoring.get("freshness_seconds"):
            self.freshness = timedelta(seconds=monitoring["freshness_seconds"])
        if monitoring.get("collection_interval_seconds"):
            self.collection_interval = timedelta(seconds=monitoring["collection_interval_seconds"])

    # ---------- configuration ----------
    def _servers_config(self) -> list[dict]:
        return [s for s in self.config.get("servers", []) if s.get("enabled", True)]

    def _server_config(self, server_id: str) -> dict | None:
        return next((s for s in self._servers_config() if s["id"] == server_id), None)

    def _contact_url(self) -> str | None:
        return (self.config.get("app") or {}).get("admin_contact_url")

    # ---------- queries ----------
    def _snapshot(self, server_id: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT state, reason_code, observed_at, fresh_until, evidence_json FROM state_snapshots WHERE scope_key = ?",
            (f"server:{server_id}",),
        ).fetchone()

    def _latest_by_source(self, server_id: str) -> dict[str, sqlite3.Row]:
        rows = self.db.execute(
            """
            SELECT o.source_kind, o.result, o.observed_at, o.fresh_until, o.error_code, o.metrics_json
            FROM observations o
            JOIN (SELECT source_kind, MAX(observed_at) AS latest FROM observations WHERE server_id = ? GROUP BY source_kind) m
              ON m.source_kind = o.source_kind AND m.latest = o.observed_at
            WHERE o.server_id = ?
            """,
            (server_id, server_id),
        ).fetchall()
        return {row[0]: row for row in rows}

    def _collector_payload(self, server_id: str) -> dict:
        row = self._latest_by_source(server_id).get("collector")
        if row is None:
            return {}
        try:
            return json.loads(row[5] or "{}")
        except json.JSONDecodeError:
            return {}

    def _protocols(self, server_id: str, cfg: dict) -> list[tuple[str, str]]:
        rows = self.db.execute("SELECT id, kind FROM protocols WHERE server_id = ? AND enabled = 1 ORDER BY id", (server_id,)).fetchall()
        if rows:
            return [(r[0], r[1]) for r in rows]
        kind = PROTOCOL_OF_TYPE.get(cfg.get("type"), "amneziawg")
        return [(f"{server_id}:{kind}", kind)]

    def _first_observation_at(self) -> datetime | None:
        row = self.db.execute("SELECT MIN(observed_at) FROM observations").fetchone()
        return _dt(row[0]) if row and row[0] else None

    # ---------- freshness / evidence ----------
    def _freshness(self, observed_at: datetime | None, fresh_until: datetime | None, now: datetime) -> dict:
        return {"observed_at": _iso(observed_at), "fresh_until": _iso(fresh_until), "is_stale": fresh_until is None or fresh_until < now}

    def _evidence(self, server_id: str, now: datetime) -> list[dict]:
        out = []
        for source, row in self._latest_by_source(server_id).items():
            if source not in ("pc", "mobile", "abroad", "human_activity", "collector"):
                continue
            meta = {}
            try:
                meta = json.loads(row[5] or "{}")
            except json.JSONDecodeError:
                pass
            out.append({
                "source": source,
                "state": RESULT_STATE.get(row[1], "unknown"),
                "freshness": self._freshness(_dt(row[2]), _dt(row[3]), now),
                "reason_code": row[4],
                "via_server_id": meta.get("via_server_id") if source == "abroad" else None,
            })
        order = {"pc": 0, "mobile": 1, "abroad": 2, "human_activity": 3, "collector": 4}
        out.sort(key=lambda e: order[e["source"]])
        return out

    def _presence(self, now: datetime) -> dict[str, dict]:
        """Existing check sources: a probe that reported at least once and is not revoked."""
        out: dict[str, dict] = {}
        for kind, last_seen in self.db.execute(
            "SELECT kind, MAX(last_seen_at) FROM probes WHERE status != 'revoked' AND last_seen_at IS NOT NULL GROUP BY kind"
        ).fetchall():
            source = SOURCE_OF_PROBE.get(kind)
            if not source:
                continue
            seen = _dt(last_seen)
            out[source] = {"source": source, "state": "active" if seen and now - seen <= self.silent_after else "silent", "last_report_at": _iso(seen)}
        return out

    # ---------- timeline ----------
    def _timeline(self, server_id: str, start: datetime, end: datetime) -> list[tuple[datetime, datetime, str]]:
        """State intervals covering [start, end) from transitions; unknown before the first observation."""
        rows = self.db.execute(
            "SELECT confirmed_at, from_state, to_state FROM state_transitions WHERE scope_key = ? ORDER BY confirmed_at",
            (f"server:{server_id}",),
        ).fetchall()
        first = self.db.execute("SELECT MIN(observed_at) FROM observations WHERE server_id = ?", (server_id,)).fetchone()[0]
        known_from = _dt(first) or end
        snapshot = self._snapshot(server_id)
        current = snapshot[0] if snapshot else "unknown"
        if snapshot and snapshot[3] and _dt(snapshot[3]) < end:
            current = "unknown"
        points: list[tuple[datetime, str]] = []
        state = rows[0][1] if rows else current
        cursor = start
        for at, _from, to in rows:
            t = _dt(at)
            if t <= start:
                state = to
                continue
            if t >= end:
                break
            points.append((cursor, state))
            cursor, state = t, to
        points.append((cursor, state))
        intervals = []
        for i, (at, st) in enumerate(points):
            until = points[i + 1][0] if i + 1 < len(points) else end
            if until <= at:
                continue
            if at < known_from:
                if until <= known_from:
                    intervals.append((at, until, "unknown"))
                    continue
                intervals.append((at, known_from, "unknown"))
                at = known_from
            intervals.append((at, until, st))
        return intervals

    def _availability(self, server_id: str, window: timedelta, now: datetime) -> tuple[float | None, float | None]:
        start = now - window
        known = 0.0
        operational = 0.0
        # availability over known time: operational counts fully, degraded half, unavailable not at all
        for at, until, state in self._timeline(server_id, start, now):
            seconds = (until - at).total_seconds()
            if state == "unknown":
                continue
            known += seconds
            operational += seconds if state == "operational" else seconds / 2 if state == "degraded" else 0.0
        total = window.total_seconds()
        coverage = round(known / total, 4) if total else None
        if known <= 0:
            return None, coverage
        return round(operational / known, 4), coverage

    def _points(self, server_id: str, period: str, now: datetime) -> list[dict]:
        if period == "24h":
            step, count = timedelta(minutes=30), 48
        else:
            step, count = timedelta(hours=1), 168
        start = now - step * count
        buckets: list[dict] = [{"connections": [], "seen": False} for _ in range(count)]
        for observed_at, source, metrics_json in self.db.execute(
            "SELECT observed_at, source_kind, metrics_json FROM observations WHERE server_id = ? AND observed_at >= ? ORDER BY observed_at",
            (server_id, _iso(start)),
        ).fetchall():
            index = int((_dt(observed_at) - start) / step)
            if not 0 <= index < count:
                continue
            buckets[index]["seen"] = True
            if source == "collector":
                try:
                    conns = (json.loads(metrics_json or "{}").get("connections") or {})
                except json.JSONDecodeError:
                    conns = {}
                known = [v for v in conns.values() if v is not None]
                if known:
                    buckets[index]["connections"].append(sum(known))
        timeline = self._timeline(server_id, start, now)
        def state_at(t: datetime) -> str:
            for at, until, state in timeline:
                if at <= t < until:
                    return state
            return "unknown"
        points = []
        for i, bucket in enumerate(buckets):
            at = start + step * i
            end = at + step
            avg = None
            if bucket["connections"]:
                avg = int(math.floor(sum(bucket["connections"]) / len(bucket["connections"]) + 0.5))
            state = state_at(min(end - timedelta(seconds=1), now - timedelta(seconds=1))) if bucket["seen"] else "unknown"
            points.append({"at": _iso(end), "state": state, "coverage": 1.0 if bucket["seen"] else 0.0, "connections": avg})
        return points

    # ---------- cards ----------
    def _card(self, cfg: dict, now: datetime, recommended_id: str | None) -> dict:
        sid = cfg["id"]
        snapshot = self._snapshot(sid)
        observed = _dt(snapshot[2]) if snapshot else None
        fresh_until = _dt(snapshot[3]) if snapshot else None
        stale = fresh_until is None or fresh_until < now
        state = "unknown" if stale else (snapshot[0] if snapshot else "unknown")
        uptime, coverage = self._availability(sid, timedelta(hours=24), now)
        return {
            "id": sid,
            "name": self._text(cfg.get("name"), "ru"),
            "country_code": cfg["country_code"],
            "state": state,
            "freshness": self._freshness(observed, fresh_until, now),
            "recommended": recommended_id == sid,
            "uptime_24h": uptime,
            "coverage_24h": coverage,
            "sources": self._evidence(sid, now),
        }

    @staticmethod
    def _text(value, lang: str) -> str:
        if isinstance(value, dict):
            return value.get(lang) or value.get("ru") or value.get("en") or ""
        return "" if value is None else str(value)

    def _recommendation(self, cards: list[dict], now: datetime) -> str | None:
        candidates = []
        for card in cards:
            cfg = self._server_config(card["id"]) or {}
            payload = self._collector_payload(card["id"])
            conns = payload.get("connections") or {}
            known = [v for v in conns.values() if v is not None]
            load = float(sum(known)) if known else None
            protocols = self._protocols(card["id"], cfg)
            complete = all(conns.get(kind) is not None for _, kind in protocols) if conns else False
            snapshot = self._snapshot(card["id"])
            evaluation = Evaluation(State(card["state"]), snapshot[1] if snapshot else "NO_FRESH_EVIDENCE", None, None, 1 if snapshot else 0, 1.0 if not card["freshness"]["is_stale"] else 0.0)
            candidates.append(ServerCandidate(card["id"], evaluation, load, complete or load is None, priority=-int(cfg.get("recommended_priority", 100))))
        return recommend_server(candidates)

    # ---------- ReadModel ----------
    def status(self, role: str, lang: str = "ru") -> dict:
        now = self.now()
        cards = [self._card(cfg, now, None) for cfg in self._servers_config()]
        recommended = self._recommendation(cards, now) if cards else None
        for card in cards:
            card["recommended"] = card["id"] == recommended
            cfg = self._server_config(card["id"]) or {}
            card["name"] = self._text(cfg.get("name"), lang)
        order = {"unavailable": 3, "degraded": 2, "unknown": 1, "operational": 0}
        overall = max((c["state"] for c in cards), key=order.get, default="unknown")
        observed = [_dt(c["freshness"]["observed_at"]) for c in cards if c["freshness"]["observed_at"]]
        fresh_until = [_dt(c["freshness"]["fresh_until"]) for c in cards if c["freshness"]["fresh_until"]]
        presence = self._presence(now)
        active = [k for k in KINDS if presence.get(k, {}).get("state") == "active"]
        since = self._first_observation_at()
        return {
            "state": overall,
            "freshness": {
                "observed_at": _iso(max(observed)) if observed else None,
                "fresh_until": _iso(min(fresh_until)) if fresh_until else None,
                "is_stale": not cards or all(c["freshness"]["is_stale"] for c in cards),
            },
            "coverage": round(len(active) / len(KINDS), 4),
            "mode": self.mode,
            "observing_since": _iso(since),
            "recommended_server_id": recommended,
            "note": self._note(now, lang),
            "servers": cards,
            "sources": [presence[k] for k in KINDS if k in presence],
        }

    def _note(self, now: datetime, lang: str = "ru") -> dict | None:
        row = self.db.execute(
            """
            SELECT id, server_id, text, expires_at, created_at FROM admin_notes
            WHERE status = 'active' AND starts_at <= ? AND (expires_at IS NULL OR expires_at > ?)
            ORDER BY created_at DESC LIMIT 1
            """,
            (_iso(now), _iso(now)),
        ).fetchone()
        if row is None:
            return None
        return {"id": row[0], "server_id": row[1], "text": row[2][:500], "expires_at": _iso(_dt(row[3])), "created_at": _iso(_dt(row[4]))}

    def _detail(self, cfg: dict, role: str, lang: str, now: datetime) -> dict:
        status = self.status(role, lang)
        card = next(c for c in status["servers"] if c["id"] == cfg["id"])
        payload = self._collector_payload(cfg["id"])
        conns = payload.get("connections") or {}
        protocols = []
        for _pid, kind in self._protocols(cfg["id"], cfg):
            known = kind in conns and conns[kind] is not None
            protocols.append({"kind": kind, "state": card["state"] if known or card["state"] != "operational" else "unknown", "coverage": 1.0 if known else 0.0, "connections": conns.get(kind) if known else None})
        uptime7, coverage7 = self._availability(cfg["id"], timedelta(days=7), now)
        resources = payload.get("resources")
        profiles = payload.get("profiles")
        return {
            **card,
            "protocols": protocols,
            "checks": card["sources"],
            "uptime_7d": uptime7,
            "coverage_7d": coverage7,
            "components": payload.get("components") or [],
            "resources": None if resources is None else {"traffic_mbps": resources.get("traffic_mbps"), "cpu_percent": resources.get("cpu_percent"), "memory_percent": resources.get("memory_percent"), "swap_percent": resources.get("swap_percent"), "peak_connections_24h": resources.get("peak_connections_24h")},
            "profiles": None if profiles is None else {"issued": profiles.get("issued"), "ever_connected": profiles.get("ever_connected"), "active_24h": profiles.get("active_24h"), "last_connection_at": profiles.get("last_connection_at")},
            "service_checks": payload.get("service_checks") or [],
        }

    def server(self, server_id: str, role: str, lang: str = "ru") -> dict | None:
        cfg = self._server_config(server_id)
        return None if cfg is None else self._detail(cfg, role, lang, self.now())

    def metrics(self, server_id: str, period: str) -> dict | None:
        if self._server_config(server_id) is None:
            return None
        points = self._points(server_id, period, self.now())
        return {"server_id": server_id, "period": period, "coverage": round(sum(p["coverage"] for p in points) / len(points), 4), "points": points}

    def events(self, filter: str, cursor: str | None, limit: int, role: str = "member", lang: str = "ru") -> dict:
        visible = ("member",) if role != "admin" else ("member", "admin")
        where = ["visible_to IN (%s)" % ",".join("?" * len(visible))]
        params: list = list(visible)
        if filter == "problems":
            where.append("severity IN ('warning', 'critical')")
        elif filter == "notes":
            where.append("kind = 'note'")
        offset = int(cursor) if cursor and cursor.isdigit() else 0
        rows = self.db.execute(
            f"SELECT id, kind, severity, server_id, title_key, params_json, occurred_at FROM events WHERE {' AND '.join(where)} ORDER BY occurred_at DESC, id LIMIT ? OFFSET ?",
            (*params, limit + 1, offset),
        ).fetchall()
        items = [{
            "id": r[0], "kind": r[1], "severity": r[2], "server_id": r[3], "title_key": r[4],
            "params": self._localize_params(json.loads(r[5] or "{}"), lang), "occurred_at": _iso(_dt(r[6])),
        } for r in rows[:limit]]
        return {"items": items, "next_cursor": str(offset + limit) if len(rows) > limit else None}

    @staticmethod
    def _localize_params(params: dict, lang: str) -> dict:
        out = {}
        for key, value in params.items():
            if isinstance(value, dict) and ("ru" in value or "en" in value):
                out[key] = value.get(lang) or value.get("ru") or value.get("en")
            else:
                out[key] = value
        return out

    def help(self, lang: str = "ru") -> dict:
        url = self._contact_url()
        return {"step_keys": ["help.step1", "help.step2", "help.step3", "help.step4"], "contact_available": url is not None, "contact_url": url}

    def admin_server(self, server_id: str, lang: str = "ru") -> dict | None:
        cfg = self._server_config(server_id)
        if cfg is None:
            return None
        now = self.now()
        detail = self._detail(cfg, "admin", lang, now)
        payload = self._collector_payload(server_id)
        items = [{"severity": a["severity"], "code": a["code"], "message": self._text(a.get("message"), lang)[:240], "server_id": server_id} for a in payload.get("attention") or []]
        items.sort(key=lambda a: SEVERITY_ORDER[a["severity"]])
        diagnostics = dict(payload.get("diagnostics") or {})
        snapshot = self._snapshot(server_id)
        if snapshot and snapshot[1] == "FULL_TEST_FAILURE_CONFIRMED" and any(e["source"] == "abroad" and e["state"] == "operational" for e in detail["checks"]):
            diagnostics.setdefault("code", "BLOCKED_IN_COUNTRY")
            diagnostics.setdefault("abroad_reachable", True)
            diagnostics.setdefault("action_key", "admin.diag.action")
        return {**detail, "attention": [a["message"][:80] for a in items], "attention_items": items, "diagnostics": diagnostics}

    def admin_probes(self) -> list[dict]:
        out = []
        for row in self.db.execute(
            "SELECT public_id, kind, status, capabilities_json, agent_version, last_seen_at FROM probes ORDER BY enrolled_at"
        ).fetchall():
            report = self.db.execute(
                "SELECT route_verified, network_type FROM probe_reports r JOIN probes p ON p.id = r.probe_id WHERE p.public_id = ? ORDER BY received_at DESC LIMIT 1",
                (row[0],),
            ).fetchone()
            status = row[2]
            last_seen = _dt(row[5])
            if status == "active" and (last_seen is None or self.now() - last_seen > self.silent_after):
                status = "stale"
            out.append({
                "id": row[0], "kind": row[1], "status": status, "last_seen_at": _iso(last_seen),
                "capabilities": json.loads(row[3] or "[]") or PROBE_CAPABILITIES.get(row[1], []),
                "agent_version": row[4], "route_verified": (bool(report[0]) if report else None),
                "queued_reports": None, "network_type": (report[1] if report and report[1] in ("home", "cellular", "abroad", "unknown") else PROBE_NETWORK.get(row[1])),
            })
        return out

    def admin_overview(self, lang: str = "ru") -> dict:
        now = self.now()
        items: list[dict] = []
        for cfg in self._servers_config():
            payload = self._collector_payload(cfg["id"])
            for a in payload.get("attention") or []:
                items.append({"severity": a["severity"], "code": a["code"], "message": self._text(a.get("message"), lang)[:240], "server_id": cfg["id"]})
        doctor_items: list[dict] = []
        servers = self._servers_config()
        if not servers:
            doctor_items.append({"check": "servers", "state": "fail", "next": self.i18n.t(lang, "doctor.servers.fail"), "command": "vpn-pulse server add"})
        probes = self.admin_probes()
        if not probes:
            items.append({"severity": "medium", "code": "PROBES_NOT_ENROLLED", "message": self.i18n.t(lang, "attention.probesNotEnrolled"), "server_id": None})
            hint = "doctor.probes.afterServer" if not servers else "doctor.probes.enroll"
            doctor_items.append({"check": "probes", "state": "warn", "next": self.i18n.t(lang, hint), "command": "vpn-pulse probe enroll pc"})
        else:
            silent = [p for p in probes if p["status"] in ("stale", "stopped")]
            for p in silent:
                minutes = _minutes(_dt(p["last_seen_at"]), now)
                items.append({"severity": "medium", "code": "PROBE_SILENT", "message": self.i18n.t(lang, "attention.probeSilent", name=self.i18n.t(lang, "admin.probe." + p["kind"]), duration=self.i18n.duration(lang, minutes)), "server_id": None})
            if silent:
                doctor_items.append({"check": "probes", "state": "warn", "next": self.i18n.t(lang, "doctor.probes.silent"), "command": "vpn-pulse doctor probes"})
        last_run = self.db.execute("SELECT finished_at, result FROM collection_runs ORDER BY started_at DESC LIMIT 1").fetchone()
        if servers:
            if last_run is None:
                doctor_items.append({"check": "collector", "state": "fail", "next": self.i18n.t(lang, "doctor.collector.fail"), "command": "vpn-pulse doctor collector"})
                items.append({"severity": "high", "code": "COLLECTOR_STALE", "message": self.i18n.t(lang, "attention.collectorStale"), "server_id": None})
            else:
                finished = _dt(last_run[0])
                if last_run[1] != "ok" or finished is None or now - finished > 3 * self.collection_interval:
                    doctor_items.append({"check": "collector", "state": "warn", "next": self.i18n.t(lang, "doctor.collector.stale"), "command": "vpn-pulse doctor collector"})
                    items.append({"severity": "high", "code": "COLLECTOR_STALE", "message": self.i18n.t(lang, "attention.collectorStale"), "server_id": None})
        stuck = self.db.execute("SELECT count(*) FROM notification_queue WHERE state = 'pending' AND next_attempt_at < ?", (_iso(now - timedelta(minutes=10)),)).fetchone()[0]
        if stuck:
            doctor_items.append({"check": "queue", "state": "warn", "next": self.i18n.t(lang, "doctor.queue.stuck", n=stuck), "command": "vpn-pulse doctor queue"})
        items.sort(key=lambda a: SEVERITY_ORDER[a["severity"]])
        result = "fail" if any(d["state"] == "fail" for d in doctor_items) else "warn" if doctor_items else "ok"
        return {"attention_items": items[:100], "doctor": {"result": result, "items": doctor_items[:20]}, "next_command": doctor_items[0]["command"] if doctor_items else None}

    def readiness(self) -> dict:
        now = self.now()
        checks: dict[str, dict] = {}
        try:
            self.db.execute("SELECT 1 FROM servers LIMIT 1").fetchone()
            checks["database"] = {"ok": True, "age_seconds": None}
        except sqlite3.Error:
            checks["database"] = {"ok": False, "age_seconds": None}
        last_run = self.db.execute("SELECT finished_at, result FROM collection_runs ORDER BY started_at DESC LIMIT 1").fetchone()
        if last_run and last_run[0]:
            age = int((now - _dt(last_run[0])).total_seconds())
            checks["collector"] = {"ok": last_run[1] == "ok" and age <= 3 * self.collection_interval.total_seconds(), "age_seconds": max(0, age)}
        else:
            checks["collector"] = {"ok": False, "age_seconds": None}
        pending = self.db.execute("SELECT MIN(created_at) FROM notification_queue WHERE state = 'pending'").fetchone()[0]
        age = int((now - _dt(pending)).total_seconds()) if pending else 0
        checks["queue"] = {"ok": age <= 600, "age_seconds": max(0, age)}
        checks["storage"] = {"ok": True, "age_seconds": None}
        return {"ready": all(c["ok"] for c in checks.values()), "checks": checks}
