# User guide: administrator actions

Administrators (Telegram IDs listed in the configuration) get an extra **Admin** tab and an
extra block on every server screen. Members never see any of it — this is enforced by the
API, not only by the interface.

## Admin tab

| Block | What it shows | Actions |
|---|---|---|
| Needs attention | tasks across all servers, most severe first (urgent / important / note) | — |
| Probes | computer, Android, cross-server: state, last report, route verified, queue, version | **Enroll a device** — shows a single-use code for ten minutes; **Revoke** — with confirmation |
| Services | collector, API, bot, storage, queue, HTTPS, Telegram — from `/health/ready` | — |
| Doctor | overall ok / warnings / errors and **one next step per item**, each with a copyable command | copy |
| Note for members | text shown above the server list, character counter, expiry | save, delete (with confirmation) |

On a clean install the Status screen also shows the administrator the first command to run,
`vpn-pulse server add`, with a copy button and a link to the quick start.

## Server screen, admin block

- Structured attention items for this server.
- In an incident: the probable cause, e.g. *"Blocked in the country: two timeouts in a row from
  inside, reachable from abroad, SSH responds"*, and the action — request a new address from the
  host; profiles do not change.

## What administrators cannot do from the app

Change VPN configuration, restart services, switch DNS, issue profiles. VPN Pulse informs; the
operator acts on the servers. This is deliberate: a compromised admin session must not be able
to break the VPN.

## Notes

- Keep notes short and practical: what is happening, what members should do, until when.
- The note is public to every member of the group; do not put addresses or names in it.

## Enrollment codes

Codes are single-use and expire after ten minutes. They are shown once; if a device did not
manage to enroll, create a new code. Revoking a device invalidates its token immediately; its
past reports stay in history.
