# Concepts

## Evidence, not opinion

A VPN server can be perfectly healthy from its own point of view — process up, port open —
while nobody in the country can reach it. VPN Pulse therefore never derives a member-facing
state from the server alone. State comes from **evidence**:

| Source | What it proves | Where it runs |
|---|---|---|
| `pc` 💻 | a full VPN handshake and an HTTPS request through the tunnel succeeded | a computer inside the users' country, outside the users' own VPN |
| `mobile` 📶 | carrier DNS and reachability from the mobile network, outside the VPN | an Android phone excluded from the VPN app (split tunneling) |
| `abroad` 🌍 | the server is reachable from another of your servers | your own servers, cross-checking each other |
| `human_activity` | members are actually connected right now | the collector, from aggregate handshake data |
| `collector` | the service process, port and configuration look right on the server | a read-only helper on the server |

A source **exists** only after its probe has delivered its first accepted report. Until then it
is not shown to members at all — not in the legend, not in the rows, not in the server checks —
and it does not count against coverage. You can run with one probe, two or all three; fewer
probes means less evidence, never a worse state. An enrolled probe that stops reporting stays
visible as *silent* until the administrator revokes it. `GET /status` lists the existing sources
in `sources[]`.

## Four states

| State | Meaning | Never means |
|---|---|---|
| `operational` | two fresh successful full checks **or** fresh member connections | — |
| `degraded` | a partial failure: one network, one protocol, DNS, or conflicting sources | "everything is broken" |
| `unavailable` | two consecutive valid full-check failures from a network while regular internet there works | that the server is down — see `abroad` |
| `unknown` | no fresh evidence: probes silent, computer asleep, route not verified | zero, 100 %, or success of any kind |

Zero connected users is **not** a failure. An `unknown` server is drawn with a dashed ring and
a `—` where a current value would be; historical uptime is labelled as history.

## Freshness

Every piece of evidence carries `observed_at` and `fresh_until`. Data older than the
configured freshness window (default 180 s) is stale and cannot confirm `operational`.
Late reports go to history only; they never make the present look fresher than it is.

## Two confirmations

A single failed check makes the administrator's view yellow. Only the second consecutive
failure changes the public state and triggers a notification. Recovery also needs two
successes. This keeps a flaky minute from paging twenty people.

## Recommendation

"Recommended" is put on the server whose work is confirmed by a full check and whose data
is complete. If Xray connections are unknown, that server is not called "the least loaded".
When nothing is confirmed, nothing is recommended — the UI says so.

## Scope

State is tracked per **server × protocol × network**. A mobile-network problem on one server
does not colour the other servers, and a computer-probe failure does not hide that members
are connected — the UI shows a cautious "some checks failed" with the reason.
