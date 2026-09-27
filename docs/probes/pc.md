# PC probe

> **Status: experimental agent available.** The shared Linux agent supports `KIND=pc`; complete
> the live route matrix on the intended home network before treating its reports as evidence.

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

## Reference agent

The PC mode reuses `deploy/probe-abroad/vpn-pulse-probe-abroad`, its installer, systemd timer and
0600 queue. Set `KIND=pc` in `/etc/vpn-pulse-probe/config` and use the userspace engine when the
targets require a newer AmneziaWG protocol than the VM kernel provides.

`TARGETS` maps server ids to their tunnel addresses. `HOME_EXIT` is the public address expected
outside the test tunnels; `EXPECTED_EXITS` maps each server id to the public address expected
inside its tunnel. These values belong only in the private host config. At every tick the agent:

1. calls the control URLs and the address service outside the namespaces;
2. creates one interface at a time outside the namespace, then moves it inside;
3. installs the namespace's only default route through that interface;
4. records a fresh handshake, HTTP 204 through the tunnel and its observed exit;
5. tears the interface down before checking the next target.

The report uses `network.type=home` and contains `control_internet`, `handshake` and `https` for
every target. `route_verified` is true only when the VM exit equals `HOME_EXIT` and every tunnel
exit equals its target in `EXPECTED_EXITS`. A mismatch is still reported for diagnosis, but the
server state logic excludes that report as route evidence.

Install `curl`, `iproute2`, Python 3, `amneziawg-go`, `awg` and `awg-quick`; copy
`deploy/probe-abroad/config.example`, set the private values, put one 0600 profile per target in
`/etc/vpn-pulse-probe/peers`, then enroll with the one-use code from `vpn-pulse probe enroll pc`.
Start `vpn-pulse-probe-abroad.timer` only after a manual ON/OFF route matrix succeeds.

## Enrollment

`vpn-pulse probe enroll pc` prints a single-use code valid for ten minutes. The agent exchanges
it for a personal token; the token can be revoked from the administrator screen. No shared
secrets, no root keys, no bot token on the computer.

## Test profiles

Each server needs a dedicated AmneziaWG profile for the probe. Inside the isolated PC namespace
the profile uses `AllowedIPs = 0.0.0.0/0`; this cannot change the VM's main route. The profile is
flagged as a probe on the server so it never counts as a member.

## What the administrator sees

Agent version, last report age, `route_verified`, queue size and the network the probe covers.
One computer covers one network; other carriers need other probes.
