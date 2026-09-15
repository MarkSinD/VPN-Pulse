# Connect a server

> **Status: partly implemented.** `vpn-pulse server add | list | remove` edit the servers block
> of `config.yaml` today (validated against the contract, written atomically); the SSH steps and
> the read-only helpers below are designed but not implemented yet. Until they exist, probe
> reports are the evidence for a server.

## Principle

VPN Pulse only **reads** from your servers. It never edits VPN configuration, never restarts
services, never holds VPN keys. If something on this page would require write access, that is
a bug in the design — please open an issue.

## Server types

| `type` | Observed through | Minimum access |
|---|---|---|
| `awg-host` | AmneziaWG kernel interface on the host (`awg show <iface> dump`) | dedicated helper user allowed to run one wrapper script |
| `awg-docker` | AmneziaWG inside a Docker container | helper user allowed to run one wrapper that executes `wg show` inside the named container; no docker group membership, no shell |
| `hiddify` | Hiddify Manager (Xray) plus optional AmneziaWG container | read access to the panel's connection data; connections are reported per protocol |

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

## Planned flow: `vpn-pulse server add` on the server side

1. Choose the type, a display name (RU/EN) and the country code.
2. Confirm the SSH host key fingerprint; it is pinned for future connections.
3. VPN Pulse generates a **separate** collector key for this server.
4. Dry run: the wizard prints the exact helper setup it wants to perform on the target server.
5. You confirm; the helper (an unprivileged user and one wrapper script) is installed.
6. A test collection runs and shows the fields and coverage it obtained — no sensitive values.
7. The configuration is saved atomically and `doctor` checks the new source.

Cancelling at any step leaves no half-configured source.

## Removing a server

`vpn-pulse server remove <id>` stops collection and revokes the collector key first. Removing
the helper from the target server is a separate printed command run by the server owner; it
does not touch the VPN.

## Test peers for probes

The PC probe and the cross-server checks need a dedicated test profile per server. These peers
are marked as probes on the server and are excluded from "connected members" in every
metric. Creating them is a manual, owner-approved step; VPN Pulse only records their public
identifiers.

## What you get afterwards

The server appears on the Status screen. Until probes are enrolled, the Mini App shows the
coverage warning ("checks are not fully configured") rather than a green success — see
[concepts.md](concepts.md).
