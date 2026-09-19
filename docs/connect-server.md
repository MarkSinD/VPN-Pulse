# Connect a server

> **Status: implemented for `awg-host` and `awg-docker`.** `vpn-pulse server add | list | remove`
> edit the servers block of `config.yaml`; `vpn-pulse collector keygen | pin | test | list` and
> `deploy/helper/install-helper.sh` connect the server side. `hiddify` is still planned; until a
> server has a helper, probe reports are its evidence.

## Principle

VPN Pulse only **reads** from your servers. It never edits VPN configuration, never restarts
services, never holds VPN keys. If something on this page would require write access, that is
a bug in the design — please open an issue.

## Server types

| `type` | Observed through | Minimum access |
|---|---|---|
| `awg-host` | AmneziaWG kernel interface on the host (`awg show <iface> dump`) | user `vpnpulse` whose only privilege is `sudo /usr/local/bin/vpn-pulse-dump` |
| `awg-docker` | AmneziaWG inside a Docker container | the same user; the dump runs `wg show` inside the named container — no docker group membership, no shell |
| `hiddify` | Hiddify Manager (Xray) plus optional AmneziaWG container | planned: read access to the panel's connection data; connections reported per protocol |

The helper returns aggregate numbers only: handshake ages, connection counts, interface
counters, service checks. Peer keys and any per-person data never leave the server.

## Today: `vpn-pulse server add`

```bash
vpn-pulse server add --id primary-vpn --type awg-host --name-ru "Основной сервер" --name-en "Primary server" --country NL --priority 10
vpn-pulse server list          # configured servers with their current state
vpn-pulse server remove primary-vpn --yes
```

`add` refuses duplicate ids and ids that look like hostnames; `remove` takes the server out of the
configuration and keeps its history in the database. Nothing on the VPN server is touched.

## The server side, step by step

1. **Key and map entry** (on the monitoring host):

   ```bash
   vpn-pulse collector keygen primary-vpn --host vpn1.internal.example   # or an alias from ~/.ssh/config
   ```

   creates a separate ed25519 key for this server (`secrets/collector-primary-vpn.key`, 0600),
   an entry in the collectors map (`secrets/collectors.yaml` — hosts and key paths, never in
   `config.yaml` and never in git), sets `servers[].collector_ref` and prints the command for
   step 2 with the public key in it.

2. **The helper** (on the VPN server, as root; the two scripts are in `deploy/helper/`):

   ```bash
   sudo ./install-helper.sh --kind awg-host --iface awg0 --pubkey 'ssh-ed25519 AAAA… vpn-pulse collector-primary-vpn'
   sudo ./install-helper.sh --kind awg-docker --container amnezia-awg --domain vpn.example.org --pubkey-file collector.pub
   ```

   creates the user `vpnpulse` (no password, home under `/var/lib`), installs
   `/usr/local/bin/vpn-pulse-helper` as that user's SSH **forced command** (`restrict`: no shell,
   no pty, no forwarding), `/usr/local/bin/vpn-pulse-dump` (root, 0750) with one sudoers line, and
   `/etc/vpn-pulse-helper/config`. It ends with a self-test as `vpnpulse`. `--dry-run` prints the
   plan, `--remove` takes everything away. Nothing in the VPN configuration is touched.
   Reinstallation backs up changed files beside the originals (`.bak-YYYY-MM-DD`, with a suffix
   on repeated runs). The home and authorized keys are root-owned; the account cannot replace
   its forced command. Sudo permits only the sanitizer with no arguments.

3. **Pin the host key** (monitoring host): `vpn-pulse collector pin primary-vpn` fetches the
   server's key, shows its `SHA256:` fingerprint and stores it as the only accepted key; compare it
   with `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` on the server, or pass
   `--fingerprint SHA256:…` to make the pin refuse anything else.

4. **Test**: `vpn-pulse collector test primary-vpn` runs one collection and prints the coverage
   (which contract blocks came back, which attention items) — no values that could name a host or
   a person. `vpn-pulse doctor` reports servers without a helper, missing keys and unpinned hosts.

5. `vpn-pulse run` reads the map (`storage.collectors_file`) at start and collects every server
   that has an enabled entry, once per `collection_interval_seconds`, each call bounded by the
   entry's `timeout_seconds`.

The helper's output is aggregate only — handshake ages, byte counters, booleans, percentages,
kernel names. Peer keys, preshared keys, endpoints and allowed IPs are stripped by
`vpn-pulse-dump` before anything leaves the server; `tests/test_helper_sh.py` feeds it a dump with
fake keys and asserts none of them come back.

## Removing a server

`vpn-pulse server remove <id>` takes the server out of the configuration (its history stays in
the database); delete its entry and key from `secrets/collectors.yaml` and run
`sudo ./install-helper.sh --remove` on the server. Neither step touches the VPN.

## Test peers for probes

The PC probe and the cross-server checks need a dedicated test profile per server. These peers
are marked as probes on the server and are excluded from "connected members" in every
metric. Creating them is a manual, owner-approved step; VPN Pulse only records their public
identifiers.

## What you get afterwards

The server appears on the Status screen. Until probes are enrolled, the Mini App shows the
coverage warning ("checks are not fully configured") rather than a green success — see
[concepts.md](concepts.md).
