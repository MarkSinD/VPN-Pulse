"""HTTP layer of VPN Pulse (contracts/openapi.yaml).

Reads go through a ReadModel (SQLite in production, demo scenarios in the dev server); writes go
through SqliteStore. The app itself keeps no state between requests, so it can restart at any
moment and several workers can share one database file.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

import jsonschema
from fastapi import Cookie, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from vpnpulse.api import schemas
from vpnpulse.api.read_model import ReadModel, ReadModelUnavailable, StatusOnlyReadModel, pick_language
from vpnpulse.api.security import RateLimiter, client_address
from vpnpulse.auth import AuthenticationError, MembershipChecker, validate_telegram_init_data
from vpnpulse.storage.database import apply_migrations, connect
from vpnpulse.storage.store import SqliteStore, sync_servers


class SessionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    init_data: str = Field(min_length=1, max_length=8192)


class AnalyticsBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: list[dict] = Field(min_length=1, max_length=50)


class EnrollmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["pc", "android", "abroad", "watchdog"]
    capabilities: list[Literal["report_pc", "report_mobile", "report_abroad", "read_watchdog"]] = Field(min_length=1)


class ProbeEnrollInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=128)
    agent_version: str = Field(max_length=64)
    schema_version: Literal[1] = 1


class ReportNetwork(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["home", "cellular", "abroad", "unknown"]
    ip_family: Literal["ipv4", "ipv6", "dual", "unknown"]
    route_verified: bool


class ReportResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,63}$")
    check: Literal["control_internet", "handshake", "https", "dns", "tcp"]
    result: Literal["success", "failure", "not_run"]
    duration_ms: int | None = Field(ge=0, le=120000)
    not_run_reason: Literal["no_network", "no_cellular", "route_unverified", "stopped", "unsupported"] | None = None
    error_code: str | None = Field(default=None, max_length=80)


class ProbeReportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_id: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")
    schema_version: Literal[1] = 1
    agent_version: str = Field(max_length=64)
    observed_at: datetime
    network: ReportNetwork
    results: list[ReportResult] = Field(min_length=1, max_length=20)


class AdminNoteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    server_id: str | None = None
    text: str = Field(min_length=1, max_length=500)
    expires_at: datetime | None = None

    @field_validator("text")
    @classmethod
    def safe_text(cls, value: str) -> str:
        if any(ord(char) < 32 and char not in "\n\t" for char in value):
            raise ValueError("control characters are not allowed")
        return value


def _migrations_dir() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "migrations"
        if (candidate / "0001_initial.sql").exists():
            return candidate
    raise FileNotFoundError("migrations/ not found; pass a store to create_app")


def create_app(
    *,
    bot_token: str,
    membership: MembershipChecker,
    analytics_schema: Path,
    status_provider: Callable[[str], dict] | None = None,
    read_model: ReadModel | None = None,
    store: SqliteStore | None = None,
    config: dict | None = None,
    contact_url: str | None = None,
    default_language: str = "ru",
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    limits: bool = True,
) -> FastAPI:
    """Build the API. Reads: `read_model` (or the legacy status-only `status_provider`); writes: `store`.

    Without a store an in-memory SQLite database is created — the same code path as production,
    just not persistent. Real deployments pass a store over the shared database file.
    """
    if read_model is None:
        if status_provider is None:
            raise ValueError("create_app needs read_model or status_provider")
        read_model = StatusOnlyReadModel(status_provider, contact_url)
    if store is None:
        connection = connect(":memory:")
        apply_migrations(connection, _migrations_dir())
        store = SqliteStore(connection, analytics_schema=analytics_schema, config=config, pepper=bot_token, now=now)
    if config and config.get("servers"):
        sync_servers(store.db, config, now())  # rows that notes, reports and observations reference
    app = FastAPI(title="VPN Pulse API", version="1.5.1")
    limiter = RateLimiter(now)
    # sessions: members behind one carrier NAT open the app together during an outage — 60, not 20
    limited = {"/api/v1/sessions": 60, "/api/v1/probe/enroll": 20,
               "/api/v1/probe/reports": 120, "/api/v1/analytics/events:batch": 60}

    def raw_problem(request: Request, status: int, code: str, headers: dict | None = None):
        return JSONResponse(status_code=status, media_type="application/problem+json", headers=headers,
                            content={"type": f"/problems/{code.lower()}", "title": code.replace("_", " ").title(),
                                     "status": status, "code": code,
                                     "trace_id": request.headers.get("x-request-id") or uuid4().hex})

    @app.middleware("http")
    async def request_guards(request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH"}:
            origin = request.headers.get("origin")
            expected = f"{request.url.scheme}://{request.headers.get('host')}"
            if origin and origin.rstrip("/") != expected.rstrip("/"):
                return raw_problem(request, 403, "ORIGIN_REJECTED")
            length = request.headers.get("content-length")
            if length and length.isdigit() and int(length) > 65_536:
                return raw_problem(request, 413, "BODY_TOO_LARGE")
            body = await request.body()
            if len(body) > 65_536:
                return raw_problem(request, 413, "BODY_TOO_LARGE")
            async def receive():
                return {"type": "http.request", "body": body, "more_body": False}
            request._receive = receive
        limit = limited.get(request.url.path) if limits and request.method == "POST" else None
        if limit:
            allowed, retry = limiter.allow(request.url.path, client_address(request), limit)
            if not allowed:
                return raw_problem(request, 429, "RATE_LIMITED", {"Retry-After": str(retry)})
        return await call_next(request)

    @app.exception_handler(ReadModelUnavailable)
    async def read_model_unavailable(request: Request, error: ReadModelUnavailable):
        return await problem_details(request, HTTPException(status_code=503, detail={"code": error.code}))

    @app.exception_handler(HTTPException)
    async def problem_details(request: Request, error: HTTPException):
        detail = error.detail if isinstance(error.detail, dict) else {}
        code = str(detail.get("code", "HTTP_ERROR"))
        trace_id = request.headers.get("x-request-id") or uuid4().hex
        return JSONResponse(
            status_code=error.status_code,
            media_type="application/problem+json",
            content={
                "type": f"/problems/{code.lower()}",
                "title": code.replace("_", " ").title(),
                "status": error.status_code,
                "code": code,
                "trace_id": trace_id,
            },
        )

    def require_session(token: str | None, role: str | None = None):
        session = store.get_session(token, now())
        if session is None:
            raise HTTPException(status_code=401, detail={"code": "SESSION_EXPIRED"})
        if role and session.identity.role != role:
            raise HTTPException(status_code=403, detail={"code": "ROLE_REQUIRED"})
        return session

    def lang_of(request: Request) -> str:
        return pick_language(request.headers.get("accept-language"), default_language)

    def trace_of(request: Request) -> str:
        return request.headers.get("x-request-id") or uuid4().hex

    def require_probe(authorization: str | None):
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail={"code": "PROBE_TOKEN_REQUIRED"})
        probe = store.probe_by_token(authorization.removeprefix("Bearer "))
        if probe is None:
            raise HTTPException(status_code=401, detail={"code": "PROBE_TOKEN_INVALID"})
        return probe

    def public_probe(probe: dict) -> dict:
        return {key: value for key, value in probe.items() if not key.startswith("_")}

    # ---------- health ----------
    @app.get("/api/v1/health/live")
    def live():
        return {"alive": True}

    @app.get("/api/v1/health/ready", response_model=schemas.Readiness)
    def ready():
        return read_model.readiness()

    # ---------- sessions ----------
    @app.post("/api/v1/sessions", status_code=204)
    def create_session(payload: SessionInput, response: Response):
        try:
            identity = validate_telegram_init_data(payload.init_data, bot_token=bot_token, membership=membership, now=now())
        except AuthenticationError as error:
            status = 403 if str(error) == "MEMBERSHIP_REQUIRED" else 401
            raise HTTPException(status_code=status, detail={"code": str(error)}) from error
        session = store.create_session(identity, now())
        response.set_cookie("vpnpulse_session", session.token, httponly=True, secure=True, samesite="lax", max_age=1800, path="/api/v1")

    @app.get("/api/v1/sessions/current", response_model=schemas.SessionInfo)
    def current_session(vpnpulse_session: str | None = Cookie(default=None)):
        session = require_session(vpnpulse_session)
        return {"role": session.identity.role, "expires_at": session.expires_at.isoformat()}

    @app.delete("/api/v1/sessions/current", status_code=204)
    def delete_session(vpnpulse_session: str | None = Cookie(default=None)):
        store.revoke_session(vpnpulse_session, now())

    # ---------- member reads ----------
    @app.get("/api/v1/status", response_model=schemas.StatusResponse)
    def status(request: Request, vpnpulse_session: str | None = Cookie(default=None)):
        session = require_session(vpnpulse_session)
        return read_model.status(session.identity.role, lang_of(request))

    @app.get("/api/v1/servers/{server_id}", response_model=schemas.ServerDetail)
    def server(server_id: str, request: Request, vpnpulse_session: str | None = Cookie(default=None)):
        session = require_session(vpnpulse_session)
        detail = read_model.server(server_id, session.identity.role, lang_of(request))
        if detail is None:
            raise HTTPException(status_code=404, detail={"code": "SERVER_NOT_FOUND"})
        return detail

    @app.get("/api/v1/servers/{server_id}/metrics", response_model=schemas.MetricsResponse)
    def server_metrics(server_id: str, period: str = "24h", vpnpulse_session: str | None = Cookie(default=None)):
        require_session(vpnpulse_session)
        if period not in {"24h", "7d"}:
            raise HTTPException(status_code=400, detail={"code": "PERIOD_INVALID"})
        payload = read_model.metrics(server_id, period)
        if payload is None:
            raise HTTPException(status_code=404, detail={"code": "SERVER_NOT_FOUND"})
        return payload

    @app.get("/api/v1/events", response_model=schemas.EventPage)
    def events(request: Request, filter: str = "all", cursor: str | None = None, limit: int = 50, vpnpulse_session: str | None = Cookie(default=None)):
        session = require_session(vpnpulse_session)
        if filter not in {"all", "problems", "notes"} or not 1 <= limit <= 100:
            raise HTTPException(status_code=400, detail={"code": "EVENT_QUERY_INVALID"})
        return read_model.events(filter, cursor, limit, session.identity.role, lang_of(request))

    @app.get("/api/v1/help", response_model=schemas.HelpResponse)
    def help_content(request: Request, vpnpulse_session: str | None = Cookie(default=None)):
        require_session(vpnpulse_session)
        return read_model.help(lang_of(request))

    # ---------- admin ----------
    @app.get("/api/v1/admin/servers/{server_id}", response_model=schemas.AdminServerDetail)
    def admin_server(server_id: str, request: Request, vpnpulse_session: str | None = Cookie(default=None)):
        require_session(vpnpulse_session, "admin")
        detail = read_model.admin_server(server_id, lang_of(request))
        if detail is None:
            raise HTTPException(status_code=404, detail={"code": "SERVER_NOT_FOUND"})
        return detail

    @app.get("/api/v1/admin/probes", response_model=list[schemas.ProbeSummary])
    def admin_probes(vpnpulse_session: str | None = Cookie(default=None)):
        require_session(vpnpulse_session, "admin")
        # probes known to the read model first (demo scenarios), then the ones enrolled through the API
        listed = list(read_model.admin_probes())
        seen = {probe["id"] for probe in listed}
        for probe in store.list_probes():
            if probe["id"] not in seen:
                listed.append(probe)
        return listed

    @app.get("/api/v1/admin/overview", response_model=schemas.AdminOverview)
    def admin_overview(request: Request, vpnpulse_session: str | None = Cookie(default=None)):
        require_session(vpnpulse_session, "admin")
        return read_model.admin_overview(lang_of(request))

    @app.post("/api/v1/admin/probe-enrollments", status_code=201)
    def create_enrollment(payload: EnrollmentInput, request: Request, vpnpulse_session: str | None = Cookie(default=None)):
        session = require_session(vpnpulse_session, "admin")
        code, expires_at = store.create_enrollment(payload.kind, list(payload.capabilities), session.token, now())
        store.audit(actor=session.token, role="admin", action="probe.enroll_code", target_type="probe", target_id=payload.kind, trace_id=trace_of(request), now=now())
        return {"code": code, "expires_at": expires_at}

    @app.post("/api/v1/admin/probes/{probe_id}/revoke", status_code=204)
    def revoke_probe(probe_id: str, request: Request, vpnpulse_session: str | None = Cookie(default=None)):
        session = require_session(vpnpulse_session, "admin")
        revoked = store.revoke_probe(probe_id, now())
        if not revoked:
            fallback = getattr(read_model, "revoke_probe", None)
            revoked = bool(fallback and fallback(probe_id))
        if not revoked:
            raise HTTPException(status_code=404, detail={"code": "PROBE_NOT_FOUND"})
        store.audit(actor=session.token, role="admin", action="probe.revoke", target_type="probe", target_id=probe_id, trace_id=trace_of(request), now=now())

    @app.put("/api/v1/admin/note", response_model=schemas.AdminNote)
    def put_note(payload: AdminNoteInput, request: Request, vpnpulse_session: str | None = Cookie(default=None)):
        session = require_session(vpnpulse_session, "admin")
        if payload.server_id and not any(s["id"] == payload.server_id for s in (config or {}).get("servers", [])):
            raise HTTPException(status_code=404, detail={"code": "SERVER_NOT_FOUND"})
        note = store.put_note(payload.text, payload.expires_at, payload.server_id, "admin", now())
        store.audit(actor=session.token, role="admin", action="note.put", target_type="note", target_id=note["id"], details={"length": len(payload.text)}, trace_id=trace_of(request), now=now())
        return note

    @app.delete("/api/v1/admin/note", status_code=204)
    def delete_note(request: Request, vpnpulse_session: str | None = Cookie(default=None)):
        session = require_session(vpnpulse_session, "admin")
        store.delete_note(now())
        store.audit(actor=session.token, role="admin", action="note.delete", target_type="note", target_id="active", trace_id=trace_of(request), now=now())

    # ---------- probes ----------
    @app.post("/api/v1/probe/enroll", status_code=201)
    def enroll_probe(payload: ProbeEnrollInput):
        enrollment = store.consume_enrollment(payload.code, now())
        if enrollment is None:
            raise HTTPException(status_code=401, detail={"code": "ENROLLMENT_INVALID"})
        if enrollment["kind"] == "abroad" and not enrollment.get("via_server_id"):
            raise HTTPException(status_code=400, detail={"code": "ABROAD_VIA_REQUIRED"})
        token, probe = store.register_probe(enrollment["kind"], enrollment["capabilities"], payload.agent_version, now(), enrollment.get("via_server_id"))
        return {"token": token, "probe": public_probe(probe), "config": store.probe_config(probe["kind"], probe.get("via_server_id"))}

    @app.get("/api/v1/probe/config", response_model=schemas.ProbeConfig)
    def probe_config(authorization: str | None = Header(default=None)):
        probe = require_probe(authorization)
        return store.probe_config(probe["kind"], probe.get("via_server_id"))

    @app.post("/api/v1/probe/reports", status_code=202)
    def probe_report(payload: ProbeReportInput, authorization: str | None = Header(default=None)):
        probe = require_probe(authorization)
        try:
            duplicate, _written = store.accept_report(probe, payload.model_dump(mode="json"), now())
        except ValueError as error:
            raise HTTPException(status_code=409, detail={"code": "REPORT_ID_CONFLICT"}) from error
        return {"report_id": payload.report_id, "accepted": True, "duplicate": duplicate}

    # ---------- analytics ----------
    @app.post("/api/v1/analytics/events:batch", status_code=202)
    def analytics_batch(payload: AnalyticsBatch, vpnpulse_session: str | None = Cookie(default=None)):
        require_session(vpnpulse_session)
        try:
            accepted = store.analytics.accept_batch(payload.events, now())
        except jsonschema.ValidationError as error:
            raise HTTPException(status_code=400, detail={"code": "ANALYTICS_EVENT_INVALID"}) from error
        return {"accepted": accepted}

    app.state.store = store
    app.state.read_model = read_model
    app.state.rate_limiter = limiter
    return app
