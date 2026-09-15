# Architecture

## Processes

```
 INSIDE THE USERS' COUNTRY                     MONITORING HOST (one small VPS)
 ┌──────────────────────────┐                  ┌──────────────────────────────────────────────┐
 │ 💻 PC probe (planned)     │  HTTPS + token   │  API (FastAPI)  ◄── Telegram initData ── Mini App │
 │  isolated VPN tunnels to │ ───────────────► │   │                                          │
 │  each server + HTTPS     │  reports, queue  │   ▼                                          │
 │  through the tunnel      │                  │  Core: SQLite · evaluator · debounce · freshness│
 ├──────────────────────────┤                  │   │                    ▲                     │
 │ 📶 Android probe (planned)│  HTTPS + token   │   │                    │ collector (read-only │
 │  excluded from VPN,      │ ───────────────► │   │                    │  SSH helper): peers, │
 │  bound to cellular:      │                  │   ▼                    │  counters, checks    │
 │  DNS + reachability      │                  │  Bot ──► Telegram group (state changes)      │
 └──────────────────────────┘                  │      ──► administrator (diagnostics, /note)  │
                                               └───────┬──────────────────┬───────────────────┘
                                                       │                  │
            ┌──────────────┐   ┌──────────────┐        ▼                  ▼
            │ VPN server A │   │ VPN server B │   … your servers, each also running a 🌍
            └──────────────┘   └──────────────┘     cross-check probe against the others (planned)
                                               watchdog on a second host: heartbeat of API, collector, bot, queue
```

## Modules (`src/vpnpulse/`)

| Module | Responsibility | Status |
|---|---|---|
| `config.py` | load and validate `config.yaml`, redact secrets from logs | done |
| `storage/` | SQLite schema (`migrations/0001_initial.sql`), `SqliteStore` (all API writes), `SqliteReadModel` (all API reads), `StateRepository` + `NotificationWorker` (snapshots, transitions, queue) | done |
| `domain/evaluator.py` | evidence → state per server × protocol × network; freshness; two confirmations; recommendation | done, fixture-tested |
| `pipeline.py` | the loop: collect → evaluate → snapshots → transitions → events → notification queue; hourly sweep and aggregates | done, deterministic tests |
| `collectors/` | `Collected` / `Collector` interface and `FixtureCollector` (demo); `awg-host` / `awg-docker` / `hiddify` planned | fixture only |
| `notify.py` | message texts from `i18n/*.json` (public names only); console, fake and Telegram Bot API senders | done (Telegram not yet exercised against a real bot) |
| `cli/` | `vpn-pulse init / run / doctor / server / probe / note` — installation directory, the loop, one next step per finding, config edits, probe lifecycle, the note; output redacted, secrets `0600` | done (server-side helper install planned) |
| `auth.py` | Telegram `initData` HMAC, `auth_date`, member/admin roles | done |
| `api/` | routes from `contracts/openapi.yaml`, role projections, Problem Details; stateless over SQLite | done |
| `analytics.py` | allowlisted product events, idempotency, retention | done |
| `observability.py` | structured JSON logs with redaction | done |
| installer, probes, watchdog | — | planned |

## Data flow

1. **Collection.** Every `collection_interval_seconds` the collector asks each server's read-only
   helper for aggregate data: peer handshake ages, connection counts, interface counters,
   service checks. Nothing identifies a person; nothing is written to the server.
2. **Probe reports.** PC, Android and cross-server probes `POST /probe/reports` with a
   per-device token. Reports are idempotent (`report_id`), carry `network.type` and
   `route_verified`, and are queued on the device when offline.
3. **Evaluation.** The evaluator turns evidence into `operational / degraded / unavailable /
   unknown` per scope, applies freshness and the two-confirmation rule, and picks the
   recommended server.
4. **Transitions.** Each state transition becomes an event and at most one queued notification
   (`notification_queue`, deduplicated by transition). Duplicate reports never produce duplicate
   messages; a restart over the same database resends nothing.
5. **Delivery.** `NotificationWorker` sends what is due every run; a failed send is retried with
   growing back-off (30 s × attempts, up to 20 attempts). Several pending messages for one server
   collapse into the newest, and an unsent outage/recovery pair cancels out.
6. **Mini App.** The web client exchanges `initData` for a short session, then reads `/status`,
   `/servers/{id}`, `/servers/{id}/metrics`, `/events`, `/help`; administrators additionally
   read `/admin/*` and `/health/ready`. The administrator's "doctor" is aggregated on the
   client from those — there is no separate doctor endpoint.

## Who hears what

| Transition | Group (members) | Administrator |
|---|---|---|
| → `unavailable` (confirmed failure) | 🔴 once | — |
| → `operational` after the group heard about an outage (whatever the path back) | 🟢 once | — |
| → `degraded` (conflicting or unconfirmed evidence) | — | 🟡 (silent message) |
| → `unknown` (no fresh evidence) | — | ⚪ (silent message) |
| → `operational` from `degraded`/`unknown` without a group alert | — | 🟢 |
| `unknown` → `operational` (first data after a gap or a restart) | — | — |

The texts are `bot.*` keys in `i18n/*.json` with the server's public name; they never carry
hosts, addresses or member data.

## Trust boundaries

- Members never receive addresses, ports, hostnames or raw errors; `AdminServerDetail` is a
  separate projection behind the admin role.
- The collector helper runs as an unprivileged user with a dedicated key and read-only access.
- Probe tokens are per device and revocable; enrollment codes are single-use, ten minutes.
- The monitoring host never stores VPN private keys or member profiles.

## Deployment (planned)

One systemd unit per process (API, collector, bot) on the monitoring host; Caddy terminates
HTTPS for the Mini App on a domain **unrelated to the VPN servers**; SQLite on local disk with
encrypted off-host backups; a watchdog on a second host. See
[operations/doctor.md](operations/doctor.md).

## Why not one big health endpoint?

Because a server's self-report is exactly the thing that lies during a block. The design keeps
the server's opinion (`collector`) as one source among several and lets independent probes
outvote it.
