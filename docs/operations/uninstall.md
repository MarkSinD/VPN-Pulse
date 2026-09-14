# Operations: uninstall

> **Status: planned.** Behaviour described for review; the command is not implemented.

`vpn-pulse uninstall` lists exactly what will be removed (systemd units, application files,
Caddy site) and what will be kept (`--keep-data` is the default: database, configuration,
secrets, backups). It asks for confirmation once.

Removing VPN Pulse **does not** stop or reconfigure any VPN. Collector helpers on your servers
are removed separately by their owners with the command printed by `vpn-pulse server remove`.
