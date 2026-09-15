# Collector SDK

> **Status: interface fixed, real adapters pending.** Today there is one collector,
> `FixtureCollector` (`src/vpnpulse/collectors/fixture.py`), which plays the demo scenarios for
> `vpn-pulse run --demo` and the tests. The interface below is what a real collector implements.

## What a collector is

A collector turns whatever a source can tell us into **observations** — small, normalised
records the evaluator understands. It never decides state itself.

```python
class Collector(Protocol):
    name: str
    def collect(self, now: datetime) -> list[Collected]: ...

Collected(
    server_id="primary-vpn",                       # an id from config.yaml; unknown ids are dropped
    source="collector" | "human_activity",         # probes report through the API instead
    result="success" | "failure" | "not_run",
    observed_at=datetime,                          # when the evidence was produced
    metrics={...},                                 # the payload below for `collector` sources
    error_code="SSH_TIMEOUT" | None,               # a code, never a message with a host in it
    network_scope="all",
)
```

The loop (`vpnpulse.pipeline`) stores each `Collected` as an `observations` row with
`fresh_until = observed_at + freshness_seconds`, links it to the `collection_runs` row of that
run, and evaluates the fresh rows of every server. A collector that raises marks the run
`partial` (or `error` when nothing was collected) and the loop goes on. See
`src/vpnpulse/collectors/base.py` and `src/vpnpulse/domain/models.py`.

## What a collector writes

One `collector` observation per server per run. Its `metrics_json` follows
[`contracts/collector-observation.schema.json`](../contracts/collector-observation.schema.json):
connection counts per protocol, resources, aggregate profile counts, software components, service
checks, admin-only attention items (bilingual) and structured diagnostics. Every block is optional —
a partial collector reports what it knows and nothing else is invented downstream. The read model
takes the newest payload for the Server screen and the counts of every payload for the charts.

## Rules for a collector

- Read-only. No writes, no restarts, no configuration changes on the observed system.
- Aggregate only. Counts, ages and booleans — never peer keys or per-person data.
- Redacted. Hostnames, addresses and ports do not appear in observations, events or logs.
- Honest about coverage: return `NOT_RUN` with a reason instead of inventing a value.
- Time-bounded: respect the deadline; a late answer is history, not the present.

## Planned adapters

`awg-host`, `awg-docker`, `hiddify` (see [connect-server.md](connect-server.md)). Contributions
for other VPN stacks are welcome — open an issue describing the read-only data the stack can
expose.
