# Operations: upgrade and rollback

> **Status: implemented in `install.sh`** (`sudo ./install.sh upgrade | rollback`); the
> `vpn-pulse upgrade` / `rollback` commands with database-compatibility reports are planned on top.

## Layout

Every release lives in its own directory with its own virtual environment —
`/opt/vpn-pulse/releases/<timestamp>-<git sha>` — and `/opt/vpn-pulse/current` points at the one
that runs. The systemd units start `/opt/vpn-pulse/current/venv/bin/vpn-pulse`, so switching a
release is switching one symlink and restarting two services. The last three releases are kept.

## Upgrade

`sudo ./install.sh upgrade` from a newer checkout:

1. preflight (nothing changes if it fails);
2. a new release directory is built from the checkout (skipped when the source is already the
   current release);
3. the database is copied with SQLite's online backup to
   `/var/lib/vpn-pulse/backups/vpnpulse-<timestamp>.sqlite3` (0600; the last seven are kept);
4. the monitoring loop is stopped and the new code applies its migrations (they are additive —
   a destructive migration is not allowed in this project);
5. `current` is switched, both services restart, `vpn-pulse doctor` runs;
6. if the doctor reports failures, the previous release is switched back and restarted
   automatically and the command exits with `2`.

`--dry-run` prints the plan. Configuration, secrets and data are never touched by an upgrade.

## Rollback

`sudo ./install.sh rollback` switches `current` to the previous release, restarts the services
and runs the doctor. The database keeps its schema: because migrations only add, the previous
release reads it. Roll back only one step at a time; if the doctor is red after a rollback,
restore the backup made by the upgrade (`docs/operations/backup-restore.md`).

## What never changes during upgrade

Your VPN servers, their configuration and the collector helpers on them. Upgrades touch only
the monitoring host.
