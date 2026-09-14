# Security policy

VPN Pulse observes VPN servers; it never holds VPN keys, never issues profiles and never
changes server configuration. Still, it runs next to infrastructure people rely on, so we
treat security reports seriously.

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

Use GitHub's private vulnerability reporting on this repository
("Security" → "Report a vulnerability"). Include: affected component (API, Mini App, probe,
collector, installer), a reproduction, and the impact you see. You will get an acknowledgement
within 7 days and a status update within 30 days.

## Scope

In scope:

- authentication of Telegram `initData` and session handling (`/sessions`);
- role separation — a member must never receive administrator fields;
- probe enrollment codes and tokens, report idempotency and rate limits;
- analytics ingestion (allowlist, no identity, no free text);
- installer and CLI (planned) — secret handling, file permissions, redaction in logs;
- anything that would let VPN Pulse modify a VPN server or leak server addresses to members.

Out of scope: the VPN protocols themselves (AmneziaWG, Xray), Telegram, and third-party
hosting providers.

## Design commitments

- Collectors are read-only and run as a dedicated unprivileged helper.
- Secrets live in files with `0600` permissions, never in the repository, logs or the UI.
- Member-facing responses contain no IPs, domains, ports, hostnames or raw error text.
- Probe tokens are per device and revocable; enrollment codes are single-use and expire.
- Product analytics carry an allowlist of properties and no Telegram identifiers.

See [docs/privacy.md](docs/privacy.md) and [docs/architecture.md](docs/architecture.md).
