from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from vpnpulse.domain import Observation, ObservationResult


def load_scenario(path: Path, scenario_id: str, now: datetime) -> list[Observation]:
    scenarios = json.loads(path.read_text(encoding="utf-8"))
    scenario = next(item for item in scenarios if item["id"] == scenario_id)
    return [
        Observation(
            source=item["source"],
            result=ObservationResult(item["result"]),
            observed_at=now - timedelta(seconds=item["age"]),
            fresh_until=now - timedelta(seconds=item["age"]) + timedelta(seconds=180),
            full_vpn_test=item["full"],
            control_internet_ok=item["control"],
        )
        for item in scenario["observations"]
    ]
