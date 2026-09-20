# Backup and restore

VPN Pulse creates complete backups on demand. It does not schedule them or send them elsewhere.

```bash
sudo vpn-pulse backup
sudo vpn-pulse backup --to /var/lib/vpn-pulse/backups --keep 5
```

The `0600` tar archive contains a consistent SQLite online backup, `config.yaml`, the complete
`secrets/` directory, `run.env` when present, and `MANIFEST.json`. The manifest records the app and
database schema versions plus the size and SHA-256 digest of every payload file. The command keeps
the newest five archives by default and prints an `scp <host>:… .` command for manual retrieval.

These archives contain credentials. Keep them private. At present they remain unencrypted on the
application host with mode `0600`; copying them to protected off-host storage is the operator's
manual choice.

## Rehearse a restore

Restore into an empty directory without touching the installation:

```bash
sudo vpn-pulse restore /var/lib/vpn-pulse/backups/vpn-pulse-backup-YYYYMMDDTHHMMSSZ.tar \
  --into /tmp/vpn-pulse-restore-test
```

The command verifies every digest, rejects archives from a newer schema version, restores secure
file permissions, and runs SQLite `PRAGMA integrity_check`. Use `--dry-run` to verify and describe an
archive without creating the target directory.

## Restore the installation

Stop the writers, restore with explicit confirmation, then start them again:

```bash
sudo systemctl stop vpn-pulse-run vpn-pulse-api vpn-pulse-bot
sudo vpn-pulse restore /path/to/vpn-pulse-backup-YYYYMMDDTHHMMSSZ.tar --yes
sudo systemctl start vpn-pulse-run vpn-pulse-api vpn-pulse-bot
sudo vpn-pulse doctor
```

Before replacement, the command copies every existing destination beside itself with a
`.bak-<UTC timestamp>` suffix. It does not manage systemd itself. An archive with a bad checksum,
an unsafe path, an invalid database, or a schema newer than the installed application is refused.

`install.sh upgrade` is separate: it keeps seven database-only snapshots before migrations. Those
snapshots do not contain configuration or secrets and do not replace `vpn-pulse backup`.
