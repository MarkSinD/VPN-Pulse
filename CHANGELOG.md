# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow SemVer once the first
release is cut.

## [Unreleased]

### Added

- Dev server: `python -m vpnpulse.dev --sqlite <db> --config <config.yaml>` serves a real
  installation's database with dev sessions instead of Telegram (nothing seeded, mode `live`) — the
  way to look at live data in the Mini App before the bot exists. `vpn-pulse doctor collectors`
  prints the map entries, the server each serves and the last collection per server.
- Real servers (R-11/R-12): `deploy/helper/` — `vpn-pulse-helper` (the `vpnpulse` user's SSH forced
  command; system facts as one JSON document) and `vpn-pulse-dump` (root through one sudoers line;
  the interface dump with keys, endpoints, allowed IPs and the port stripped before printing), plus
  `install-helper.sh` (user, forced command with `restrict`, sudoers, config, self-test, `--remove`,
  `--dry-run`). `SshCollector` reads a server through the helper (batch mode, pinned host key,
  per-server key, whole-call deadline) and writes the contract payload: connections from handshake
  ages, profiles, traffic as a byte delta, components, service checks, admin attention
  (`KERNEL_MODULE_MISMATCH`, `ENGINE_UNREADABLE`, `DISK_PRESSURE`, `DDNS_MISMATCH`, `TUNING_LOST`,
  RU/EN), diagnostics; fresh handshakes become a `human_activity` observation; failures are codes.
  `contracts/collectors.schema.json` and `storage.collectors_file` (the private map next to the
  secrets); `vpn-pulse collector keygen | pin | test | list`; `doctor collectors`.
  `tests/test_helper_sh.py` runs the shell helpers on fake tools with a secret canary.
- Gate A, the local vertical slice, in one test (`tests/test_e2e_gate_a.py`): the scripted world
  → `vpn-pulse run` → SQLite → the Telegram Bot API adapter on a fake transport → `vpn-pulse serve`
  built from `config.yaml` → the Mini App in Chromium, opened the way Telegram opens it (signed
  `initData`) → the page's analytics back into the same database. CI runs it in the `browser` job;
  without Playwright it is skipped, not silently passed.
- The Mini App sends its allowlisted product events to `POST /analytics/events:batch` in batches
  (shape per `contracts/analytics-events.schema.json`, a random session id, no identity) once a
  session exists — after the render or interaction that caused them, never in their way;
  `quick_start_opened` is tracked. `TelegramNotifier` tests on a fake transport (chats, silent
  administrator messages, public texts, `False` on any failure, token read at send time);
  `vpnpulse.cli.run.make_notifier` is the one place that picks Telegram or the console.
- Tests for the two Gate A rows that had none: a probe report arriving out of order never
  rewrites newer evidence (API-03); unknown time lowers coverage and never uptime (MON-04).
- `install.sh`: `preflight` (read-only checks), `demo` / `demo-stop` (no root: venv, seeded demo
  database, the loop in demo mode and the API with the Mini App at 127.0.0.1:8765), `install`
  (system user `vpn-pulse`, per-release directory with its own venv under `/opt/vpn-pulse`,
  `config.yaml` and `0700/0600` secrets under `/etc/vpn-pulse`, data under `/var/lib/vpn-pulse`,
  hardened systemd units, Caddy snippet with the domain, the `/usr/local/bin/vpn-pulse` wrapper,
  doctor as the last step; wizard or flags; `--demo-data` seeds fictional servers), `upgrade`
  (backup, migrations, switch, restart, doctor, automatic rollback on failure), `rollback`,
  `uninstall` (data and secrets kept unless `--purge`); `--dry-run` everywhere.
  `scripts/install_check.sh` runs the whole sequence on a clean Ubuntu 24.04 (CI job `install`;
  locally `--docker`).
- `vpn-pulse serve`: the production API process built from `config.yaml` (Telegram membership
  through the Bot API with a short cache, `mode: demo` when the data directory carries the demo
  marker, the Mini App served from `/app/`, no dev routes). `vpn-pulse demo seed | clear`: a demo
  scenario in a real installation. `deploy/systemd/*.service`, `deploy/caddy/vpn-pulse.caddy`.

- The administrator's command line (`vpnpulse.cli`): `vpn-pulse init` (config.yaml, database,
  `0700` secrets directory, bot token stored `0600` from a file or stdin and never echoed),
  `vpn-pulse doctor [section] [--json]` (one next step per finding with the Admin screen's texts;
  exit code 0/1/2), `vpn-pulse server add | list | remove` (atomic, contract-validated edits of
  `config.yaml`), `vpn-pulse probe enroll | list | revoke` (single-use codes, audit without the
  code), `vpn-pulse note set | clear | show`. `--config` / `VPN_PULSE_CONFIG`, `--db` and `--lang`
  work before or after the command; every line printed passes through a redactor.
- Configuration contract: optional `storage.database` (the SQLite file shared by the API and the
  loop) and `telegram` (`bot_token_file`, `group_chat_id`, `admin_chat_id`) blocks; `vpn-pulse run`
  reads both. Contract 1.4.1: `PUT /admin/note` answers 404 `SERVER_NOT_FOUND` for an unknown
  `server_id`; the API mirrors configured servers into the tables at start-up (`sync_servers`).

- The monitoring loop (`vpnpulse.pipeline`, `vpn-pulse run`): collect → evaluate → snapshots →
  transitions → member-visible events → notification queue, plus an hourly retention sweep and
  hourly connection aggregates (`metric_hourly`). One process owns the loop over the SQLite file
  the API reads; a failing collector marks the run and never stops it. Notification policy: the
  group hears about a confirmed outage once and about the recovery that follows it; unconfirmed
  problems and data gaps go to the administrator; the first evaluation after a gap tells nobody.
  Failed sends retry with growing back-off, pending messages for one server collapse into the
  newest, an unsent outage/recovery pair cancels out, a restart resends nothing.
- `vpnpulse.collectors`: the `Collected` / `Collector` interface and `FixtureCollector`, a scripted
  world that plays the demo scenarios over time (`vpn-pulse run --demo`, tests).
- `vpnpulse.notify`: message texts from `i18n/*.json` (`bot.*`, public server names only) with
  console, fake and Telegram Bot API senders.
- SQLite writes (`vpnpulse.storage.SqliteStore`): web sessions, one-time enrollment codes, probes
  with hashed tokens, idempotent reports turned into observations, the administrator note, product
  analytics, audit entries and a retention sweep. The API keeps no state between requests; the
  same code path runs in tests, the dev server (in-memory database) and production. One shared
  connection serializes its statements for the worker threads (`SerializedConnection`).
- SQLite read model (`vpnpulse.storage.SqliteReadModel`): every read route is served from the
  database and the public configuration — state and freshness from snapshots, evidence from the
  latest observation per source, availability and metric points from the state timeline, server
  details from the newest collector payload, check-source presence from probes, doctor and
  installation-wide attention derived from the tables. Strict pydantic response models validate
  every read response. `python -m vpnpulse.dev --sqlite <file>` seeds a scenario into a real
  database (`vpnpulse.dev.seed`) and serves it through the same model.
- Contract 1.4.0: documented `Accept-Language` on localized routes;
  `contracts/collector-observation.schema.json` — the payload every collector writes.
- Server-side RU/EN strings for doctor hints and attention messages (`i18n/*.json`, `vpnpulse.i18n`).
- The Mini App reads the API: `web/src/api.js` (contract client) and `web/src/model.js` (one view
  model built either from API payloads or from the demo scenarios); the renderer is unchanged.
  Sessions via Telegram init data or the dev session, role from `GET /sessions/current`, 60-second
  refresh, offline and membership screens driven by real responses, admin note / enrollment / revoke
  through the API, real 7-day metrics. `scripts/ui_parity_check.py` proves API render == scenario
  render for every scenario × role × language × screen; `scripts/ui_check.py` is the browser QA matrix.
- Contract 1.3.0 (additive): `GET /sessions/current`, `GET /admin/overview` (attention items across
  the installation + doctor summary), `EvidenceSummary.via_server_id`, `ProfileStats.last_connection_at`.
- Dev server (`python -m vpnpulse.dev`): the real API on the demo scenarios with `?scenario=`,
  `?lang=`, `?delay_ms=`, dev sessions, and the built Mini App at `/app/`. The read side of the API
  now goes through a `ReadModel` protocol (`vpnpulse.api.read_model`); `tests/test_dev_server.py`
  validates every route × scenario × role against the contract.
- Contract: `SoftwareComponent.note` (free member-safe detail); demo scenarios moved to
  `fixtures/ui/scenarios.json` and gained attention codes (`KERNEL_MODULE_MISMATCH`, …).
- API contract v1.2.0 (`contracts/openapi.yaml`): `StatusResponse.sources` / `SourceAvailability` —
  check sources that exist right now (a source appears after its probe's first report); the UI hides
  missing sources instead of warning members about them.
- API contract v1.1.0 (`contracts/openapi.yaml`): additive fields required by the accepted UI —
  `StatusResponse.mode` and `observing_since`, empty server list on a clean install,
  `ServerDetail.components / resources / profiles / service_checks / uptime_7d / coverage_7d`,
  `Event.kind = monitoring`, `/help.contact_url`, `AdminServerDetail.attention_items`,
  probe health fields on `ProbeSummary`. Contract tests in `tests/test_contract_ui_v4.py`.
- Configuration schema: `app.admin_contact_url`; servers may be empty right after installation.
- Interactive UI prototypes (`docs/prototypes/`): Mini App with thirteen scenarios, roles,
  RU/EN and light/dark; Android probe flow; first-run walkthrough.
- Visual style v5 "instrument panel": near-black / iOS-grouped palette of its own, gauge rings with
  inline SVG flags (24-hour availability as the arc), brushed-metal primary button, recessed panels,
  engraved rules, lamp badges; two font weights and 1.5 line-height. `scripts/check_contrast.py`
  verifies 4.5:1 text and 3:1 control contrast for both themes in CI.
- Backend core (mock-first): configuration loader, SQLite migration, state evaluator with
  canonical fixtures, session/auth, analytics ingestion, route parity with the contract.
- Repository scaffolding: documentation set, CI (tests, contract validation, link check,
  private-data scan, secret scan), security policy, contributing guide.

### Changed

- CI: the private-data scan of Git history looks at diffs only (commit metadata is not published
  content); the browser QA/parity and the installer jobs are blocking after their first green runs.
- The doctor's probes hint on a fresh installation reads "After the server, enroll the probes"
  (`doctor.probes.afterServer`), matching the Admin screen fixtures.

### Planned

- The `hiddify` helper, Telegram bot in a real group, `doctor https`, PC and Android probes,
  cross-server checks, watchdog and off-host backups. See `docs/` pages marked *planned*.
