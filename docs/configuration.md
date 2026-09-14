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
| `default_language` | `ru` \| `en` | — | language used before the user's Telegram language is known |
| `languages` | list of `ru` \| `en` | — | enabled languages; the UI switch shows only these |
| `timezone` | IANA name | `UTC` | used for event grouping and note expiry display |
| `admin_contact_url` | `https://t.me/…` | — | target of the "Contact administrator" button; omit to hide the button |

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
| `collector_ref` | string | — | reference to the collector credential file (not the credential itself) |

Sensitive: none of these fields is secret, but `collector_ref` points to one.

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
