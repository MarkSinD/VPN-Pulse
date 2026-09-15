"""Demo scenarios for the dev server: compact fixtures → contract-shaped API payloads.

`fixtures/ui/scenarios.json` describes the demo world once (servers, per-scenario overrides,
event sets, admin data). This module resolves scenario inheritance and turns the result into the
exact shapes of `contracts/openapi.yaml` — the same payloads the Mini App receives from a real
deployment. Nothing here touches a server; everything is fictional.

The current scenario and UI language are per-request values (`contextvars`) set by the dev
server's middleware, so one process can serve many scenarios side by side (`?scenario=…`).
"""
from __future__ import annotations

import contextvars
import json
import math
import os
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from vpnpulse.api.read_model import ReadModelUnavailable

REQUEST: contextvars.ContextVar[dict | None] = contextvars.ContextVar("vpnpulse_dev_request", default=None)

KINDS = ("pc", "mobile", "abroad")
KIND_PROBE = {"pc": "pc", "mobile": "android", "abroad": "abroad"}
RESULT_STATE = {"ok": "operational", "fail": "unavailable", "partial": "degraded", "unknown": "unknown"}
FRESHNESS_SECONDS = 180
EVENT_KIND = {
    "stateChanged": "state_change", "sourceFailed": "monitoring", "recovered": "recovery", "note": "note",
    "addressUpdated": "configuration", "keysIssued": "configuration", "probeSilent": "monitoring",
}
EVENT_SEVERITY = {"ok": "info", "problem": "critical", "note": "info", "info": "info"}
COMPONENT_IDS = (("amneziawg", "amneziawg"), ("xray", "xray"), ("hiddify", "hiddify"), ("ddns", "ddns"), ("bbr", "tuning"))
PROBE_CAPABILITIES = {"pc": ["control_internet", "handshake", "https"], "android": ["dns", "tcp"], "abroad": ["handshake"]}
PROBE_NETWORK = {"pc": "home", "android": "cellular", "abroad": "abroad"}
UI_ONLY_SCENARIOS = {"loading"}  # the skeleton is a client state, not an API answer
NAMESPACE = uuid.UUID("6f0f4c1e-6d2a-4a58-9d6e-3d5e7f1a2b3c")


def default_fixtures_path() -> Path:
    env = os.environ.get("VPNPULSE_UI_FIXTURES")
    if env:
        return Path(env)
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "fixtures" / "ui" / "scenarios.json"
        if candidate.exists():
            return candidate
    raise FileNotFoundError("fixtures/ui/scenarios.json not found; set VPNPULSE_UI_FIXTURES")


def _parse_percent(value) -> float | None:
    if value is None or value == "—":
        return None
    return round(float(str(value).replace("%", "").replace(",", ".")) / 100, 4)


def _seeded(seed: int, base: float, amp: float, points: int, hours_per_point: float) -> list[float]:
    out = []
    for i in range(points):
        hour = i * hours_per_point
        day = max(0.0, math.sin((hour - 6) / 24 * math.pi * 2))
        out.append(max(0.0, round((base + amp * day + ((i * 7 + seed) % 5) * 0.3 - 0.6) * 10) / 10))
    return out


@dataclass
class Scenario:
    id: str
    raw: dict
    servers: list[dict]
    events: list[dict]
    admin: dict | None
    presence: dict[str, str]
    now: datetime
    extra: dict = field(default_factory=dict)

    def server(self, server_id: str) -> dict | None:
        return next((s for s in self.servers if s["id"] == server_id), None)


class ScenarioCatalog:
    def __init__(self, data: dict) -> None:
        self.data = data

    @classmethod
    def load(cls, path: Path | None = None) -> "ScenarioCatalog":
        return cls(json.loads((path or default_fixtures_path()).read_text(encoding="utf-8")))

    @property
    def ids(self) -> list[str]:
        return [k for k in self.data["scenarios"] if k not in UI_ONLY_SCENARIOS]

    def merged(self, scenario_id: str) -> dict:
        raw = self.data["scenarios"].get(scenario_id) or self.data["scenarios"]["operational"]
        if not raw.get("inherit"):
            return dict(raw)
        base = self.merged(raw["inherit"])
        merged = {**base, **raw}
        merged["servers"] = dict(base.get("servers") or {})
        for sid, over in (raw.get("servers") or {}).items():
            merged["servers"][sid] = {**merged["servers"].get(sid, {}), **over}
        if "events" not in raw:
            merged["events"] = base.get("events")
        return merged

    def build(self, scenario_id: str, now: datetime) -> Scenario:
        fx = self.data
        sc = self.merged(scenario_id)
        # events: a set name, a list, plus an optional appended set
        ev = sc.get("events")
        if isinstance(ev, str):
            ev = fx["eventSets"][ev]
        ev = list(ev or [])
        if sc.get("eventsAppend"):
            ev = ev + list(fx["eventSets"][sc["eventsAppend"]])
        # servers
        servers: list[dict] = []
        if not sc.get("empty") and not sc.get("loading") and sc.get("api") != "auth":
            for base_s in fx["servers"]:
                over = (sc.get("servers") or {}).get(base_s["id"])
                if not over:
                    continue
                s = {**base_s, **over}
                s["load"] = {**fx["defaults"]["load"][s["id"]], **(over.get("load") or {})}
                s["sources"] = {k: {**fx["defaults"]["sourcesOk"][k], **((over.get("sources") or {}).get(k) or {})} for k in KINDS}
                base = 1 + s["load"]["awg"] / 4 if s["load"]["awg"] else 0.3
                s["series"] = _seeded(s["seed"], base, 3 + s["load"]["awg"], 48, 0.5)
                if s["state"] == "unavailable":
                    s["series"][46] = 0
                    s["series"][47] = 0
                s["segs"] = ["operational"] * 48
                for a, b, state in over.get("marks") or []:
                    for i in range(a, b + 1):
                        s["segs"][i] = state
                if over.get("gapFrom") is not None:
                    for i in range(over["gapFrom"], 48):
                        s["segs"][i] = "unknown"
                        s["series"][i] = None
                servers.append(s)
        # admin
        admin = None
        if sc.get("admin", {}) is not None:
            a = sc.get("admin") or {}
            defaults = fx["defaults"]["admin"]
            admin = {
                "attention": list(a.get("attentionPrepend") or []) + list(a["attention"] if "attention" in a else defaults["attention"]),
                "probes": {**defaults["probes"], **(a.get("probes") or {})},
                "services": {**defaults["services"], **(a.get("services") or {})},
                "doctor": a.get("doctor") or defaults["doctor"],
                "enrollCode": defaults["enrollCode"],
                "nextCommand": a.get("nextCommand"),
            }
        # presence of check sources: none / silent / active (see monitoring policy)
        presence: dict[str, str] = {}
        over_sources = sc.get("sources") or {}
        for k in KINDS:
            if over_sources.get(k):
                presence[k] = over_sources[k]
                continue
            p = admin["probes"].get(KIND_PROBE[k]) if admin else None
            presence[k] = "none" if not p or p.get("enrolled") is False else ("silent" if p.get("state") == "unknown" else "active")
        return Scenario(scenario_id, sc, servers, ev, admin, presence, now)


class FixtureReadModel:
    """ReadModel over the demo catalog. Scenario and language come from the request context."""

    def __init__(self, catalog: ScenarioCatalog, *, default_scenario: str = "operational", contact_url: str | None = "https://t.me/example_admin", now=None) -> None:
        self.catalog = catalog
        self.default_scenario = default_scenario
        self.contact_url = contact_url
        self._now = now or (lambda: datetime.now(UTC))
        self._revoked: set[str] = set()

    # ---------- request context ----------
    def _ctx(self) -> tuple[Scenario, str]:
        req = REQUEST.get() or {}
        scenario_id = req.get("scenario") or self.default_scenario
        lang = req.get("lang") or "ru"
        if lang not in ("ru", "en"):
            lang = "ru"
        return self.catalog.build(scenario_id, self._now()), lang

    @staticmethod
    def _text(value, lang: str) -> str:
        if isinstance(value, dict):
            return value.get(lang) or value.get("ru") or ""
        return "" if value is None else str(value)

    def _iso(self, dt: datetime | None) -> str | None:
        return dt.astimezone(UTC).isoformat().replace("+00:00", "Z") if dt else None

    def _freshness(self, now: datetime, minutes) -> dict:
        if minutes is None:
            return {"observed_at": None, "fresh_until": None, "is_stale": True}
        observed = now - timedelta(minutes=minutes)
        return {
            "observed_at": self._iso(observed),
            "fresh_until": self._iso(observed + timedelta(seconds=FRESHNESS_SECONDS)),
            "is_stale": minutes * 60 > FRESHNESS_SECONDS,
        }

    def _at(self, now: datetime, day, hhmm: str) -> datetime:
        hour, minute = (int(x) for x in hhmm.split(":"))
        if isinstance(day, int):
            base = (now - timedelta(days=day)).date()
        else:
            base = datetime.fromisoformat(str(day)).date()
        return datetime(base.year, base.month, base.day, hour, minute, tzinfo=UTC)

    # ---------- building blocks ----------
    def _evidence(self, sc: Scenario, s: dict) -> list[dict]:
        out = []
        for k in KINDS:
            if sc.presence[k] == "none":
                continue
            src = s["sources"][k]
            out.append({
                "source": k,
                "state": RESULT_STATE[src["r"]],
                "freshness": self._freshness(sc.now, src.get("age")),
                "reason_code": str(src.get("detailKey", "")).split(".")[-1] or None,
            })
        return out

    def _card(self, sc: Scenario, s: dict, lang: str) -> dict:
        known = [x for x in s["segs"] if x != "unknown"]
        return {
            "id": s["id"],
            "name": self._text(s["name"], lang),
            "country_code": s["cc"].upper(),
            "state": s["state"],
            "freshness": self._freshness(sc.now, s.get("staleMin", sc.raw.get("freshnessMin"))),
            "recommended": sc.raw.get("recommended") == s["id"],
            "uptime_24h": _parse_percent(s.get("uptime24")),
            "coverage_24h": None if s["state"] == "unknown" and not known else round(len(known) / 48, 4),
            "sources": self._evidence(sc, s),
        }

    def _detail(self, sc: Scenario, s: dict, lang: str) -> dict:
        ld, xr = s["load"], "xray" in s["protocols"]
        protocols = [{"kind": "amneziawg", "state": s["state"], "coverage": 0.0 if s["state"] == "unknown" else 1.0, "connections": ld["awg"]}]
        if xr:
            protocols.append({"kind": "xray_reality", "state": s["state"] if ld.get("xrayKnown") else "unknown",
                              "coverage": 1.0 if ld.get("xrayKnown") else 0.0, "connections": ld.get("xray") if ld.get("xrayKnown") else None})
        components = []
        for w in s.get("software", []):
            name = w["name"]
            cid = next((cid for needle, cid in COMPONENT_IDS if needle in name.lower()), "other")
            parts = name.split()
            version = parts[-1] if len(parts) > 1 and parts[-1][0].isdigit() else None
            components.append({"id": cid, "name": name if version is None else " ".join(parts[:-1]), "version": version,
                               "note_key": w.get("noteKey"), "note": w.get("note")})
        sysm = s.get("system", {})
        checks = [{"check": "ssh", "ok": bool(sysm.get("ssh"))}, {"check": "engine", "ok": True}, {"check": "port", "ok": bool(sysm.get("port"))}]
        if sysm.get("dns"):
            checks += [{"check": "dns", "ok": True}, {"check": "ddns", "ok": bool(sysm.get("ddns"))}]
        return {
            **self._card(sc, s, lang),
            "protocols": protocols,
            "checks": self._evidence(sc, s),
            "uptime_7d": _parse_percent(s.get("uptime7")),
            "coverage_7d": None if s["state"] == "unknown" else 1.0,
            "components": components,
            "resources": {"traffic_mbps": ld["mbit"], "cpu_percent": ld["cpu"], "memory_percent": ld["ram"], "swap_percent": ld["swap"], "peak_connections_24h": ld["peak"]},
            "profiles": {"issued": s["keys"]["issued"], "ever_connected": s["keys"]["ever"], "active_24h": s["keys"]["active"]},
            "service_checks": checks,
        }

    def _event(self, sc: Scenario, index: int, e: dict, lang: str) -> dict:
        params: dict = {}
        if e.get("state"):
            params["state"] = e["state"]
        if e.get("source"):
            params["source"] = e["source"]
        if e.get("text") is not None:
            params["text"] = self._text(e["text"], lang)
        severity = EVENT_SEVERITY.get(e.get("sev"), "info")
        if e.get("kind") == "stateChanged" and e.get("state") == "degraded":
            severity = "warning"
        return {
            "id": str(uuid.uuid5(NAMESPACE, f"{sc.id}:{index}:{e.get('kind')}:{e.get('day')}:{e.get('time')}")),
            "kind": EVENT_KIND.get(e.get("kind"), "monitoring"),
            "severity": severity,
            "server_id": e.get("server"),
            "title_key": "events." + str(e.get("kind")),
            "params": params,
            "occurred_at": self._iso(self._at(sc.now, e.get("day", 0), e.get("time", "00:00"))),
        }

    # ---------- ReadModel ----------
    def status(self, role: str) -> dict:
        sc, lang = self._ctx()
        if sc.raw.get("api") == "offline":
            raise ReadModelUnavailable("STATUS_UNAVAILABLE")
        note = sc.raw.get("note")
        active = [k for k in KINDS if sc.presence[k] == "active"]
        present = [k for k in KINDS if sc.presence[k] != "none"]
        since = self.catalog.data["meta"].get("since")
        return {
            "state": sc.raw.get("overall", "unknown"),
            "freshness": self._freshness(sc.now, sc.raw.get("freshnessMin")),
            "coverage": round(len(active) / len(KINDS), 4),
            "mode": "demo" if sc.raw.get("demo") else "live",
            "observing_since": self._iso(datetime.fromisoformat(since).replace(tzinfo=UTC)) if since else None,
            "recommended_server_id": sc.raw.get("recommended"),
            "note": None if not note else {
                "id": str(uuid.uuid5(NAMESPACE, f"{sc.id}:note")),
                "server_id": None,
                "text": self._text(note["text"], lang),
                "expires_at": self._iso(self._at(sc.now, 0, note["expires"])) if note.get("expires") else None,
                "created_at": self._iso(self._at(sc.now, 0, note.get("time", "00:00"))),
            },
            "servers": [self._card(sc, s, lang) for s in sc.servers],
            "sources": [{
                "source": k,
                "state": sc.presence[k],
                "last_report_at": self._iso(sc.now - timedelta(minutes=(sc.admin or {}).get("probes", {}).get(KIND_PROBE[k], {}).get("lastMin") or 0)),
            } for k in present],
        }

    def server(self, server_id: str, role: str) -> dict | None:
        sc, lang = self._ctx()
        if sc.raw.get("api") == "offline":
            raise ReadModelUnavailable("STATUS_UNAVAILABLE")
        s = sc.server(server_id)
        return None if s is None else self._detail(sc, s, lang)

    def metrics(self, server_id: str, period: str) -> dict | None:
        sc, _ = self._ctx()
        s = sc.server(server_id)
        if s is None:
            return None
        if period == "24h":
            step, series, segs = timedelta(minutes=30), s["series"], s["segs"]
        else:
            step = timedelta(hours=1)
            base = 1 + s["load"]["awg"] / 4 if s["load"]["awg"] else 0.3
            series = _seeded(s["seed"], base, 3 + s["load"]["awg"], 168, 1.0)
            segs = ["operational"] * 120 + s["segs"]
            for i in range(120, 168):
                if segs[i] == "unknown":
                    series[i] = None
        n = len(series)
        points = [{
            "at": self._iso(sc.now - step * (n - 1 - i)),
            "state": segs[i],
            "coverage": 0.0 if segs[i] == "unknown" else 1.0,
            "connections": None if series[i] is None else int(round(series[i])),
        } for i in range(n)]
        return {"server_id": server_id, "period": period, "coverage": round(sum(1 for p in points if p["coverage"]) / n, 4), "points": points}

    def events(self, filter: str, cursor: str | None, limit: int) -> dict:
        sc, lang = self._ctx()
        if sc.raw.get("api") == "offline":
            raise ReadModelUnavailable("STATUS_UNAVAILABLE")
        items = [self._event(sc, i, e, lang) for i, e in enumerate(sc.events)]
        items.sort(key=lambda e: e["occurred_at"], reverse=True)
        if filter == "problems":
            items = [e for e in items if e["severity"] in ("warning", "critical")]
        elif filter == "notes":
            items = [e for e in items if e["kind"] == "note"]
        start = int(cursor) if cursor and cursor.isdigit() else 0
        page = items[start:start + limit]
        return {"items": page, "next_cursor": str(start + limit) if start + limit < len(items) else None}

    def help(self) -> dict:
        return {"step_keys": ["help.step1", "help.step2", "help.step3", "help.step4"],
                "contact_available": self.contact_url is not None, "contact_url": self.contact_url}

    def admin_server(self, server_id: str) -> dict | None:
        sc, lang = self._ctx()
        s = sc.server(server_id)
        if s is None:
            return None
        items = [a for a in (sc.admin or {}).get("attention", []) if a.get("server") == server_id]
        attention_items = [{"severity": a["sev"], "code": a.get("code", "ATTENTION"), "message": self._text(a["text"], lang), "server_id": server_id} for a in items]
        diagnostics = {}
        if s.get("diag"):
            diagnostics = {"code": "BLOCKED_IN_COUNTRY", "abroad_reachable": True, "ssh_ok": True, "action_key": "admin.diag.action"}
        return {**self._detail(sc, s, lang), "attention": [a["message"][:80] for a in attention_items], "attention_items": attention_items, "diagnostics": diagnostics}

    def admin_probes(self) -> list[dict]:
        sc, _ = self._ctx()
        out = []
        for kind, p in (sc.admin or {}).get("probes", {}).items():
            if p.get("enrolled") is False:
                continue
            probe_id = f"probe-{kind}"
            status = "revoked" if probe_id in self._revoked else ("stopped" if p.get("session") == "stopped" else "stale" if p.get("state") == "unknown" else "active")
            out.append({
                "id": probe_id,
                "kind": kind,
                "status": status,
                "last_seen_at": self._iso(sc.now - timedelta(minutes=p["lastMin"])) if p.get("lastMin") is not None else None,
                "capabilities": PROBE_CAPABILITIES[kind],
                "agent_version": p.get("version"),
                "route_verified": p.get("route") if kind == "pc" else None,
                "queued_reports": p.get("queue"),
                "network_type": PROBE_NETWORK[kind],
            })
        return out

    def revoke_probe(self, probe_id: str) -> bool:
        known = {f"probe-{k}" for k in ("pc", "android", "abroad")}
        if probe_id not in known:
            return False
        self._revoked.add(probe_id)
        return True

    def readiness(self) -> dict:
        sc, _ = self._ctx()
        services = (sc.admin or {}).get("services") or self.catalog.data["defaults"]["admin"]["services"]
        checks = {name: {"ok": state == "ok", "age_seconds": 0 if state == "ok" else None} for name, state in services.items()}
        return {"ready": all(c["ok"] for c in checks.values()), "checks": checks}
