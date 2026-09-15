"""Write a demo scenario into a real SQLite database (tests, `--sqlite` dev mode, demo installs).

The seed produces exactly what collectors, probes and the evaluator would have left behind:
servers and protocols, seven days of collector observations with connection counts, the latest
collector payload (contracts/collector-observation.schema.json), evidence observations per check
source, state snapshots and transitions matching the scenario's timeline, events, the admin note,
probes with their last reports and a finished collection run. Nothing real: ids, names and
numbers come from fixtures/ui/scenarios.json.
"""
from __future__ import annotations

import json
import math
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta

from vpnpulse.dev.scenarios import EVENT_KIND, EVENT_SEVERITY, KINDS, Scenario, ScenarioCatalog, _seeded

FRESHNESS = timedelta(seconds=180)
RESULT_OF = {"ok": "success", "fail": "failure", "partial": "failure", "unknown": "not_run"}
REASON_OF = {"operational": "FULL_SUCCESS_CONFIRMED", "degraded": "CONFLICTING_FRESH_EVIDENCE", "unavailable": "FULL_TEST_FAILURE_CONFIRMED", "unknown": "NO_FRESH_EVIDENCE"}
COMPONENT_IDS = (("amneziawg", "amneziawg"), ("xray", "xray"), ("hiddify", "hiddify"), ("ddns", "ddns"), ("bbr", "tuning"))
NAMESPACE = uuid.UUID("2b6c1d0e-1f7a-4b2e-9c3d-8e4f5a6b7c8d")


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _uid(*parts) -> str:
    return str(uuid.uuid5(NAMESPACE, ":".join(str(p) for p in parts)))


def config_for(catalog: ScenarioCatalog, scenario: Scenario, contact_url: str | None = "https://t.me/example_admin") -> dict:
    """A public config.yaml-shaped dict describing the scenario's servers."""
    servers = []
    for index, base in enumerate(catalog.data["servers"]):
        if scenario.server(base["id"]) is None:
            continue
        engine = (base.get("system") or {}).get("engine")
        servers.append({
            "id": base["id"],
            "type": "awg-host" if engine == "module" else "awg-docker",
            "name": base["name"],
            "country_code": base["cc"].upper(),
            "enabled": True,
            "recommended_priority": 10 * (index + 1),
            "collector_ref": f"collector-{base['id']}",
        })
    app = {"default_language": "ru", "languages": ["ru", "en"], "timezone": "UTC"}
    if contact_url:
        app["admin_contact_url"] = contact_url
    return {
        "version": 1,
        "app": app,
        "servers": servers,
        "monitoring": {"collection_interval_seconds": 60, "pc_target_interval_seconds": 60, "probe_deadline_seconds": 20, "confirmations": 2, "freshness_seconds": 180},
        "retention": {"observations_days": 7, "aggregates_days": 90, "events_days": 180, "analytics_raw_days": 30, "audit_days": 365},
    }


def _collector_payload(s: dict, now: datetime, with_details: bool) -> dict:
    ld = s["load"]
    connections = {"amneziawg": ld["awg"]}
    if "xray" in s["protocols"]:
        connections["xray_reality"] = ld.get("xray") if ld.get("xrayKnown") else None
    payload: dict = {"connections": connections}
    if not with_details:
        return payload
    components = []
    for w in s.get("software", []):
        name = w["name"]
        cid = next((cid for needle, cid in COMPONENT_IDS if needle in name.lower()), "other")
        parts = name.split()
        version = parts[-1] if len(parts) > 1 and parts[-1][0].isdigit() else None
        components.append({"id": cid, "name": name if version is None else " ".join(parts[:-1]), "version": version, "note_key": w.get("noteKey"), "note": w.get("note")})
    sysm = s.get("system") or {}
    checks = [{"check": "ssh", "ok": bool(sysm.get("ssh"))}, {"check": "engine", "ok": True}, {"check": "port", "ok": bool(sysm.get("port"))}]
    if sysm.get("dns"):
        checks += [{"check": "dns", "ok": True}, {"check": "ddns", "ok": bool(sysm.get("ddns"))}]
    payload.update({
        "resources": {"traffic_mbps": ld["mbit"], "cpu_percent": ld["cpu"], "memory_percent": ld["ram"], "swap_percent": ld["swap"], "peak_connections_24h": ld["peak"]},
        "profiles": {"issued": s["keys"]["issued"], "ever_connected": s["keys"]["ever"], "active_24h": s["keys"]["active"],
                     "last_connection_at": None if ld.get("lastConnMin") is None else _iso(now - timedelta(minutes=ld["lastConnMin"]))},
        "components": components,
        "service_checks": checks,
    })
    return payload


def seed_scenario(connection: sqlite3.Connection, catalog: ScenarioCatalog, scenario_id: str, now: datetime | None = None, *, contact_url: str | None = "https://t.me/example_admin") -> dict:
    """Populate an empty, migrated database with the scenario. Returns the matching config dict."""
    now = now or datetime.now(UTC)
    sc = catalog.build(scenario_id, now)
    cfg = config_for(catalog, sc, contact_url)
    attention_by_server: dict[str, list[dict]] = {}
    for a in (sc.admin or {}).get("attention", []):
        if a.get("server"):
            attention_by_server.setdefault(a["server"], []).append({"severity": a["sev"], "code": a.get("code", "ATTENTION"), "message": a["text"]})
    with connection:
        for order, s in enumerate(sc.servers):
            connection.execute("INSERT INTO servers VALUES (?, ?, ?, 1, ?, ?, ?)",
                               (s["id"], s["id"], next(c["type"] for c in cfg["servers"] if c["id"] == s["id"]), order + 1, _iso(now - timedelta(days=30)), _iso(now)))
            kinds = ["amneziawg"] + (["xray_reality"] if "xray" in s["protocols"] else [])
            for kind in kinds:
                connection.execute("INSERT INTO protocols VALUES (?, ?, ?, ?, 1, ?, ?, ?)",
                                   (f"{s['id']}:{kind}", s["id"], kind, f"server.protocol.{kind}", "complete" if s["load"].get("xrayKnown", True) or kind == "amneziawg" else "partial", _iso(now - timedelta(days=30)), _iso(now)))
            # seven days of collector observations: hourly for days 1-7, half-hourly for the last day
            week = _seeded(s["seed"], 1 + s["load"]["awg"] / 4 if s["load"]["awg"] else 0.3, 3 + s["load"]["awg"], 168, 1.0)
            latest_at = now - timedelta(minutes=s.get("staleMin") or (sc.raw.get("freshnessMin") if s["state"] == "unknown" else 1) or 1)
            # observations sit in the middle of their slot so a sliding window never splits them
            for i in range(144):
                at = now - timedelta(hours=168 - i) + timedelta(minutes=30)
                connection.execute(_OBS_SQL, (_uid(scenario_id, s["id"], "col", i), s["id"], None, "collector", "all", _iso(at), _iso(at), "success", _iso(at + FRESHNESS), "sufficient",
                                              json.dumps({"connections": {"amneziawg": int(math.floor(week[i] + 0.5))}}), None, None, None))
            last_obs_at = now - timedelta(hours=25)
            for i in range(48):
                if s["segs"][i] == "unknown":
                    continue
                at = now - timedelta(minutes=30 * (48 - i)) + timedelta(minutes=15)
                last = i == 47 or all(x == "unknown" for x in s["segs"][i + 1:])
                value = s["series"][i]
                payload = _collector_payload(s, now, with_details=last)
                if value is not None:
                    payload["connections"]["amneziawg"] = int(math.floor(value + 0.5))
                if last and attention_by_server.get(s["id"]):
                    payload["attention"] = attention_by_server[s["id"]]
                if last and s.get("diag"):
                    payload["diagnostics"] = {"code": "BLOCKED_IN_COUNTRY", "abroad_reachable": True, "ssh_ok": True, "action_key": "admin.diag.action"}
                # the newest observation is fresh only when the timeline reaches the present; a gap at the end stays a gap
                obs_at = latest_at if (last and i == 47) else at
                last_obs_at = max(last_obs_at, obs_at)
                connection.execute(_OBS_SQL, (_uid(scenario_id, s["id"], "col24", i), s["id"], None, "collector", "all", _iso(obs_at), _iso(obs_at), "success", _iso(obs_at + FRESHNESS), "sufficient", json.dumps(payload), None, None, None))
            # evidence per existing check source, plus member connections when they confirm the state
            for k in KINDS:
                if sc.presence[k] == "none":
                    continue
                src = s["sources"][k]
                if src.get("age") is None:
                    continue
                at = now - timedelta(minutes=src["age"])
                meta = {"via_server_id": s.get("abroadFrom")} if k == "abroad" else {}
                connection.execute(_OBS_SQL, (_uid(scenario_id, s["id"], k), s["id"], None, k, "country" if k != "abroad" else "abroad", _iso(at), _iso(at), RESULT_OF[src["r"]], _iso(at + FRESHNESS), "sufficient", json.dumps(meta), str(src.get("detailKey", "")).split(".")[-1] or None, None, None))
            if s.get("confirmedBy") in ("humans", "both"):
                at = now - timedelta(minutes=1)
                connection.execute(_OBS_SQL, (_uid(scenario_id, s["id"], "humans"), s["id"], None, "human_activity", "all", _iso(at), _iso(at), "success", _iso(at + FRESHNESS), "sufficient", "{}", None, None, None))
            # snapshot + transitions reproducing the 24 h timeline
            snap_observed = min(latest_at, last_obs_at) if s["state"] == "unknown" else latest_at
            connection.execute("INSERT INTO state_snapshots VALUES (?, ?, NULL, 'all', ?, ?, 'sufficient', ?, ?, ?, ?, 1)",
                               (f"server:{s['id']}", s["id"], s["state"], REASON_OF[s["state"]], _iso(snap_observed), _iso(now), _iso(snap_observed + FRESHNESS), json.dumps({"count": 1, "coverage": 1.0})))
            prev = "operational"
            for i in range(48):
                state = s["segs"][i]
                if state != prev:
                    at = now - timedelta(minutes=30 * (48 - i)) + timedelta(seconds=1)
                    connection.execute(_TR_SQL, (_uid(scenario_id, s["id"], "tr", i), f"server:{s['id']}", prev, state, REASON_OF[state], _iso(at), _iso(at), _uid(scenario_id, s["id"], "dedupe", i), "{}"))
                    prev = state
            if prev != s["state"]:
                at = now - timedelta(minutes=1)
                connection.execute(_TR_SQL, (_uid(scenario_id, s["id"], "tr", "final"), f"server:{s['id']}", prev, s["state"], REASON_OF[s["state"]], _iso(at), _iso(at), _uid(scenario_id, s["id"], "dedupe", "final"), "{}"))
        # events
        for index, e in enumerate(sc.events):
            day = e.get("day", 0)
            hour, minute = (int(x) for x in str(e.get("time", "00:00")).split(":"))
            base = (now - timedelta(days=day)).date() if isinstance(day, int) else datetime.fromisoformat(str(day)).date()
            at = datetime(base.year, base.month, base.day, hour, minute, tzinfo=UTC)
            params: dict = {}
            if e.get("state"):
                params["state"] = e["state"]
            if e.get("source"):
                params["source"] = e["source"]
            if e.get("text") is not None:
                params["text"] = e["text"]
            severity = EVENT_SEVERITY.get(e.get("sev"), "info")
            if e.get("kind") == "stateChanged" and e.get("state") == "degraded":
                severity = "warning"
            connection.execute("INSERT INTO events VALUES (?, ?, ?, ?, NULL, ?, ?, ?, 'member', ?)",
                               (_uid(scenario_id, "event", index), EVENT_KIND.get(e.get("kind"), "monitoring"), severity, e.get("server"), "events." + str(e.get("kind")), json.dumps(params, ensure_ascii=False), _iso(at), _iso(at)))
        # the administrator note
        note = sc.raw.get("note")
        if note:
            hour, minute = (int(x) for x in note.get("time", "00:00").split(":"))
            created = datetime(now.year, now.month, now.day, hour, minute, tzinfo=UTC)
            expires = None
            if note.get("expires"):
                eh, em = (int(x) for x in note["expires"].split(":"))
                expires = datetime(now.year, now.month, now.day, eh, em, tzinfo=UTC)
            connection.execute("INSERT INTO admin_notes VALUES (?, NULL, ?, 'active', ?, ?, 'admin', ?, ?)",
                               (_uid(scenario_id, "note"), (note["text"].get("ru") if isinstance(note["text"], dict) else note["text"])[:500], _iso(created), _iso(expires) if expires else None, _iso(created), _iso(created)))
        # probes and their last reports
        for kind, p in ((sc.admin or {}).get("probes") or {}).items():
            if p.get("enrolled") is False:
                continue
            last_seen = now - timedelta(minutes=p["lastMin"]) if p.get("lastMin") is not None else None
            status = "stopped" if p.get("session") == "stopped" else "active"
            connection.execute("INSERT INTO probes VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, NULL)",
                               (f"probe-{kind}", f"probe-{kind}", kind, status, json.dumps({"pc": ["control_internet", "handshake", "https"], "android": ["dns", "tcp"], "abroad": ["handshake"]}.get(kind, [])), b"seed", "seed", p.get("version") or "0.1", _iso(now - timedelta(days=7)), _iso(last_seen) if last_seen else None))
            if last_seen is not None:
                connection.execute("INSERT INTO probe_reports VALUES (?, ?, 1, ?, ?, ?, ?, 'ipv4', ?, ?, 'ok', NULL)",
                                   (_uid(scenario_id, "report", kind), f"probe-{kind}", p.get("version") or "0.1", _iso(last_seen), _iso(last_seen), {"pc": "home", "android": "cellular", "abroad": "abroad"}[kind], 1 if p.get("route", True) else 0, b"seed"))
        # a finished collection run when there is something to collect
        if sc.servers and ((sc.admin or {}).get("services") or {}).get("collector", "ok") == "ok":
            connection.execute("INSERT INTO collection_runs VALUES (?, ?, ?, 'ok', ?, 1200, NULL)",
                               (_uid(scenario_id, "run"), _iso(now - timedelta(seconds=70)), _iso(now - timedelta(seconds=60)), _uid(scenario_id, "trace")))
    return cfg


_OBS_SQL = "INSERT INTO observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
_TR_SQL = "INSERT INTO state_transitions VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)"
