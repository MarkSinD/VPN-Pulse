"""Contract tests for the fields the accepted UI v4 relies on (see plans/ui-contract-map.md).

They validate representative payloads against the OpenAPI component schemas, so a later
schema change that breaks the UI shows up here before any server code exists.
"""
from __future__ import annotations

from pathlib import Path

import jsonschema
import pytest
import yaml


def _contracts_dir() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "contracts"
        if (candidate / "openapi.yaml").exists():
            return candidate
    raise FileNotFoundError("contracts/openapi.yaml not found above tests/")


OPENAPI = yaml.safe_load((_contracts_dir() / "openapi.yaml").read_text(encoding="utf-8"))


def validate(schema_name: str, payload: dict) -> None:
    root = {"$ref": f"#/components/schemas/{schema_name}", "components": OPENAPI["components"]}
    jsonschema.Draft202012Validator(root).validate(payload)


FRESH = {"observed_at": "2026-09-13T11:32:00Z", "fresh_until": "2026-09-13T11:35:00Z", "is_stale": False}
STALE = {"observed_at": "2026-09-13T11:07:00Z", "fresh_until": "2026-09-13T11:10:00Z", "is_stale": True}


def card(**over):
    base = {
        "id": "server-1", "name": "Server 1", "country_code": "LV", "state": "operational",
        "freshness": FRESH, "recommended": True, "uptime_24h": 1.0, "coverage_24h": 1.0,
        "sources": [
            {"source": "pc", "state": "operational", "freshness": FRESH, "reason_code": "handshake_https_ok"},
            {"source": "mobile", "state": "operational", "freshness": FRESH, "reason_code": "dns_reach_ok"},
            {"source": "abroad", "state": "operational", "freshness": FRESH, "reason_code": None},
        ],
    }
    base.update(over)
    return base


def test_status_clean_install_has_no_servers_and_demo_mode():
    validate("StatusResponse", {
        "state": "unknown", "freshness": {"observed_at": None, "fresh_until": None, "is_stale": True},
        "coverage": 0, "mode": "demo", "observing_since": None, "recommended_server_id": None, "note": None, "servers": [],
    })


def test_status_unknown_row_uses_null_uptime_not_zero():
    payload = {
        "state": "unknown", "freshness": STALE, "coverage": 0.4, "mode": "live",
        "observing_since": "2026-06-06T00:00:00Z", "recommended_server_id": None, "note": None,
        "servers": [card(state="unknown", recommended=False, uptime_24h=None, coverage_24h=0.6,
                         sources=[{"source": "pc", "state": "unknown", "freshness": STALE, "reason_code": "pc_silent"}])],
    }
    validate("StatusResponse", payload)
    assert payload["servers"][0]["uptime_24h"] is None


def test_server_detail_carries_ui_groups():
    detail = card()
    detail.update({
        "protocols": [
            {"kind": "amneziawg", "state": "operational", "coverage": 1.0, "connections": 5},
            {"kind": "xray_reality", "state": "unknown", "coverage": 0.0, "connections": None},
        ],
        "checks": detail["sources"],
        "uptime_7d": 0.998, "coverage_7d": 0.97,
        "components": [
            {"id": "hiddify", "name": "Hiddify Manager", "version": "pre2096", "note_key": "server.software.panel"},
            {"id": "xray", "name": "Xray", "version": "26.2", "note_key": None},
            {"id": "amneziawg", "name": "AmneziaWG", "version": None, "note_key": "server.software.docker"},
        ],
        "resources": {"traffic_mbps": 18.4, "cpu_percent": 21, "memory_percent": 54, "swap_percent": 17, "peak_connections_24h": 14},
        "profiles": {"issued": 26, "ever_connected": 19, "active_24h": 9},
        "service_checks": [{"check": "ssh", "ok": True}, {"check": "engine", "ok": True}, {"check": "port", "ok": True}, {"check": "dns", "ok": None}],
    })
    validate("ServerDetail", detail)
    xray = next(p for p in detail["protocols"] if p["kind"] == "xray_reality")
    assert xray["connections"] is None, "unknown Xray must be null, never zero"


def test_admin_detail_structured_attention():
    detail = card()
    detail.update({
        "protocols": [{"kind": "amneziawg", "state": "unavailable", "coverage": 1.0, "connections": 0}],
        "checks": [], "attention": ["blocked in country"],
        "attention_items": [{"severity": "high", "code": "BLOCKED_IN_COUNTRY", "message": "Failing checks from inside the country for 18 minutes; reachable from abroad.", "server_id": "server-1"}],
        "diagnostics": {"pc_failures_in_row": 2},
    })
    validate("AdminServerDetail", detail)


def test_probe_summary_health_fields():
    validate("ProbeSummary", {
        "id": "probe-pc-1", "kind": "pc", "status": "active", "last_seen_at": "2026-09-13T11:32:00Z",
        "capabilities": ["report_pc"], "agent_version": "0.1.0", "route_verified": True, "queued_reports": 0, "network_type": "home",
    })
    validate("ProbeSummary", {
        "id": "probe-android-1", "kind": "android", "status": "stopped", "last_seen_at": None,
        "capabilities": ["report_mobile"], "agent_version": None, "route_verified": None, "queued_reports": 3, "network_type": None,
    })


def test_event_kinds_cover_probe_health():
    validate("Event", {
        "id": "5f0b1a2c-0000-4000-8000-000000000001", "kind": "monitoring", "severity": "warning", "server_id": None,
        "title_key": "events.probeSilent", "params": {"source": "pc"}, "occurred_at": "2026-09-13T11:10:00Z",
    })


def test_help_contact_url_is_optional_and_nullable():
    schema = OPENAPI["paths"]["/help"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    jsonschema.Draft202012Validator(schema).validate({"step_keys": ["help.step1", "help.step2", "help.step3", "help.step4"], "contact_available": False, "contact_url": None})
    jsonschema.Draft202012Validator(schema).validate({"step_keys": ["help.step1", "help.step2", "help.step3", "help.step4"], "contact_available": True, "contact_url": "https://t.me/example_admin"})


def test_analytics_allowlist_contains_ui_events():
    schema = yaml.safe_load((_contracts_dir() / "analytics-events.schema.json").read_text(encoding="utf-8"))
    names = set(schema["properties"]["name"]["enum"])
    for used in ("app_opened", "status_ready", "server_row_pressed", "server_detail_viewed", "detail_group_toggled",
                 "events_viewed", "events_filter_changed", "help_viewed", "help_step_opened", "contact_admin_pressed",
                 "language_changed", "retry_pressed", "ui_error_shown", "quick_start_opened"):
        assert used in names, used


def test_status_lists_only_reporting_sources():
    payload = {
        "state": "operational", "freshness": FRESH, "coverage": 0.67, "mode": "live",
        "observing_since": "2026-09-01T00:00:00Z", "recommended_server_id": "s1", "note": None,
        "servers": [card(state="operational", recommended=True, uptime_24h=1.0, coverage_24h=1.0)],
        "sources": [
            {"source": "mobile", "state": "active", "last_report_at": "2026-09-13T14:30:00Z"},
            {"source": "abroad", "state": "silent", "last_report_at": "2026-09-13T13:10:00Z"},
        ],
    }
    validate("StatusResponse", payload)
    with pytest.raises(jsonschema.ValidationError):
        validate("SourceAvailability", {"source": "pc", "state": "missing", "last_report_at": None})
