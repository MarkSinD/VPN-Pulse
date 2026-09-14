# Operations: upgrade and rollback

> **Status: planned.** Behaviour described for review; commands are not implemented.

## Upgrade

`vpn-pulse upgrade` first shows the current and target versions, configuration and database
compatibility, the backup path and the restart plan. Then, after confirmation: preflight,
local backup, migrations, restart, `doctor`. If a P0 health check fails after restart, the
application is rolled back automatically to the previous version.

## Rollback

`vpn-pulse rollback` reports whether the current database is compatible with the previous
version. Unknown compatibility blocks the action and prints the restore instruction instead of
guessing.

## What never changes during upgrade

Your VPN servers, their configuration and the collector helpers on them. Upgrades touch only
the monitoring host.
