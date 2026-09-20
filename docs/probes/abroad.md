# Cross-server probe (🌍 "from abroad")

An `abroad` probe checks a VPN server **from another server** through a dedicated test peer: a real
AmneziaWG handshake plus a ping through the tunnel, once a minute. It is the evidence that tells
"the server is blocked where the members are" from "the server is down": members' probes fail from
home while the cross-server check still passes.

What it reports: the target id, `handshake` success or failure, the duration, the time, and
`route_verified` — nothing about addresses, keys or people. The test peer is marked as a probe on
the target, so the collector never counts it as a member or as human activity.

## How a check works

The probe host keeps a persistent network namespace with **no default route**. For each target the
agent creates an AmneziaWG interface in the main namespace (so its UDP socket keeps the host's route
to the endpoint), moves it into the namespace, adds the probe's tunnel address and one `/32` route to
the target, pings the target's tunnel address, reads the handshake age and deletes the interface.
Success means a handshake younger than 30 s **and** a ping reply through the tunnel. Inside the
namespace there is nowhere else to go, so a torn tunnel cannot pass by reaching the target directly.

Failures carry a code: `TUNNEL_SETUP_FAILED` (interface, keys or parameters), `HANDSHAKE_FAILED`
(no fresh handshake — the usual sign of a blocked or dead endpoint), `PING_FAILED` (handshake but no
reply), `CHECK_TIMEOUT`.

## Setting it up

Needs on the probe host: the AmneziaWG kernel module (`ip link add … type amneziawg`), `awg` and
`awg-quick` from amneziawg-tools, `python3` (3.8+, standard library only), systemd. The unit runs as
root because creating and moving interfaces between namespaces needs it; the unit confines the
filesystem (`ProtectSystem=strict`, two writable directories) and caps memory at 64 MiB.

1. **Install** from `deploy/probe-abroad/`: `sudo sh install-probe-abroad.sh` creates the namespace
   `vpprobe`, `/etc/vpn-pulse-probe/{peers,keys}` (0700), `/var/lib/vpn-pulse-probe`, the unit and
   the timer (enabled, not started). Copy `config.example` to `/etc/vpn-pulse-probe/config`:
   `API_URL`, `TOKEN_FILE`, and `TARGETS=<server id>=<its tunnel address>,…` — the ids are the ones
   from `config.yaml`.
2. **A test peer per target.** On the probe host `create-probe-profile.sh` generates the key pair and
   the preshared key (they never leave the host) and writes `peers/<server id>.conf` with the
   target's AmneziaWG parameters, endpoint and a `/32` `AllowedIPs`. Give the target the public key:
   on an Amnezia Docker server `add-probe-peer.sh` adds the peer to the interface config and to
   `clientsTable` under a recognizable name (`probe-from-…`), applies it live and backs both files
   up first. On a host-mode server add the peer the way you add any client. Then put the probe's
   public key into `PROBE_PEERS` in `/etc/vpn-pulse-helper/config` on the target
   (`install-helper.sh --probe-peers "<key> <key>"` writes it) — from then on the helper reports that
   peer as `probe` and the collector leaves it out of every count.
3. **Enroll.** On the application host: `sudo vpn-pulse probe enroll abroad --via <server id of the
   probe host>` prints a single-use code (ten minutes). On the probe host:
   `sudo vpn-pulse-probe-abroad enroll <code>` stores the token (0600). The `--via` server is the one
   the app shows as "checked from"; the probe never receives itself as a target.
4. `sudo systemctl start vpn-pulse-probe-abroad.timer`; `journalctl -u vpn-pulse-probe-abroad -n 5`
   prints one line per round, e.g. `backup=success primary=success`.

Reports wait in a 0600 JSONL queue (`/var/lib/vpn-pulse-probe/queue.jsonl`, 24 hours, 1500 entries)
while the API is unreachable and go out oldest first.

## What the administrator sees

`vpn-pulse probe list` shows the probe with its last report; the server screens show the 🌍 source
with "checked from <server>".
Removing the probe: `install-probe-abroad.sh --remove` on the probe host (keeps the profiles), the
peer on the target the way any client is removed, and `vpn-pulse probe revoke <id>` on the app host.
