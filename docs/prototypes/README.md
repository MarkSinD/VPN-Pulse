# VPN Pulse — interactive UI prototypes

Self-contained HTML prototypes of the VPN Pulse interfaces. Open any file in a browser —
no server, no network, no secrets. All data is fictional fixtures.

| File | What it is |
|---|---|
| `mvp.html` | Telegram Mini App v4: Status → Server, Events, Profiles, Help, Admin |
| `android.html` | the Android probe app: enroll → exclude from VPN → cellular check → run |
| `onboarding.html` | first-run walkthrough for documentation: demo mode, clean install, partial coverage, doctor |
| `ui-tokens.css` | shared design tokens (spacing, radius, type scale, Telegram theme colors, motion) |
| `source/` | build sources: `app.js`, `app.css`, `android.js`, `android.css`, `fixtures.json`, `icons.svg`, templates |

## Showcase controls

The dark dashed bar at the top is a demo tool, **not part of the product**. It switches the
scenario, role (member/admin), theme and 200% text. The same is available through URL parameters:

```text
mvp.html?scenario=unavailable&role=admin&theme=dark&lang=en&screen=server:s2&showcase=hidden
android.html?state=running&lang=en&theme=dark&showcase=hidden
```

Scenarios: `loading`, `operational`, `degraded`, `unavailable`, `unknown`, `offline`, `auth`,
`empty_events`, `long_note`, `conflict`, `demo`, `clean_install`, `partial_coverage`.
Screens: `status`, `events`, `keys`, `help`, `admin`, `server:s1..s3`.

## Design rules encoded here

- One glance, one answer: overall state, recommended server and data freshness first.
- A server row is one button; tapping it opens a separate Server screen. Back restores list
  position and focus.
- State is shown by the ring color **and** by a word; `unknown` is never drawn as a green 100%.
- Three check sources: 💻 full VPN check from a computer inside the country, 📶 mobile network
  outside the VPN, 🌍 cross-check from another server abroad.
- User screens never show IPs, domains, ports or hosting providers.
- Strings come from `i18n/ru.json` and `i18n/en.json` (inlined at build time).

## Rebuilding

The prototypes are generated from `source/` by the project's build script
(`scripts/build_mockups.py` in the main repository). Edit the sources, not the built files.
