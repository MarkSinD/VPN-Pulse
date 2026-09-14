from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
import secrets
from uuid import uuid4

import jsonschema
from fastapi import Cookie, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from vpnpulse.analytics import AnalyticsRegistry
from vpnpulse.auth import (
    AuthenticationError,
    InMemorySessionStore,
    MembershipChecker,
    validate_telegram_init_data,
)


class SessionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    init_data: str = Field(min_length=1, max_length=8192)


class AnalyticsBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: list[dict] = Field(min_length=1, max_length=50)


class EnrollmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str
    capabilities: list[str] = Field(min_length=1)


class ProbeEnrollInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    agent_version: str = Field(max_length=64)
    schema_version: int = 1


class ProbeReportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_id: str
    schema_version: int = 1
    agent_version: str = Field(max_length=64)
    observed_at: datetime
    network: dict
    results: list[dict] = Field(min_length=1, max_length=20)


class AdminNoteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    server_id: str | None = None
    text: str = Field(min_length=1, max_length=500)
    expires_at: datetime | None = None


def create_app(
    *,
    bot_token: str,
    membership: MembershipChecker,
    status_provider: Callable[[str], dict],
    analytics_schema: Path,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> FastAPI:
    app = FastAPI(title="VPN Pulse API", version="1.0.0")
    sessions = InMemorySessionStore()
    analytics = AnalyticsRegistry(analytics_schema)
    enrollments: dict[str, dict] = {}
    probes: dict[str, dict] = {}
    accepted_reports: set[str] = set()
    active_note: dict | None = None

    @app.exception_handler(HTTPException)
    async def problem_details(request: Request, error: HTTPException):
        detail = error.detail if isinstance(error.detail, dict) else {}
        code = str(detail.get("code", "HTTP_ERROR"))
        trace_id = request.headers.get("x-request-id") or __import__("uuid").uuid4().hex
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
        session = sessions.get(token, now())
        if session is None:
            raise HTTPException(status_code=401, detail={"code": "SESSION_EXPIRED"})
        if role and session.identity.role != role:
            raise HTTPException(status_code=403, detail={"code": "ROLE_REQUIRED"})
        return session

    def require_probe(authorization: str | None):
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail={"code": "PROBE_TOKEN_REQUIRED"})
        token = authorization.removeprefix("Bearer ")
        probe = probes.get(token)
        if probe is None or probe.get("status") == "revoked":
            raise HTTPException(status_code=401, detail={"code": "PROBE_TOKEN_INVALID"})
        return probe

    @app.get("/api/v1/health/live")
    def live():
        return {"alive": True}

    @app.post("/api/v1/sessions", status_code=204)
    def create_session(payload: SessionInput, response: Response):
        try:
            identity = validate_telegram_init_data(
                payload.init_data,
                bot_token=bot_token,
                membership=membership,
                now=now(),
            )
        except AuthenticationError as error:
            status = 403 if str(error) == "MEMBERSHIP_REQUIRED" else 401
            raise HTTPException(status_code=status, detail={"code": str(error)}) from error
        session = sessions.create(identity, now())
        response.set_cookie(
            "vpnpulse_session",
            session.token,
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=1800,
            path="/api/v1",
        )

    @app.delete("/api/v1/sessions/current", status_code=204)
    def delete_session(vpnpulse_session: str | None = Cookie(default=None)):
        sessions.revoke(vpnpulse_session)

    @app.get("/api/v1/status")
    def status(vpnpulse_session: str | None = Cookie(default=None)):
        session = require_session(vpnpulse_session)
        return status_provider(session.identity.role)

    @app.get("/api/v1/servers/{server_id}")
    def server(server_id: str, vpnpulse_session: str | None = Cookie(default=None)):
        session = require_session(vpnpulse_session)
        status_payload = status_provider(session.identity.role)
        card = next((item for item in status_payload.get("servers", []) if item["id"] == server_id), None)
        if card is None:
            raise HTTPException(status_code=404, detail={"code": "SERVER_NOT_FOUND"})
        return {**card, "protocols": [], "checks": card.get("sources", [])}

    @app.get("/api/v1/servers/{server_id}/metrics")
    def server_metrics(
        server_id: str,
        period: str = "24h",
        vpnpulse_session: str | None = Cookie(default=None),
    ):
        require_session(vpnpulse_session)
        if period not in {"24h", "7d"}:
            raise HTTPException(status_code=400, detail={"code": "PERIOD_INVALID"})
        return {"server_id": server_id, "period": period, "coverage": 0, "points": []}

    @app.get("/api/v1/events")
    def events(
        filter: str = "all",
        cursor: str | None = None,
        limit: int = 50,
        vpnpulse_session: str | None = Cookie(default=None),
    ):
        require_session(vpnpulse_session)
        if filter not in {"all", "problems", "notes"} or not 1 <= limit <= 100:
            raise HTTPException(status_code=400, detail={"code": "EVENT_QUERY_INVALID"})
        return {"items": [], "next_cursor": None}

    @app.get("/api/v1/help")
    def help_content(vpnpulse_session: str | None = Cookie(default=None)):
        require_session(vpnpulse_session)
        return {
            "step_keys": ["help.checkStatus", "help.restartVpn", "help.useRecommended", "help.useBackup"],
            "contact_available": True,
        }

    @app.get("/api/v1/admin/servers/{server_id}")
    def admin_server(server_id: str, vpnpulse_session: str | None = Cookie(default=None)):
        session = require_session(vpnpulse_session, "admin")
        status_payload = status_provider(session.identity.role)
        card = next((item for item in status_payload.get("servers", []) if item["id"] == server_id), None)
        if card is None:
            raise HTTPException(status_code=404, detail={"code": "SERVER_NOT_FOUND"})
        return {**card, "protocols": [], "checks": card.get("sources", []), "attention": [], "diagnostics": {}}

    @app.get("/api/v1/admin/probes")
    def admin_probes(vpnpulse_session: str | None = Cookie(default=None)):
        require_session(vpnpulse_session, "admin")
        public_keys = {"id", "kind", "status", "last_seen_at", "capabilities"}
        return [{key: value for key, value in probe.items() if key in public_keys} for probe in probes.values()]

    @app.post("/api/v1/admin/probe-enrollments", status_code=201)
    def create_enrollment(payload: EnrollmentInput, vpnpulse_session: str | None = Cookie(default=None)):
        require_session(vpnpulse_session, "admin")
        code = secrets.token_urlsafe(24)
        expires_at = now() + timedelta(minutes=10)
        enrollments[code] = {"kind": payload.kind, "capabilities": payload.capabilities, "expires_at": expires_at}
        return {"code": code, "expires_at": expires_at}

    @app.post("/api/v1/admin/probes/{probe_id}/revoke", status_code=204)
    def revoke_probe(probe_id: str, vpnpulse_session: str | None = Cookie(default=None)):
        require_session(vpnpulse_session, "admin")
        probe = next((item for item in probes.values() if item["id"] == probe_id), None)
        if probe is None:
            raise HTTPException(status_code=404, detail={"code": "PROBE_NOT_FOUND"})
        probe["status"] = "revoked"

    @app.put("/api/v1/admin/note")
    def put_note(payload: AdminNoteInput, vpnpulse_session: str | None = Cookie(default=None)):
        nonlocal active_note
        require_session(vpnpulse_session, "admin")
        active_note = {"id": str(uuid4()), **payload.model_dump(mode="json"), "created_at": now().isoformat()}
        return active_note

    @app.delete("/api/v1/admin/note", status_code=204)
    def delete_note(vpnpulse_session: str | None = Cookie(default=None)):
        nonlocal active_note
        require_session(vpnpulse_session, "admin")
        active_note = None

    @app.post("/api/v1/probe/enroll", status_code=201)
    def enroll_probe(payload: ProbeEnrollInput):
        enrollment = enrollments.pop(payload.code, None)
        if enrollment is None or enrollment["expires_at"] <= now():
            raise HTTPException(status_code=401, detail={"code": "ENROLLMENT_INVALID"})
        token = secrets.token_urlsafe(32)
        probe_id = f"{enrollment['kind']}-{uuid4().hex[:12]}"
        probe = {
            "id": probe_id,
            "kind": enrollment["kind"],
            "status": "active",
            "last_seen_at": None,
            "capabilities": enrollment["capabilities"],
            "agent_version": payload.agent_version,
        }
        probes[token] = probe
        public_keys = {"id", "kind", "status", "last_seen_at", "capabilities"}
        public_probe = {key: value for key, value in probe.items() if key in public_keys}
        return {"token": token, "probe": public_probe, "config": {"schema_version": 1, "interval_seconds": 60, "targets": []}}

    @app.get("/api/v1/probe/config")
    def probe_config(authorization: str | None = Header(default=None)):
        require_probe(authorization)
        return {"schema_version": 1, "interval_seconds": 60, "targets": []}

    @app.post("/api/v1/probe/reports", status_code=202)
    def probe_report(payload: ProbeReportInput, authorization: str | None = Header(default=None)):
        probe = require_probe(authorization)
        duplicate = payload.report_id in accepted_reports
        accepted_reports.add(payload.report_id)
        probe["last_seen_at"] = now().isoformat()
        return {"report_id": payload.report_id, "accepted": True, "duplicate": duplicate}

    @app.post("/api/v1/analytics/events:batch", status_code=202)
    def analytics_batch(payload: AnalyticsBatch, vpnpulse_session: str | None = Cookie(default=None)):
        require_session(vpnpulse_session)
        try:
            accepted = analytics.accept_batch(payload.events)
        except jsonschema.ValidationError as error:
            raise HTTPException(status_code=400, detail={"code": "ANALYTICS_EVENT_INVALID"}) from error
        return {"accepted": accepted}

    @app.get("/api/v1/health/ready")
    def ready():
        return {
            "ready": True,
            "checks": {
                "database": {"ok": True, "age_seconds": None},
                "collector": {"ok": True, "age_seconds": 0},
                "bot": {"ok": True, "age_seconds": 0},
            },
        }

    app.state.sessions = sessions
    app.state.analytics = analytics
    return app
