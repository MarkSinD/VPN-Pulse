# Security evidence

This matrix maps the threat model to executable evidence or an explicit deployment decision.

| ID | Threat and mechanism | Evidence | Status |
|---|---|---|---|
| T01 | Forged or stale Telegram data: HMAC, TTL and constant-time comparison | `tests/test_api.py::test_forged_hash_is_rejected`, `test_changed_signed_user_is_rejected`, `test_expired_and_tampered_init_data_are_rejected` | covered |
| T02 | Former member retains access: membership check and short sessions | `tests/test_store.py::test_session_survives_a_restart_and_can_be_revoked` | covered |
| T03 | Member reaches administrator projection: server-side RBAC | `tests/test_api.py::test_member_cannot_read_admin_projection` | covered |
| T04 | ID enumeration: authorization precedes lookup and unknown probe IDs share one response | `tests/test_api.py::test_unknown_probe_ids_have_the_same_response` | covered |
| T05 | Stolen probe token: hashed token, capability scope and revocation | `tests/test_api.py::test_admin_can_enroll_report_and_revoke_probe` | covered |
| T06 | Replayed report: UUID idempotency and payload hash conflict | `tests/test_api.py::test_admin_can_enroll_report_and_revoke_probe` | covered |
| T07 | Old report replaces current state: ordering by observation time | `tests/test_store.py::test_late_report_does_not_rewrite_newer_evidence` | covered |
| T08 | Config command injection: typed config and fixed SSH command | `tests/test_ssh_collector.py::test_map_rejects_bad_entries_without_echoing_secrets` | covered |
| T09 | VPN secrets reach storage or logs: helper sanitization and secret canary | `tests/test_helper_sh.py::test_dump_prints_ages_and_counters_but_never_keys_endpoints_or_ports` | covered |
| T10 | Note XSS/control characters: controls rejected and all note markup DOM-escaped | `tests/test_api.py::test_admin_note_rejects_control_characters`, `test_note_markup_is_escaped_by_the_dom_renderer` | covered |
| T11 | Cross-site write: SameSite cookie plus exact Origin check | `tests/test_api.py::test_cross_site_origin_is_rejected_for_writes`, `test_same_site_origin_reaches_handler` | covered |
| T12 | Enrollment brute force: 128-bit one-use code, ten-minute TTL, 20/minute bucket | `tests/test_api.py::test_session_rate_limit_returns_retry_after`, `tests/test_store.py::test_enrollment_is_single_use_and_expires` | covered |
| T13 | Identity leaks through analytics: allowlist and schema rejection | `tests/test_api.py::test_analytics_rejects_identity_field` | covered |
| T14 | Database loss: online backup, integrity verification and restore drill | `tests/test_cli_backup.py::test_restore_into_empty_directory_and_permissions` and `docs/operations/backup-restore.md` | covered |
| T15 | Monitoring changes VPN state: no control route and fixed read-only helper | `tests/test_api.py::test_runtime_route_surface_matches_openapi_contract` | covered |
| T16 | Dependency compromise: hashed lock, audit and CycloneDX artifact | `.github/workflows/ci.yml` `supply-chain` job | covered |
| T17 | API resource exhaustion: 64 KiB body cap, bounded salted buckets | `test_post_body_over_64_kib_is_rejected_as_problem`, `test_rate_limit_table_is_bounded`, `test_rate_limit_refills_after_window` | covered |
| T18 | Cloudflare origin bypass | n/a: Cloudflare is not used; Caddy is on the same host on ports 80/443 and the API listens only on loopback | n/a |

The only vendored browser dependency is `web/vendor/telegram-web-app.js`. Its source, fetch date and
repeatable update command are recorded in `web/vendor/README.md`; CI rebuilds the public prototypes
and rejects a diff.

Rate-limit identifiers are SHA-256 digests over the client address and a random process salt. The
10,000-entry table is memory-only and evicts least-recently-used keys. Forwarded addresses are trusted
only from a loopback peer.
