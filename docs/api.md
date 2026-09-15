# API

The contract is [`contracts/openapi.yaml`](../contracts/openapi.yaml) (OpenAPI 3.1, version
1.1.0). Base path `/api/v1`. Unknown values are `null`, never zero. Errors are RFC 9457
Problem Details with a stable `code` and a `trace_id`.

## Authentication

| Scheme | Used by | How |
|---|---|---|
| `webSession` cookie | Mini App | `POST /sessions` with Telegram `initData`; the server verifies the HMAC and `auth_date`, checks group membership through the bot and issues a short session |
| `probeToken` bearer | PC, Android and cross-server probes | obtained once via `POST /probe/enroll` with a single-use code |

Roles: **member** (group member) and **admin** (configured Telegram IDs). Member responses are a
strict projection; a member calling any `/admin/*` route receives `403 MEMBERSHIP_REQUIRED`-style
problems, never partial data.

## Routes

| Method & path | Who | Purpose |
|---|---|---|
| `POST /sessions` | anyone with valid initData | start a session |
| `DELETE /sessions/current` | member | end the session |
| `GET /status` | member | overall state, freshness, coverage, `mode`, recommended server, note, server cards |
| `GET /servers/{serverId}` | member | details: checks by source, protocols (AWG / Xray separately), components, resources, profiles, service checks |
| `GET /servers/{serverId}/metrics?period=24h\|7d` | member | availability + connection series; `state=unknown` points render as gaps |
| `GET /events?filter=all\|problems\|notes&cursor&limit` | member | paginated event history with i18n `title_key` + params |
| `GET /help` | member | four step keys, `contact_available`, `contact_url` |
| `GET /admin/servers/{serverId}` | admin | member detail + `attention_items` + diagnostics |
| `GET /admin/probes` | admin | probe list with status, last report, `route_verified`, queue, version |
| `POST /admin/probe-enrollments` | admin | single-use enrollment code (shown once) |
| `POST /admin/probes/{probeId}/revoke` | admin | revoke a device token |
| `PUT /admin/note`, `DELETE /admin/note` | admin | note shown above the server list |
| `POST /probe/enroll` | probe | exchange code for token + config |
| `GET /probe/config` | probe | targets and checks the token may run |
| `POST /probe/reports` | probe | idempotent report (`duplicate: true` on replay) |
| `POST /analytics/events:batch` | member, probe | allowlisted product events |
| `GET /health/live`, `GET /health/ready` | operator | liveness; readiness with per-dependency `ok` and `age_seconds` |

## How the UI uses it

The screen-by-screen mapping (fields, states, analytics events, i18n keys) is maintained in the
project's UI-to-contract map; the essentials:

- **Status**: `state` → headline; `servers[].state` → ring; `sources[]` → the three dots;
  `uptime_24h: null` → `—`; `mode = demo` → permanent "Demo data" mark; `servers = []` → "being
  set up".
- **Server**: `protocols[]` with `connections: null` for unknown Xray → `—`; `checks[]` → the
  Checks group; `components`, `profiles`, `service_checks`, `resources` → the remaining groups.
- **Events**: `title_key` + `params` are rendered through the RU/EN dictionaries; `kind = note`
  and `severity` drive the filters.
- **Admin**: `attention_items` sorted by severity, `/admin/probes`, `/health/ready` → doctor
  summary built on the client.

## Sessions and language

`POST /sessions` sets the cookie; `GET /sessions/current` tells the client its role (member or
admin) so the Admin tab is shown only when it will work. Server names, the administrator note and
doctor hints come back in the language of `Accept-Language` (`ru` or `en`).

## Trying it locally

`python -m vpnpulse.dev` serves every route above on the demo scenarios of
`fixtures/ui/scenarios.json` (see the quick start). Server names and the administrator note come
back in the language of `Accept-Language` (`?lang=` in the dev server); formalising this header in
the contract is on the list for the SQLite read model. `tests/test_dev_server.py` validates each
route for each scenario and role against the OpenAPI schemas, and `scripts/ui_parity_check.py`
renders every screen of the Mini App from the API and from the scenarios and compares the DOM.

## Compatibility rules

- New fields are optional; enums only grow; `minItems` only shrinks.
- Anything a member might see goes through the member projection tests before release.
- Contract tests live in `tests/test_contract_ui_v4.py` and `tests/test_api.py`.
