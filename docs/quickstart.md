# Quick start

> **Status: developer preview.** There is no installer or CLI yet. This page tells you exactly
> what works today and what is planned, so you do not waste an evening on a command that does
> not exist.

## What you get today

- the backend core with tests (state evaluator, configuration, SQLite migration, mock-first API);
- validated contracts (OpenAPI 3.1, JSON Schemas, RU/EN dictionaries);
- interactive prototypes of every screen, including error and first-run states.

## Requirements

- Python 3.12 or newer;
- a browser for the prototypes.

## Steps

1. Clone and install in a virtual environment.

   ```bash
   git clone https://github.com/MarkSinD/VPN-Pulse.git
   cd VPN-Pulse
   python -m venv .venv && . .venv/bin/activate    # Windows: .venv\Scripts\activate
   pip install -e ".[dev]"
   ```

   Success: `pip` finishes without errors.

2. Run the tests.

   ```bash
   python -m pytest
   ```

   Success: all tests pass. They cover the evaluator (zero users ≠ failure, two confirmations,
   stale → unknown), authentication, role projections, analytics allowlist and the contract
   fields the UI relies on.

3. Validate the contracts.

   ```bash
   python scripts/validate_specs.py
   ```

   Success: a line like `specs OK: 18 API paths, 27 schemas, 291 i18n keys`.

4. Open the prototypes.

   Open `docs/prototypes/mvp.html` in a browser. The dark dashed bar at the top is the showcase:
   switch the scenario to `unavailable` or `clean_install`, the role to `admin`, the theme and
   the language. Open `docs/prototypes/android.html` for the probe flow and
   `docs/prototypes/onboarding.html` for the first-run walkthrough.

5. Run the dev server (optional).

   ```bash
   python -m vpnpulse.dev --scenario degraded
   ```

   It serves the real API on the demo scenarios at `http://127.0.0.1:8765/api/v1/` and the
   prototypes at `/app/`. Get a session with `POST /api/v1/dev/session?role=member|admin`, then
   add `?scenario=<id>` (any scenario except `loading`), `?lang=ru|en` or `?delay_ms=<n>` to a
   request. `GET /api/v1/dev/scenarios` lists the ids. The dev routes are not part of the
   contract and never exist in a deployment.

## Planned installation path

When the installer ships, the intended path is (not available yet):

```text
./install.sh demo          # UI on fixtures, no Telegram token needed
./install.sh preflight     # read-only environment checks
sudo ./install.sh install  # seven-step wizard: environment, app, config, secrets, HTTPS, Telegram, doctor
vpn-pulse server add       # connect a server (awg-host | awg-docker | hiddify)
vpn-pulse probe enroll pc  # one-time enrollment code for a probe
vpn-pulse doctor           # end-to-end diagnostics
```

Progress is tracked in [CHANGELOG.md](../CHANGELOG.md). Design of the installer:
[operations/doctor.md](operations/doctor.md) and [connect-server.md](connect-server.md).
