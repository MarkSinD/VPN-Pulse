# Collector SDK

> **Status: prototype.** Today there is one adapter, `fixture`, used by the tests. The
> interface below is what a real collector implements.

## What a collector is

A collector turns whatever a source can tell us into **observations** — small, normalised
records the evaluator understands. It never decides state itself.

```python
Observation(
    source="pc" | "mobile" | "abroad" | "collector" | "human_activity",
    result=ObservationResult.SUCCESS | FAILURE | NOT_RUN,
    observed_at=datetime,          # when the evidence was produced
    fresh_until=datetime,          # after this it cannot confirm "operational"
    full_vpn_test=bool,            # True only for a real handshake + HTTPS through the tunnel
    control_internet_ok=bool,      # the regular internet worked at the time of the check
)
```

See `src/vpnpulse/domain/models.py` and `src/vpnpulse/adapters/fixture.py`.

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
