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
    # when the current state began, and when the last spell of trouble ended: the screens say
    # "not working for 12 min" and "failed 40 min ago" instead of a ratio nobody can read
    state_since: datetime | None = None
    last_incident_at: datetime | None = None
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
    member_id: str | None = None
    expires_at: datetime


class AccessRequest(Strict):
    id: str
    state: Literal["pending", "approved", "denied", "cancelled"]
    created_at: datetime


class AccessGrant(Strict):
    id: str
    server_id: str
    state: Literal["active", "suspended", "revoked", "expired"]
    valid_until: datetime | None = None
    reason: str = Field(max_length=240)


class MemberAccess(Strict):
    grants: list[AccessGrant]
    request: AccessRequest | None = None


class ProfileDelivery(Strict):
    address: str
    preshared_key: str | None = None
    server_public_key: str
    endpoint: str | None = None
    dns: list[str] = Field(default_factory=list)
    extra: dict = Field(default_factory=dict)


class ProfileIssueResponse(Strict):
    profile_id: str
    address: str
    profile_state: str
    operation_id: str | None = None
    operation_state: str
    replayed: bool
    delivery: ProfileDelivery | None = None


class ProfileSummary(Strict):
    id: str
    server_id: str
    address: str
    state: str
    created_at: datetime
    first_handshake_at: datetime | None = None


class ProfileList(Strict):
    items: list[ProfileSummary]


class ProfileRevokeResponse(Strict):
    operation_id: str | None = None
    operation_state: str
    server_id: str
    profile_state: str
    replayed: bool


class ReconciliationResult(Strict):
    server_id: str
    managed: int = Field(ge=0)
    observed: int = Field(ge=0)
    missing_managed: list[str]
    unmanaged: list[str]
    ok: bool


class MemberSummary(Strict):
    id: str
    display_name: str | None = Field(default=None, max_length=160)
    username: str | None = Field(default=None, max_length=64)
    membership_state: Literal["active", "left", "banned", "unknown"]
    first_seen_at: datetime
    last_seen_at: datetime
    grants: list[AccessGrant] = Field(default_factory=list)
    access_request: AccessRequest | None = None


class MemberCoverage(Strict):
    known: int = Field(ge=0)
    active: int = Field(ge=0)
    left: int = Field(ge=0)
    banned: int = Field(ge=0)
    unknown: int = Field(ge=0)


class AdminMembers(Strict):
    coverage: MemberCoverage
    items: list[MemberSummary]


class ProbeTarget(Strict):
    id: str
    checks: list[Literal["control_internet", "handshake", "https", "dns", "tcp"]]


class ProbeConfig(Strict):
    schema_version: Literal[1] = 1
    interval_seconds: int = Field(ge=60, le=3600)
    targets: list[ProbeTarget]
