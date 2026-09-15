"""Response models for the read routes — the OpenAPI components as strict pydantic models.

FastAPI validates every read response against these before it leaves the process, so a read
model that drifts from contracts/openapi.yaml fails loudly instead of reaching the Mini App.
`extra="forbid"` mirrors `additionalProperties: false`; optional fields keep their `null` default
so members always receive the same keys.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

State = Literal["operational", "degraded", "unavailable", "unknown"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Freshness(Strict):
    observed_at: datetime | None
    fresh_until: datetime | None
    is_stale: bool


class EvidenceSummary(Strict):
    source: Literal["collector", "pc", "mobile", "abroad", "human_activity"]
    state: State
    freshness: Freshness
    reason_code: str | None = Field(default=None, max_length=80)
    via_server_id: str | None = None


class ServerCard(Strict):
    id: str
    name: str = Field(min_length=1, max_length=80)
    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    state: State
    freshness: Freshness
    recommended: bool
    uptime_24h: float | None = Field(ge=0, le=1)
    coverage_24h: float | None = Field(default=None, ge=0, le=1)
    sources: list[EvidenceSummary]


class AdminNote(Strict):
    id: str
    server_id: str | None = None
    text: str = Field(min_length=1, max_length=500)
    expires_at: datetime | None = None
    created_at: datetime


class SourceAvailability(Strict):
    source: Literal["pc", "mobile", "abroad"]
    state: Literal["active", "silent"]
    last_report_at: datetime | None


class StatusResponse(Strict):
    state: State
    freshness: Freshness
    coverage: float = Field(ge=0, le=1)
    mode: Literal["live", "demo"] = "live"
    observing_since: datetime | None = None
    recommended_server_id: str | None = None
    note: AdminNote | None = None
    servers: list[ServerCard]
    sources: list[SourceAvailability] = Field(default_factory=list, max_length=3)


class ProtocolSummary(Strict):
    kind: Literal["amneziawg", "xray_reality"]
    state: State
    coverage: float = Field(ge=0, le=1)
    connections: int | None = Field(ge=0)


class SoftwareComponent(Strict):
    id: Literal["amneziawg", "xray", "hiddify", "ddns", "tuning", "other"]
    name: str = Field(max_length=40)
    version: str | None = Field(default=None, max_length=32)
    note_key: str | None = Field(default=None, pattern=r"^server[.]software[.]")
    note: str | None = Field(default=None, max_length=60)


class ResourceSnapshot(Strict):
    traffic_mbps: float | None = Field(ge=0)
    cpu_percent: float | None = Field(ge=0, le=100)
    memory_percent: float | None = Field(ge=0, le=100)
    swap_percent: float | None = Field(default=None, ge=0, le=100)
    peak_connections_24h: int | None = Field(default=None, ge=0)


class ProfileStats(Strict):
    issued: int | None = Field(ge=0)
    ever_connected: int | None = Field(ge=0)
    active_24h: int | None = Field(ge=0)
    last_connection_at: datetime | None = None


class ServiceCheck(Strict):
    check: Literal["ssh", "engine", "port", "dns", "ddns"]
    ok: bool | None


class ServerDetail(ServerCard):
    protocols: list[ProtocolSummary]
    checks: list[EvidenceSummary]
    uptime_7d: float | None = Field(default=None, ge=0, le=1)
    coverage_7d: float | None = Field(default=None, ge=0, le=1)
    components: list[SoftwareComponent] = Field(default_factory=list, max_length=12)
    resources: ResourceSnapshot | None = None
    profiles: ProfileStats | None = None
    service_checks: list[ServiceCheck] = Field(default_factory=list, max_length=8)


class AttentionItem(Strict):
    severity: Literal["high", "medium", "low"]
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]+$")
    message: str = Field(max_length=240)
    server_id: str | None = None


class AdminServerDetail(ServerDetail):
    attention: list[str]
    attention_items: list[AttentionItem] = Field(default_factory=list, max_length=50)
    diagnostics: dict


class MetricPoint(Strict):
    at: datetime
    state: State
    coverage: float = Field(ge=0, le=1)
    connections: int | None = Field(ge=0)


class MetricsResponse(Strict):
    server_id: str
    period: Literal["24h", "7d"]
    coverage: float = Field(ge=0, le=1)
    points: list[MetricPoint] = Field(max_length=672)


class Event(Strict):
    id: str
    kind: Literal["state_change", "recovery", "note", "configuration", "monitoring"]
    severity: Literal["info", "warning", "critical"]
    server_id: str | None = None
    title_key: str = Field(pattern=r"^events\.")
    params: dict[str, str | float | int | bool | None]
    occurred_at: datetime


class EventPage(Strict):
    items: list[Event]
    next_cursor: str | None = None


class HelpResponse(Strict):
    step_keys: list[str] = Field(min_length=4, max_length=4)
    contact_available: bool
    contact_url: str | None = None


class ProbeSummary(Strict):
    id: str
    kind: Literal["pc", "android", "abroad", "watchdog"]
    status: Literal["active", "stale", "stopped", "revoked"]
    last_seen_at: datetime | None
    capabilities: list[str]
    agent_version: str | None = Field(default=None, max_length=64)
    route_verified: bool | None = None
    queued_reports: int | None = Field(default=None, ge=0)
    network_type: Literal["home", "cellular", "abroad", "unknown"] | None = None


class DoctorItem(Strict):
    check: Literal["servers", "probes", "collector", "storage", "bot", "https", "telegram", "queue", "backup"]
    state: Literal["ok", "warn", "fail"]
    next: str = Field(max_length=200)
    command: str | None = Field(default=None, max_length=120)


class DoctorSummary(Strict):
    result: Literal["ok", "warn", "fail"]
    items: list[DoctorItem] = Field(max_length=20)


class AdminOverview(Strict):
    attention_items: list[AttentionItem] = Field(max_length=100)
    doctor: DoctorSummary
    next_command: str | None = Field(default=None, max_length=120)


class ReadinessCheck(BaseModel):
    ok: bool
    age_seconds: int | None = Field(default=None, ge=0)


class Readiness(Strict):
    ready: bool
    checks: dict[str, ReadinessCheck]


class SessionInfo(Strict):
    role: Literal["member", "admin"]
    expires_at: datetime
