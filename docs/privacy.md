# Privacy

VPN Pulse is built for a small trusted circle, but it is designed as if it were public.

## What members see

- server display names, country flags, states, freshness, availability history;
- three check sources and whether they passed;
- aggregate connection counts per protocol, aggregate profile counts, coarse resource load;
- the administrator's note.

Members **never** see IP addresses, domains, ports, hostnames, hosting provider names, raw error
text, per-person data, or anything about other members.

## What the service stores about people

As little as the features need: web sessions carry only the role and a peppered hash of the
Telegram user id; probe tokens and enrollment codes are stored as SHA-256 hashes; the administrator
note is plain text written by the administrator; product analytics are allowlisted events without
identity, deduplicated and deleted after `analytics_raw_days`; audit entries record administrator
actions with a hashed actor.

## What the collector reads on your servers

Aggregate, read-only data: handshake ages and counts of VPN peers, interface counters, whether
the VPN process/container and port are up, DNS/DDNS consistency. It does not read peer keys,
does not map peers to people and does not write anything. Test peers used by probes are
flagged and excluded from "connected members".

## What probes send

Per report: `report_id`, agent version, timestamp, network type (`home`, `cellular`, `abroad`),
IP family, `route_verified`, and per-target results (`success` / `failure` / `not_run` with a
reason and duration). No SSID, no phone number, no browsing data, no user traffic.

## Product analytics

Optional, privacy-preserving: a random 24-hour `session_id`, an allowlisted event name and an
allowlisted set of properties (role, language, theme, viewport bucket, state buckets, public
server id, timings). The allowlist is enforced by
[`contracts/analytics-events.schema.json`](../contracts/analytics-events.schema.json) and by
tests. No Telegram ID, username, IP, note text or error text is ever stored. The Mini App sends
its events in small batches after a screen has rendered or an interaction happened (never before,
never blocking); the queue lives in the page's memory, so closing the app drops what was not sent.

## Secrets

The Telegram bot token, collector keys and probe tokens are files with `0600` permissions (installed under `/etc/vpn-pulse/secrets/`, owner `vpn-pulse`) on
the monitoring host. They are never written to the repository, the configuration file, logs,
API responses or the static web bundle. Logs are structured JSON with redaction; neither the API
process nor the reverse proxy keeps an access log by default (`vpn-pulse serve --access-log`
turns one on for a troubleshooting session).

An on-demand backup contains the configuration, database and secret files. It stays on the
application host as an unencrypted `0600` archive until the operator retrieves or removes it.

## Retention

Raw evidence 7 days, aggregates 90 days, events 180 days, raw analytics 30 days, audit 365 days
by default — all configurable, see [configuration.md](configuration.md).

## Your responsibility

The monitoring host domain should be unrelated to your VPN servers — the Mini App's hostname
is visible to the network operator. Do not publish screenshots with real server names if
those names identify locations you would rather keep private.
