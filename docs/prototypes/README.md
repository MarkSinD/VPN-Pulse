# VPN Pulse — interactive UI prototypes

Self-contained HTML prototypes of the VPN Pulse interfaces. Open any file in a browser —
no server, no network, no secrets. All data is fictional fixtures.

| File | What it is |
|---|---|
| `mvp.html` | Telegram Mini App v5: Status → Server, Events, Profiles, Help, Admin |
| `android.html` | the Android probe app: enroll → exclude from VPN → cellular check → run |
| `onboarding.html` | first-run walkthrough for documentation: demo mode, clean install, partial coverage, doctor |
| `ui-tokens.css` | shared design tokens: spacing, radius, type scale, the near-black / iOS-grouped palette, materials (`--metal`, `--card-edge`, `--panel-inset`, engraved lines), motion |
| `../../web/src/` | sources: `app.js` (renderer), `model.js` (view model from API or scenarios), `api.js` (contract client), `app.css`, `android.*`, `icons.svg`, templates |
| `../../fixtures/ui/scenarios.json` | the demo scenarios — shared by the prototypes and the dev server (`python -m vpnpulse.dev`) |

## Showcase controls

The dark dashed bar at the top is a demo tool, **not part of the product**. It switches the
scenario, role (member/admin), theme and 200% text. The same is available through URL parameters:

```text
mvp.html?scenario=unavailable&role=admin&theme=dark&lang=en&screen=server:s2&showcase=hidden
android.html?state=running&lang=en&theme=dark&showcase=hidden
```

Scenarios: `loading`, `operational`, `degraded`, `unavailable`, `unknown`, `offline`, `auth`,
`empty_events`, `long_note`, `conflict`, `demo`, `clean_install`, `partial_coverage`, `no_pc`.
Screens: `status`, `events`, `keys`, `help`, `admin`, `server:s1..s3`.

## Design rules encoded here

- One glance, one answer: overall state, recommended server and data freshness first.
- A server row is one button; tapping it opens a separate Server screen. Back restores list
  position and focus.
- State is shown by the ring color **and** by a word; `unknown` is never drawn as a green 100%.
- The ring is a gauge: a 300° scale open at the bottom, engraved ticks, the country flag in the
  centre (inline SVG keyed by the server's `cc`, never emoji) and the code in the gap. Arc length is
  the 24-hour availability, colour is the state, a dashed arc means no data; a ✕ / ! badge repeats
  the state for colour-blind users.
- Instrument-panel materials, one accent: the palette is the product's own (near-black glass with
  `#1c1c1e` cards in dark, `#f2f2f7` with white cards in light — the tones iPhone users already
  know); Telegram only decides light vs dark. Green / amber / red / grey are
  reserved for states; the interface accent is silver. Two font weights (400 and 700), body
  line-height 1.5. Every text pair is ≥ 4.5:1 and every control boundary ≥ 3:1 — checked by
  `scripts/check_contrast.py`.
- Check sources are dynamic: a source exists only after its probe's first accepted report
  (`/status.sources`). The legend plate shows each existing source as a lamp — green = reporting,
  hollow = enrolled but silent — and disappears when there are none; rows and the server's
  "Checks" group list only existing sources. Members are never warned about missing probes; the
  administrator sees them under Probes. Labels sit under the icons in the plate and inside the rows
  only in the wide layout (≥ 1024 px).
- Three check sources: 💻 full VPN check from a computer inside the country, 📶 mobile network
  outside the VPN, 🌍 cross-check from another server abroad.
- User screens never show IPs, domains, ports or hosting providers.
- Strings come from `i18n/ru.json` and `i18n/en.json` (inlined at build time).

## Rebuilding

The files here are built from `web/src/`. Edit the sources, not the built files:

```bash
python scripts/build_prototypes.py          # web/src → docs/prototypes
python scripts/check_contrast.py            # after changing ui-tokens.css
python scripts/ui_check.py                  # browser QA matrix (Playwright)
python scripts/ui_parity_check.py           # API render == scenario render, every screen
```

## Data source

`mvp.html` is the real Mini App. Opened as a file it renders the inlined demo scenarios; served by
the dev server (`python -m vpnpulse.dev`, then <http://127.0.0.1:8765/app/mvp.html>) or inside
Telegram it reads the API through `web/src/api.js` — the same screens, the same DOM (checked by
`scripts/ui_parity_check.py`). `?data=fixtures` / `?data=api` forces a source; in API mode the
showcase bar is hidden unless the page is opened with `?showcase=visible` — then it switches
scenarios by asking the dev server (`?scenario=`) — and the 7-day range shows real 7-day metrics.
Inside Telegram the page loads `telegram-web-app.js` from its own origin (a vendored copy of
Telegram's script, `web/vendor/`): that is what hands the page the signed `initData`.
