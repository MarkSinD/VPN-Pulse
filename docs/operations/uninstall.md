# Operations: uninstall

> **Status: implemented in `install.sh`** (`sudo ./install.sh uninstall [--purge]`).

The command lists what it will remove — the two systemd units, `/opt/vpn-pulse` (all releases
and virtual environments), `/usr/local/bin/vpn-pulse`, the Caddy snippet and its import line —
and asks once. By default it **keeps** `/etc/vpn-pulse` (configuration, secrets) and
`/var/lib/vpn-pulse` (database, backups); `--purge` removes them and the `vpn-pulse` system
user too. `--dry-run` shows the plan; `--yes` skips the question.

Removing VPN Pulse **does not** stop or reconfigure any VPN. Collector helpers on your servers
are removed separately by their owners with the command printed by `vpn-pulse server remove`
(when the server-side helpers exist).
