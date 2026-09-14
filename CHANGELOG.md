# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow SemVer once the first
release is cut.

## [Unreleased]

### Added

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
