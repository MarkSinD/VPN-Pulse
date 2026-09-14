# Android probe

> **Status: planned.** Design complete and prototyped in `docs/prototypes/android.html`; the
> app is not built yet.

The Android probe checks the **mobile network** from inside the users' country, outside the
VPN. It does not test VPN tunnels — the PC probe does that — so it stays small and honest:
carrier DNS, TCP/HTTPS reachability of allowed targets, and the network path itself.

## First run

1. **Enroll.** Enter the single-use code from the administrator screen (or scan it). The phone
   receives a personal token and its list of allowed targets.
2. **Exclude the app from the VPN.** In Amnezia: *Split App Tunneling → apps that work without
   VPN → add VPN Pulse Probe*, then reconnect Amnezia. Otherwise every check would travel through
   the tunnel and report the view from abroad.
3. **Cellular check.** The app binds its sockets to the cellular network (exclusion alone does
   not prefer mobile data over Wi-Fi) and verifies the path with a control HTTPS target while
   Wi-Fi and Amnezia are on. Green means: requests really leave through the mobile network,
   bypassing the VPN.
4. **Done.** Tap *Start* whenever convenient.

## Running

- *Start* opens a visible diagnostic session: checks every minute while the screen is on.
- In the background Android allows at most one run per 15 minutes and may delay it; the app
  shows the last measurement and never promises a five-minute alert from the phone.
- Results are queued when offline and sent over cellular when it returns.
- No SIM / no mobile data → "no data", not a failure.

## What is sent

Per report: network type `cellular`, IP family, `route_verified`, and per-target results
(`dns`, `tcp`, `https`, `control_internet`) with durations and `not_run` reasons
(`no_cellular`, `route_unverified`, `stopped`). No SSID, phone number, location or user traffic.

## Distribution

A signed APK outside public stores for the pilot, published with a checksum in releases.
The signing key stays with the project owner. The app contains no shared token; enrollment
codes are personal and revocable.

## Screens

See `docs/prototypes/android.html` — states: not enrolled, enrollment error, exclusion
instruction, cellular check (checking / ok / failed / no SIM), done, running, stopped,
offline queue, stale, missing permission.
