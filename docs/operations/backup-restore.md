# Operations: backup and restore

> **Status: partly implemented.** `install.sh upgrade` makes a local copy of the database before
> every upgrade (`/var/lib/vpn-pulse/backups/`, 0600, last seven kept). The encrypted off-host
> `vpn-pulse backup` / `restore` commands below are planned.

## What is backed up

The SQLite database (evidence, aggregates, events, analytics, audit), `config.yaml`, and the
secret files — encrypted before leaving the host. VPN keys are not part of VPN Pulse and are
never included.

## Backup

`vpn-pulse backup` writes an encrypted archive to the configured destination and verifies it
can be opened. A scheduled backup runs daily; the watchdog reports a missing backup.

## Restore

`vpn-pulse restore <archive>` stops the services, restores files, runs forward migrations if the
archive is older than the installed version, starts the services and runs `doctor`. A clean
restore drill is part of the release gates.
