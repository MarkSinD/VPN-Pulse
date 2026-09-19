# Collector SDK

> **Status: two collectors.** `FixtureCollector` (`src/vpnpulse/collectors/fixture.py`) plays the
> demo scenarios for `vpn-pulse run --demo` and the tests; `SshCollector`
> (`src/vpnpulse/collectors/ssh.py`) reads a real server through the read-only helper in
> `deploy/helper/` — `awg-host` and `awg-docker` today, see [connect-server.md](connect-server.md).
> The interface below is what any collector implements.

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

## The SSH collector and its helper

`SshCollector` runs one `ssh` per server per run (batch mode, strict host-key checking against a
pinned file, a key made for that server only, a whole-call deadline) whose forced command on the
server is `deploy/helper/vpn-pulse-helper`. The helper answers with one JSON document:

| Block | What it holds | Where it comes from |
|---|---|---|
| `engine` | `ok` (the interface could be read), `listening` (a UDP socket is bound to its port) | `sudo vpn-pulse-dump`, the only privileged step |
| `peers` | `count`, `handshake_ages` (seconds; `-1` = never), `rx_bytes`, `tx_bytes` | the same dump, keys/endpoints/allowed IPs stripped before printing |
| `system` | cpu, memory, swap, disk percent; uptime; running kernel, installed kernels, DKMS-built kernels; AWG version; congestion control and qdisc | `/proc`, `df`, `dkms status`, `/lib/modules`, `tc` |
| `dns` | `configured`, `resolves`, `matches_public_ip` — booleans only | `getent` against `DOMAIN` from the helper's config |
| `errors` | codes such as `DUMP_FAILED` | — |

From that the collector derives the contract payload: `connections.amneziawg` = peers whose
handshake is younger than `freshness_seconds`; `profiles.issued / ever_connected / active_24h /
last_connection_at`; `resources.traffic_mbps` as the byte delta between two runs; `components`
(AmneziaWG with the host/container note, the congestion control as *tuning*, DDNS); `service_checks`
(`ssh`, `engine`, `port`, and `dns`/`ddns` when a domain is configured); admin `attention` items —
`KERNEL_MODULE_MISMATCH` (a newer kernel without the module), `ENGINE_UNREADABLE`,
`DISK_PRESSURE`, `DDNS_MISMATCH`, `TUNING_LOST` — with RU/EN texts from `i18n/`; and
`diagnostics`. When at least one peer handshaked within the freshness window the collector also
writes a `human_activity` observation: members proving the server works. A failed call becomes a
`collector` observation with `result = failure` and a code (`SSH_TIMEOUT`, `SSH_UNREACHABLE`,
`SSH_AUTH_FAILED`, `SSH_HOST_KEY_MISMATCH`, `HELPER_FAILED`, `HELPER_INVALID_ANSWER`) — never a
host in it.

## Planned adapters

`hiddify` (Xray connections through the panel's read-only data). Contributions for other VPN
stacks are welcome — open an issue describing the read-only data the stack can expose.
