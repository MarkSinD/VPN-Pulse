from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class State(StrEnum):
    OPERATIONAL = "operational"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class ObservationResult(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    NOT_RUN = "not_run"


@dataclass(frozen=True, slots=True)
class Observation:
    source: str
    result: ObservationResult
    observed_at: datetime
    fresh_until: datetime
    full_vpn_test: bool = False
    control_internet_ok: bool | None = None
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class Evaluation:
    state: State
    reason_code: str
    observed_at: datetime | None
    fresh_until: datetime | None
    evidence_count: int
    coverage: float


@dataclass(frozen=True, slots=True)
class ServerCandidate:
    server_id: str
    evaluation: Evaluation
    load_score: float | None
    complete_protocol_coverage: bool
    priority: int = 0
