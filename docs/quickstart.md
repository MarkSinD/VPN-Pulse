# Quick start

> **Status: installable preview.** The installer, the CLI, the monitoring loop and the API run
> on a clean Ubuntu 24.04; what they monitor is still fictional — collectors for real servers and
> the probes are the next increments. This page says exactly what works today.

## What you get today

- the monitoring loop, the SQLite store and read model, the API and the Mini App, the
  administrator CLI and the installer — the whole local chain is covered by one end-to-end test;
- a demo on fictional data (`./install.sh demo` or `python -m vpnpulse.dev`) that changes state
  within minutes; a real installation shows "no data yet" until the collectors and probes arrive;
- validated contracts (OpenAPI 3.1, JSON Schemas, RU/EN dictionaries) and interactive prototypes
  of every screen, including error and first-run states.

## Requirements

- Python 3.12 or newer (Ubuntu 24.04 on a server);
- a browser for the Mini App and the prototypes.

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

## Installing on a server (Ubuntu 24.04)

```bash
./install.sh preflight                 # read-only checks: python 3.12 + venv, disk, systemd, caddy
./install.sh demo                      # no root: Mini App + API on fictional data, http://127.0.0.1:8765/app/mvp.html
sudo ./install.sh install --demo-data  # system user vpn-pulse, /opt/vpn-pulse/releases/<id> with its own venv,
                                       # /etc/vpn-pulse/config.yaml + secrets (0700/0600), /var/lib/vpn-pulse,
                                       # units vpn-pulse-api + vpn-pulse-run, Caddy snippet, doctor
sudo vpn-pulse doctor                  # the wrapper runs the CLI as the service user
sudo ./install.sh upgrade              # from a newer checkout: backup, migrate, switch, restart, doctor — rolls back on failure
sudo ./install.sh rollback             # the previous release back
sudo ./install.sh uninstall            # units and application; data and secrets stay (--purge removes them)
```

Without `--yes` the install asks for language, timezone, the Mini App domain (for the Caddy
snippet), the contact link, the group id and — through a hidden prompt — the bot token; with
flags it asks nothing (`--language en --timezone UTC --domain monitor.example.org --group-chat-id …
--telegram-token-stdin`). `--demo-data` seeds three fictional servers and keeps them moving
(`vpn-pulse run --demo`) so a fresh installation has something to show; `vpn-pulse demo clear`
removes them when real servers arrive. Every changing command takes `--dry-run`.

The whole sequence — fresh install, `doctor` OK, repeated install unchanged, upgrade with a
backup, rollback, uninstall keeping data — is `scripts/install_check.sh`, run in CI on a clean
Ubuntu 24.04 (with systemd) and locally in a container with `scripts/install_check.sh --docker`.
Design notes: [operations/doctor.md](operations/doctor.md), [connect-server.md](connect-server.md).
