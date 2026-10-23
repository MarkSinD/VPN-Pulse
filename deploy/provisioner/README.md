# Provisioner boundary

Install this command for a dedicated account with an `authorized_keys` forced command. The account
must not have an interactive shell or share the read-only collector key. The root-owned
`/etc/vpn-pulse-provisioner/config.json` selects fixed persistent paths and starts with
`"writes_enabled": false`.

SSH input is one JSON object on stdin. The only accepted command is exactly
`vpn-pulse-provisioner`; paths, interfaces and shell fragments are rejected. R-39 supports
`inspect`, dry-run and atomic `issue`/`revoke`. Live writes require `writes_enabled: true`; every
change is locked, backed up, applied to persistent config and optional `clientsTable`, applied live,
read back and journaled by idempotency key. A failed apply restores persistent files. Start with
false and enable one server only after its inspect and owner test pass.

```json
{
  "kind": "awg-host",
  "persistent_config": "/path/chosen-by-the-owner",
  "clients_table": null,
  "live_command": ["awg", "set", "awg0"],
  "writes_enabled": false
}
```

For a Docker server use host-visible mounted paths, set `container`, and use a fixed command such as
`["docker", "exec", "vpn-container", "awg", "set", "awg0"]`. The provisioner copies the temporary
0600 PSK file into that container and deletes both copies after apply. The container name and every
command element are root-owned configuration; request JSON can never select a path or command.

Inspect responses contain only counts and public-key fingerprints. Issue returns the newly generated
PSK once to the application for client delivery; it is not written to logs or the application DB.
