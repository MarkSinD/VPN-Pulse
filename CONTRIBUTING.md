# Contributing to VPN Pulse

Thanks for helping. The project is early: the design, contracts and backend core exist; the
installer, CLI, real collectors and probes are still being built. Small, verified changes win.

## Ground rules

- **Never** commit real server addresses, domains, tokens, Telegram IDs, keys or screenshots
  with real data. CI runs a private-data scan; please run it locally too.
- Contracts first: change `contracts/openapi.yaml` or the JSON Schemas together with a test in
  `tests/`, and keep changes backward compatible (optional fields, wider enums).
- UI strings live only in `i18n/ru.json` and `i18n/en.json`. Both files must have the same keys
  and the same `{placeholders}`; `scripts/validate_specs.py` enforces it.
- `unknown` is never rendered as a success. Zero connected users is not a failure.
- Members must not receive administrator data. Add a test when you touch role projections.

## Local setup

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
python -m pytest
python scripts/validate_specs.py
python scripts/check_links.py
python scripts/check_public_tree.py
```

The Mini App and the prototypes are generated from `web/src/` with `python scripts/build_prototypes.py`;
`python scripts/ui_check.py` runs the browser QA and `python scripts/ui_parity_check.py` proves the app
renders the same DOM from the API as from the demo scenarios (both need Playwright + Chromium, as does
`tests/test_e2e_gate_a.py`, the end-to-end test — `pytest -rs` shows it as skipped without them).
Edit the sources, not the built HTML.

## Pull requests

1. One topic per PR; describe the user-visible change and how you verified it.
2. Tests and the validation scripts must pass (CI runs them).
3. For UI changes attach screenshots at 320 px and 390 px, light and dark, RU and EN,
   built from fixtures only.
4. Update `CHANGELOG.md` under *Unreleased*.

## Where to start

- `tests/` and `src/vpnpulse/domain/evaluator.py` — the state machine and its fixtures.
- `docs/api.md` and `contracts/openapi.yaml` — the API surface.
- `web/src/app.js` — the Mini App (renderer), `web/src/model.js` — the view model built from the API or
  from the demo scenarios, `web/src/api.js` — the contract client.
- Issues labelled `good first issue`.

## Code of conduct

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).
