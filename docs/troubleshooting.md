# Troubleshooting

> `vpn-pulse doctor` and its sections (`probes`, `collector`, `queue`, `storage`, `telegram`)
> work on an installation directory created by `vpn-pulse init`; the `https` check arrives with
> the installer. See [operations/doctor.md](operations/doctor.md).

## The app shows "No recent data" for a server

Nothing has confirmed the server recently. Check, in order:

1. Is the PC probe reporting? `vpn-pulse doctor probes` shows the last report per probe. A
   sleeping or offline computer is the usual cause. The server itself may be fine.
2. Are members connected? If yes, the server stays green by member activity; only the probe
   coverage is missing.
3. Is the collector reaching the server? `/health/ready` shows `collector.age_seconds`.

`unknown` is never hidden behind a green 100 %; fix the evidence source, not the display.

## "Connection check failed from the home network", but 🌍 is green

The server is alive and reachable from abroad; only checks from inside the country fail while
regular internet there works. This pattern usually means the server address is blocked. The
administrator's view shows the probable cause; members are told which server to use instead.
Action: request a new address from your host; a domain-based endpoint makes this painless.

## Both 💻 and 🌍 fail, SSH works

The VPN service itself is not answering: container, port or forwarding rules. Check the service
on the server; this is not a block.

## Everything fails including SSH

The server is down. Use your hosting provider's console.

## The Android probe reports "route not verified"

Requests are still leaving through the VPN or Wi-Fi. Exclude *VPN Pulse Probe* in Amnezia →
Split App Tunneling, reconnect Amnezia, make sure mobile data is on, then tap "Check again".
Results with an unverified route are stored but never used for state.

## A member sees "Members of the group only"

The app was opened outside the group's bot context, or the bot lost its membership. Open the
Mini App from the pinned message in the group; the administrator should confirm the bot is
still in the group.

## The PC probe tests Latvia instead of my country

The probe VM is routed through the laptop's own VPN. Give the VM a bridged network adapter (or
exclude the VM process from the VPN client), then confirm `route_verified` turns true.

## Where to look

- `/health/ready` — per-dependency `ok` and `age_seconds`.
- Administrator section in the Mini App — attention list, probe status, doctor summary.
- Structured logs on the monitoring host (planned location: `/var/log/vpn-pulse/`), redacted.
