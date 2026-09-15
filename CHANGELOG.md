# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow SemVer once the first
release is cut.

## [Unreleased]

### Added

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

### Planned

- Installer (`install.sh`), CLI (`vpn-pulse …`), collectors for `awg-host`, `awg-docker`,
  `hiddify`, Telegram bot, PC and Android probes, cross-server checks. See `docs/` pages marked
  *planned*.
