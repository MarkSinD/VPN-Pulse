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
   prototypes at `/app/`. Add `--sqlite demo.sqlite3` to seed the chosen scenario into a real
   database on first start and serve it through the production read model instead. Get a session with `POST /api/v1/dev/session?role=member|admin`, then
   add `?scenario=<id>` (any scenario except `loading`), `?lang=ru|en` or `?delay_ms=<n>` to a
   request. `GET /api/v1/dev/scenarios` lists the ids. The dev routes are not part of the
   contract and never exist in a deployment.

6. Watch the monitoring loop work (optional).

   ```bash
   vpn-pulse run --demo --db demo.sqlite3
   ```

   The loop collects from a scripted world (10 minutes all good, 5 with a mobile-network
   problem, 10 with one server down, 15 recovering — then again), evaluates, writes snapshots,
   transitions and events into `demo.sqlite3`, and prints what the bot would send:
   `[group] 🔴 Server 2: connections fail — the check confirmed an outage` once, and `[group] 🟢
   Server 2: working again` when it recovers. Start `python -m vpnpulse.dev --sqlite demo.sqlite3`
   in a second terminal to watch the same database in the Mini App. `--once` does a single run;
   `--config config.yaml` without `--demo` runs the real loop (probe reports arrive through the
   API; server collectors are the next increment). Ctrl+C stops it; a restart resends nothing.

7. Try the administrator's command line (optional).

   ```bash
   vpn-pulse init --dir ./my-install --language en
   export VPN_PULSE_CONFIG=./my-install/config.yaml
   vpn-pulse server add --id my-vpn --type awg-host --name-ru "Мой сервер" --name-en "My server" --country NL
   vpn-pulse probe enroll pc
   vpn-pulse note set "Maintenance tonight" --expires 23:00
   vpn-pulse doctor
   ```

   `init` writes `config.yaml`, creates the database and a `0700` secrets directory (pass
   `--telegram-token-stdin --group-chat-id …` to store the bot token with `0600`; it is never
   echoed). `doctor` prints one next step per finding — the same texts as the Admin screen — and
   exits `0/1/2` for ok/warnings/failures. Every command takes `--config`, `--db` and `--lang`
   before or after the verb.

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
