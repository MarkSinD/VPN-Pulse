# PC probe

> **Status: planned.** Design complete; the agent is not implemented yet.

The PC probe is the only source that proves a **full VPN connection** works from inside the
users' country: a real handshake to each server plus a small HTTPS request through the tunnel,
once a minute per target.

## Network path — the part that matters

```
 your home network ──► PC probe ──► VPN server A   (tunnel 1, isolated)
                        │      ──► VPN server B   (tunnel 2, isolated)
                        │      ──► VPN server C   (tunnel 3, isolated)
                        └── reports ──► VPN Pulse API (HTTPS, outside the tunnels)
```

The probe must reach the servers **directly from the local network**. If the computer runs
its own VPN client all the time, the probe would test from the VPN exit — from abroad — and
report success during a block. Two ways to guarantee the direct path:

1. **A Linux VM with a bridged network adapter** (recommended). The VM gets its own address on
   the home network and does not inherit the host's routes, VPN or not. Inside the VM each
   target gets its own network namespace with its own tunnel, DNS and test key, so three full
   tunnels do not fight over the default route.
2. Excluding the VM or the probe process from the VPN client via split tunneling.

Before every series the probe verifies the route: it asks a control HTTPS target for the public
address it sees and compares it with the expected home-network address. If they do not match,
reports are sent with `route_verified: false` and are **excluded from state**.

## What one check does

1. `control_internet` — two independent HTTPS targets respond (so a dead home connection is
   not mistaken for a blocked VPN).
2. `handshake` — the AmneziaWG handshake completes within the deadline (default 20 s).
3. `https` — an HTTPS request through the tunnel returns the expected answer. Direct fallback
   is forbidden inside the test namespace, so a torn tunnel cannot pass by accident.

Results are queued locally when the API is unreachable (up to 24 hours) and sent later; late
reports go to history only.

## Enrollment

`vpn-pulse probe enroll pc` prints a single-use code valid for ten minutes. The agent exchanges
it for a personal token; the token can be revoked from the administrator screen. No shared
secrets, no root keys, no bot token on the computer.

## Test profiles

Each server needs a dedicated AmneziaWG profile for the probe, with `AllowedIPs` narrowed to
the check targets. The profile is created by the server owner and is flagged as a probe on the
server so it never counts as a member.

## What the administrator sees

Agent version, last report age, `route_verified`, queue size and the network the probe covers.
One computer covers one network; other carriers need other probes.
