from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Collected:
    """One observation produced by a collector for one server.

    `source` is the evidence kind (`collector` for the server's own health, `human_activity` for
    aggregate member connections, or a probe kind when a collector doubles as a probe in demos);
    `metrics` follows contracts/collector-observation.schema.json for `collector` sources and the
    probe metrics shape otherwise. `probe_id` names the probe a scripted collector speaks for, so
    the check source shows up in the Mini App exactly as a real probe would. No hostnames,
    addresses or ports anywhere.
    """

    server_id: str
    source: str
    result: str  # success | failure | not_run
    observed_at: datetime
    metrics: dict = field(default_factory=dict)
    error_code: str | None = None
    network_scope: str = "all"
    full_vpn_test: bool = False
    control_internet_ok: bool | None = None
    probe_id: str | None = None


class Collector(Protocol):
    name: str

    def collect(self, now: datetime) -> list[Collected]: ...
