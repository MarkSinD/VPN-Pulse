# Vendored third-party files

`telegram-web-app.js` — Telegram's Mini App bridge, unmodified. It defines `window.Telegram.WebApp`
(`initData`, `ready()`, `expand()`, `colorScheme`, `BackButton`, `openTelegramLink()`), which the Mini
App uses to sign in and to follow the client's theme. Telegram documents loading it from
`https://telegram.org/js/telegram-web-app.js`; the copy is served from the app's own origin instead so
the page depends on no third-party host (some networks do not reach telegram.org). The build
(`scripts/build_prototypes.py`) copies it to `docs/prototypes/`, next to `mvp.html`.

Refresh (then rebuild and run the tests):

```bash
curl -sS -o web/vendor/telegram-web-app.js 'https://telegram.org/js/telegram-web-app.js?59'
```

| file | source | fetched |
|---|---|---|
| `telegram-web-app.js` | `https://telegram.org/js/telegram-web-app.js?59` | 2026-09-20 |
