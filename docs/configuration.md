# Configuration

The public configuration file is `config.yaml`, validated against
[`contracts/config.schema.json`](../contracts/config.schema.json). A complete example is
[`contracts/config.example.yaml`](../contracts/config.example.yaml). **Secrets are never in this
file** — the Telegram bot token, collector keys and probe tokens live in separate files with
`0600` permissions (see [privacy.md](privacy.md)).

Validation errors name the JSON path and the rule that failed; the service refuses to start on
an invalid file. Changing the file requires a restart of the API and the collector.

[Русская версия](configuration.ru.md)

## `version`

| Field | Type | Default | Notes |
|---|---|---|---|
| `version` | const `1` | — | schema version of the file |

## `app`

| Field | Type | Default | Notes |
|---|---|---|---|
| `default_language` | `ru` \| `en` | — | the language the Mini App opens in, the bot answers in and the notifications use; a visitor's own choice (the switch in the header) is remembered on their device. The phone's or Telegram's language setting is not consulted |
| `languages` | list of `ru` \| `en` | — | enabled languages; the UI switch shows only these |
| `timezone` | IANA name | `UTC` | used for event grouping and note expiry display |
| `admin_contact_url` | `https://t.me/…` | — | target of the "Contact administrator" button; omit to hide the button |
| `public_url` | `https://…` | — | where the Mini App is served (`https://<domain>/app/mvp.html`); the bot's `/start` button points here |

## `storage` (optional)

| Field | Type | Default | Notes |
|---|---|---|---|
| `database` | path | `./vpnpulse.sqlite3` | the SQLite file shared by the API and `vpn-pulse run`; `vpn-pulse init` creates it |
| `collectors_file` | path | — | the private collectors map ([`contracts/collectors.schema.json`](../contracts/collectors.schema.json)): hosts, users, key and pinned-host-key paths; `vpn-pulse collector keygen` writes `secrets/collectors.yaml` and sets this field. Relative paths are resolved from the config file's directory |

## `telegram` (optional)

Without this block `vpn-pulse run` prints the messages it would send instead of delivering them.

| Field | Type | Default | Notes |
|---|---|---|---|
| `bot_token_file` | path | — | a `0600` file holding the bot token; the token itself is never in `config.yaml` |
| `group_chat_id` | string or integer | — | the members' chat: confirmed outages and recoveries |
| `admin_chat_id` | string or integer | the group | unconfirmed problems and data gaps, sent silently |

## `servers[]`

May be **empty** right after installation — the UI then shows "Monitoring is being set up"
and the administrator sees the next command.

| Field | Type | Default | Notes |
|---|---|---|---|
| `id` | `^[a-z][a-z0-9-]{1,63}$` | — | public id used in the API and analytics; never a hostname |
| `type` | `awg-host` \| `awg-docker` \| `hiddify` | — | which collector helper is used |
| `name.ru`, `name.en` | 1–80 chars | — | display names shown to members |
| `country_code` | ISO 3166-1 alpha-2 | — | flag and country name in the UI |
| `enabled` | boolean | — | disabled servers are not collected or shown |
| `recommended_priority` | integer ≥ 0 | `0` | tie-breaker among equally confirmed servers; lower wins |
| `collector_ref` | string | — | the entry in the collectors map that reads this server (`collector-<id>` by default); no host or credential here |

Sensitive: none of these fields is secret; the hosts and key paths behind `collector_ref` live in
the collectors map next to the secrets.

## `monitoring`

| Field | Type | Default | Notes |
|---|---|---|---|
| `collection_interval_seconds` | 30–3600 | `60` | how often the collector asks each server |
| `pc_target_interval_seconds` | 60–3600 | `60` | how often the PC probe tests each target |
| `probe_deadline_seconds` | 5–120 | `20` | a full check must finish within this budget |
| `confirmations` | 2–5 | `2` | consecutive results needed to change public state |
| `freshness_seconds` | 60–3600 | `180` | evidence older than this cannot confirm `operational` |

## `retention`

| Field | Type | Default | Notes |
|---|---|---|---|
| `observations_days` | 1–30 | `7` | raw evidence |
| `aggregates_days` | 7–365 | `90` | availability and connection series |
| `events_days` | 30–730 | `180` | member-visible events |
| `analytics_raw_days` | 1–90 | `30` | product analytics before aggregation |
| `audit_days` | 30–730 | `365` | administrator actions |

## Example

```yaml
version: 1
app:
  default_language: en
  languages: [en, ru]
  timezone: UTC
  admin_contact_url: https://t.me/example_admin
storage:
  database: /var/lib/vpn-pulse/vpnpulse.sqlite3
telegram:
  bot_token_file: /etc/vpn-pulse/secrets/telegram-bot.token
  group_chat_id: "-1001234567890"
servers:
  - id: primary-vpn
    type: awg-host
    name: { ru: Основной сервер, en: Primary server }
    country_code: NL
    enabled: true
    recommended_priority: 10
    collector_ref: collector-primary
monitoring:
  collection_interval_seconds: 60
  pc_target_interval_seconds: 60
  probe_deadline_seconds: 20
  confirmations: 2
  freshness_seconds: 180
retention:
  observations_days: 7
  aggregates_days: 90
  events_days: 180
  analytics_raw_days: 30
  audit_days: 365
```
