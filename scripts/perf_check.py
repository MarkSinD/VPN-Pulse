#!/usr/bin/env python3
"""Repeatable local API, write-path and static-bundle performance budgets."""
from __future__ import annotations

import gzip
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from vpnpulse.dev.server import create_dev_app  # noqa: E402


def percentile(values, p=0.95):
    return sorted(values)[max(0, min(len(values) - 1, int(len(values) * p + 0.999) - 1))]


def timed(fn, count):
    values = []
    for _ in range(count):
        started = time.perf_counter(); response = fn(); values.append((time.perf_counter() - started) * 1000)
        if hasattr(response, "raise_for_status"): response.raise_for_status()
    return values


def main():
    app = create_dev_app(default_scenario="operational")
    api = TestClient(app, base_url="http://testserver")
    api.post("/api/v1/dev/session?role=admin").raise_for_status()
    status = api.get("/api/v1/status").json(); server_id = status["servers"][0]["id"]
    routes = {
        "GET /status": lambda: api.get("/api/v1/status"),
        "GET /servers/{id}": lambda: api.get(f"/api/v1/servers/{server_id}"),
        "GET /servers/{id}/metrics?period=7d": lambda: api.get(f"/api/v1/servers/{server_id}/metrics?period=7d"),
        "GET /events": lambda: api.get("/api/v1/events"),
    }
    rows = []
    for name, call in routes.items():
        samples = timed(call, 200); rows.append((name, statistics.median(samples), percentile(samples)))

    store = app.state.store
    _, probe = store.register_probe("pc", ["report_pc"], "perf", datetime.now(UTC))
    writes = []
    for _ in range(100):
        payload = {"report_id": str(uuid4()), "schema_version": 1, "agent_version": "perf",
                   "observed_at": datetime.now(UTC).isoformat(),
                   "network": {"type": "home", "ip_family": "ipv4", "route_verified": True},
                   "results": [{"target_id": server_id, "check": "https", "result": "success", "duration_ms": 1,
                                "not_run_reason": None, "error_code": None}]}
        started = time.perf_counter(); store.accept_report(probe, payload); writes.append((time.perf_counter() - started) * 1000)
    rows.append(("probe report write", statistics.median(writes), percentile(writes)))

    print(f"{'measurement':42} {'p50 ms':>10} {'p95 ms':>10}")
    for name, p50, p95 in rows: print(f"{name:42} {p50:10.2f} {p95:10.2f}")
    bundle = [ROOT / "docs/prototypes/mvp.html", ROOT / "web/vendor/telegram-web-app.js"]
    raw = sum(path.stat().st_size for path in bundle)
    zipped = sum(len(gzip.compress(path.read_bytes())) for path in bundle)
    print(f"bundle bytes: raw={raw} gzip={zipped}")
    failed = rows[0][2] > 300 or rows[-1][2] > 100 or zipped > 350 * 1024
    return 1 if failed else 0


if __name__ == "__main__": raise SystemExit(main())
