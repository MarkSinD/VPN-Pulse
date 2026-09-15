# VPN Pulse

**Is my self-hosted VPN reachable right now — and which server should I pick?**

VPN Pulse is a Telegram Mini App and bot for people who run a few WireGuard / AmneziaWG
(and optionally Xray) servers for friends and family. It answers one question in three
seconds, backed by evidence rather than by the servers' own opinion:

- 💻 **Computer probe** — a real VPN handshake plus HTTPS through the tunnel, from inside the
  country where your users are.
- 📶 **Mobile probe** — DNS and reachability from a phone on the mobile network, outside the VPN.
- 🌍 **Cross-check from abroad** — your servers check each other, so "blocked in the country"
  and "the server is down" stop looking the same.

Zero connected users is **not** a failure. Missing data is shown as *no data*, never as a
green 100%. Members never see IPs, domains, ports or the hosting provider.

[Русская версия](README.ru.md)

## Status

| Part | State |
|---|---|
| Product & UX specification, design system, RU/EN content | complete |
| API contract (OpenAPI 3.1, JSON Schemas) | v1.1.0, validated in CI |
| Interactive UI prototypes (Mini App, Android probe, first run) | complete — [open them](docs/prototypes/README.md) |
| Backend core: config, SQLite migration, state evaluator, mock-first API, analytics ingestion | tests green (`pytest`) |
| Dev server: every API route on 13 demo scenarios, contract-validated (`python -m vpnpulse.dev`) | working |
| Installer, CLI (`vpn-pulse …`), collectors for real servers, Telegram bot, probes | **planned** — not yet runnable |

There is no one-command install yet. Today the repository is a **developer preview**: you can
run the tests, validate the contracts and click through the prototypes. See
[docs/quickstart.md](docs/quickstart.md).

## What it looks like

| Status screen (degraded) | Server details (dark) |
|---|---|
| ![Status screen, 390 px, one server with a mobile-network issue](docs/images/status-390-degraded.png) | ![Server details, tablet width, dark theme](docs/images/server-768-dark.png) |

Every server is one row: a gauge ring with the flag shows the state (arc = 24-hour availability),
the row shows the three check sources and an availability chart. Tapping a row opens the server screen.

## Five-minute developer preview

```bash
git clone https://github.com/MarkSinD/VPN-Pulse.git
cd VPN-Pulse
python -m venv .venv && . .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m pytest                                  # backend core + contract tests
python scripts/validate_specs.py                  # OpenAPI, schemas, RU/EN parity
python -m vpnpulse.dev                            # API on demo scenarios + the Mini App at /app/
```

Then open <http://127.0.0.1:8765/app/mvp.html> (or `docs/prototypes/mvp.html` directly) and use
the showcase bar to switch scenarios (operational, degraded, unavailable, unknown, offline, clean
install, …), role, theme and language. The same scenarios are served by the API:
`GET /api/v1/status?scenario=unavailable&lang=en` after `POST /api/v1/dev/session?role=admin`.

## Documentation

- [Quick start](docs/quickstart.md) · [Быстрый старт](docs/quickstart.ru.md)
- [Concepts](docs/concepts.md) — states, freshness, sources, recommendation
- [Configuration](docs/configuration.md) · [Конфигурация](docs/configuration.ru.md)
- [Connect a server](docs/connect-server.md) · [PC probe](docs/probes/pc.md) · [Android probe](docs/probes/android.md)
- [User guide](docs/user-guide/status-and-recommendations.md) · [Admin actions](docs/user-guide/admin-actions.md)
- [Architecture](docs/architecture.md) · [API](docs/api.md) · [Privacy](docs/privacy.md) · [Compatibility](docs/compatibility.md)
- [Operations](docs/operations/doctor.md) · [Troubleshooting](docs/troubleshooting.md)
- [Contributing](CONTRIBUTING.md) · [Security policy](SECURITY.md) · [Changelog](CHANGELOG.md)

## Limitations

- Nothing here changes your VPN. Collectors are read-only by design; the app never issues keys.
- Blocking detection is inference from independent checks, not proof. The UI says
  *"connection check failed from the home network"*, and only the administrator sees the
  probable cause.
- One computer probe covers one network. Coverage of other carriers needs more probes.

## License

MIT — see [LICENSE](LICENSE).
