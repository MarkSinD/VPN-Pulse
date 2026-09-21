# Performance baseline

Measured 2026-09-21. The local run uses the seven-day demo scenario and 200 requests per read
endpoint after session creation. Probe write latency uses 100 reports.

| Local measurement | p50 | p95 | Budget |
|---|---:|---:|---:|
| `GET /status` | 5.33 ms | 6.83 ms | 300 ms |
| `GET /servers/{id}` | 5.71 ms | 7.82 ms | recorded |
| `GET /servers/{id}/metrics?period=7d` | 8.35 ms | 10.94 ms | recorded |
| `GET /events` | 6.01 ms | 8.26 ms | recorded |
| Probe report write | 0.08 ms | 0.14 ms | 100 ms |

The Mini App HTML plus the Telegram bridge is 300,149 bytes uncompressed and 66,286 bytes as the
sum of individual gzip payloads (budget: 350 KiB gzip). `scripts/perf_check.py` reproduces these
measurements and exits non-zero on a budget failure.

The production host measurements below use read-only process, HTTPS and filesystem inspection.
The browser cold-load baseline uses ten fresh Playwright pages and waits for
`body[data-load="ready"]` (budget: 2.5 seconds).

| Browser measurement | p50 | p95 | Budget |
|---|---:|---:|---:|
| Cold load, 10 fresh pages | 171.7 ms | 360.3 ms | 2,500 ms |

| Production read-only measurement | Result |
|---|---:|
| API service RSS | 59.4 MiB |
| Collector service RSS | 46.8 MiB |
| Bot service RSS | 24.3 MiB |
| HTTPS `/api/v1/status`, 20 requests, p50 | 326.0 ms |
| HTTPS `/api/v1/status`, 20 requests, p95 | 444.8 ms |
| SQLite file | 15.8 MiB |

The production HTTPS figure includes the executor-to-host network path and exceeded the 300 ms API
budget; the same endpoint's local application p95 was 6.83 ms. This is retained as a baseline for
network investigation rather than prompting an unmeasured application rewrite. A full 24-hour
database comparison was unavailable: the retained backup series covered 7.6 hours and grew from
6.16 MiB to 8.82 MiB. Re-run after a full daily pair exists.
