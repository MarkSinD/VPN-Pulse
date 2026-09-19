# Operations: doctor and installation

> **Status: `vpn-pulse doctor` and `install.sh` work.** The installer is checked end to end on a
> clean Ubuntu 24.04 by `scripts/install_check.sh` (fresh install → doctor OK → repeated install
> unchanged → upgrade → rollback → uninstall keeping data). HTTPS and backup checks of the doctor
> are still planned.

## Two entry points

- `./install.sh demo [--prefix DIR] [--port N]` — no root: a virtual environment under
  `~/.vpn-pulse-demo`, a seeded demo database, the monitoring loop in demo mode and the API with
  the Mini App at `http://127.0.0.1:8765/app/mvp.html`. No Telegram token, domain or SSH; the
  "Demo data" mark is always on. `./install.sh demo-stop` stops it.
- `./install.sh preflight` then `sudo ./install.sh install` — seven steps: environment,
  application, configuration and secrets, demo data (optional), HTTPS (Caddy snippet), services,
  doctor. Preflight changes nothing; `--dry-run` lists every change before it is made.

The wizard asks only what cannot be derived safely: language and timezone, the Mini App domain,
the contact link, the group id and the bot token (hidden prompt; it goes to
`/etc/vpn-pulse/secrets/telegram-bot.token` with `0600` and nowhere else). With flags it asks
nothing. Servers and probes are connected afterwards with `vpn-pulse server add` and
`vpn-pulse probe enroll`, so you get a working interface before the sources are ready; with
`--demo-data` it shows fictional servers in the meantime.

What the installation looks like:

| Path | Owner / mode | Contents |
|---|---|---|
| `/opt/vpn-pulse/releases/<id>` | root, world-readable | the application and its own virtual environment; `current` → the running one |
| `/etc/vpn-pulse/config.yaml` | `vpn-pulse`, 0640 | the public configuration (the units mount it read-only) |
| `/etc/vpn-pulse/secrets/` | `vpn-pulse`, 0700 / files 0600 | the bot token, later collector keys |
| `/etc/vpn-pulse/run.env` | root, 0644 | `VPN_PULSE_RUN_ARGS=--demo` for a demo installation |
| `/var/lib/vpn-pulse/` | `vpn-pulse`, 0750 | `vpnpulse.sqlite3`, `backups/`, the `demo-data` marker |
| `/etc/systemd/system/vpn-pulse-{api,run}.service` | root | hardened units (`ProtectSystem=strict`, private tmp, no new privileges) |
| `/usr/local/bin/vpn-pulse` | root, 0755 | runs the CLI as the service user with the installed configuration |

## Every step reports the same way

```text
[5/7] doctor
  [OK]   storage: database ready, schema 1
  [FAIL] servers: Connect the first server  →  vpn-pulse server add
  [WARN] probes: After the server, enroll the probes  →  vpn-pulse probe enroll pc
No system changes were made in this step.
```

Success is never signalled by colour alone; every failure carries a safe re-check command. The
HTTPS step (records and certificate of the Mini App domain, `vpn-pulse doctor https`) is planned
with the real domain; today the installer writes the Caddy snippet and leaves DNS to you.

## `vpn-pulse doctor`

```text
$ vpn-pulse doctor
doctor: FAIL
  [FAIL] servers: Connect the first server  →  vpn-pulse server add
  [WARN] probes: After the server, enroll the probes  →  vpn-pulse probe enroll pc
  [OK]   telegram: Telegram is not configured — messages are printed to the console; …  →  vpn-pulse doctor telegram
```

One line per finding, one next step each, failures first. Exit code `0` when everything passed,
`1` with warnings, `2` with failures — so `vpn-pulse doctor` works as a post-install gate.
`--json` prints `{"result", "items", "next_command"}`; `--lang ru|en` picks the language of the
hints (default: `app.default_language`).

| Check | Where it comes from | What it says |
|---|---|---|
| `servers` | configuration | no servers yet → connect the first one |
| `probes` | `probes` table | none enrolled → enroll; enrolled but silent (no report for 15 min) → wake the computer / check the network |
| `collector` | `collection_runs` | never ran → start the `vpn-pulse` service; last run failed or older than three intervals → check the service and server access |
| `queue` | `notification_queue` | messages pending for more than ten minutes → check the bot |
| `storage` | the database file | missing → `vpn-pulse init`; cannot be opened → path and permissions |
| `telegram` | `telegram` block and the token file | not configured (information: messages go to the console — a demo or a fresh installation stays green); token file missing or empty (failure); readable by others (`chmod 600`) |
| `collectors` | the collectors map and its files | no map yet (information: probes are the evidence); a server without an entry (warning: `collector keygen`); a key missing or readable by others (failure); host key not pinned (warning: `collector pin`) |

`servers`, `probes`, `collector` and `queue` are computed by the same code that serves
`GET /admin/overview`, so the terminal and the Mini App never disagree; `storage` and `telegram`
look at files the Mini App cannot see. `vpn-pulse doctor <check>` limits the output to one check
and adds details (per-probe last report, last collection run, queue counts, database size and
schema version, token-file status — never its contents).

Planned additions: `https` (records and certificate of the Mini App domain, with the installer),
`backup` (age of the last archive) and `--support-bundle`, a local redacted archive that lists
its contents first; nothing is ever uploaded automatically.

In the Mini App the administrator sees the compact doctor summary from `/admin/overview` plus
`/health/ready` and `/admin/probes` — there is no separate doctor endpoint.

## Final screen

After installation only four results are shown: the Mini App URL, Telegram state, the number
of connected sources and the doctor result. The installer does not declare success while
API, HTTPS or secret storage fail a mandatory check.

## Related

- [upgrade-rollback.md](upgrade-rollback.md) · [backup-restore.md](backup-restore.md) · [uninstall.md](uninstall.md)
