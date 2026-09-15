"""FixtureCollector — a scripted world that changes over time (demo mode, tests).

It plays the demo scenarios of fixtures/ui/scenarios.json as phases: for the current phase it
emits, per server, the collector payload (connections, resources, components, service checks), the
member-connection evidence when the scenario says people confirm the server, and the probe
evidence (pc / mobile / abroad) the scenario describes. Two consecutive runs inside a failing phase
therefore confirm an outage exactly like two real PC tests would.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from vpnpulse.collectors.base import Collected
from vpnpulse.dev.scenarios import KIND_PROBE, KINDS, ScenarioCatalog
from vpnpulse.dev.seed import _collector_payload

RESULT_OF = {"ok": "success", "fail": "failure", "partial": "failure", "unknown": "not_run"}
SCOPE_OF = {"pc": "country", "mobile": "country", "abroad": "abroad"}
DEFAULT_PHASES = (("operational", 10), ("degraded", 5), ("unavailable", 10), ("operational", 15))


@dataclass(frozen=True)
class Phase:
    scenario: str
    minutes: int


class FixtureCollector:
    name = "fixture"

    def __init__(self, catalog: ScenarioCatalog, phases: tuple[tuple[str, int], ...] = DEFAULT_PHASES, *, start: datetime | None = None, probes: bool = True, speed: float = 1.0) -> None:
        self.catalog = catalog
        self.phases = [Phase(s, m) for s, m in phases]
        self.start = start
        self.probes = probes
        self.speed = speed  # >1 plays the phases faster than the clock (demo installs)
        self.cycle = sum(p.minutes for p in self.phases)

    def scenario_at(self, now: datetime) -> str:
        if self.start is None:
            self.start = now
        elapsed = ((now - self.start).total_seconds() * self.speed / 60) % self.cycle
        for phase in self.phases:
            if elapsed < phase.minutes:
                return phase.scenario
            elapsed -= phase.minutes
        return self.phases[-1].scenario

    def collect(self, now: datetime) -> list[Collected]:
        scenario_id = self.scenario_at(now)
        sc = self.catalog.build(scenario_id, now)
        out: list[Collected] = []
        for s in sc.servers:
            payload = _collector_payload(s, now, with_details=True)
            slot = int((now.hour * 60 + now.minute) // 30) % 48
            value = s["series"][slot]
            if value is not None:
                payload["connections"]["amneziawg"] = int(math.floor(value + 0.5))
            out.append(Collected(s["id"], "collector", "success", now, payload))
            if s.get("confirmedBy") in ("humans", "both"):
                out.append(Collected(s["id"], "human_activity", "success", now, {"connections": payload["connections"]}))
            if not self.probes:
                continue
            for k in KINDS:
                if sc.presence[k] == "none":
                    continue
                src = s["sources"][k]
                if src.get("age") is None:
                    continue
                observed = now - timedelta(seconds=5)
                out.append(Collected(
                    s["id"], k, RESULT_OF[src["r"]], observed,
                    {"via_server_id": s.get("abroadFrom")} if k == "abroad" else {"checks": {"handshake": RESULT_OF[src["r"]], "https": RESULT_OF[src["r"]]} if k == "pc" else {"dns": RESULT_OF[src["r"]]}},
                    error_code=str(src.get("detailKey", "")).split(".")[-1] if src["r"] != "ok" else None,
                    network_scope=SCOPE_OF[k], full_vpn_test=(k == "pc"), control_internet_ok=True if k == "pc" else None,
                    probe_id=f"fixture-{KIND_PROBE[k]}",
                ))
        return out
