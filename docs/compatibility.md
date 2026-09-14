# Compatibility

## Monitoring host (planned installer)

| Component | Supported | Notes |
|---|---|---|
| OS | Ubuntu 22.04 / 24.04 LTS, Debian 12 | systemd required |
| Python | 3.12+ | the package declares `requires-python = ">=3.12"` |
| Database | SQLite (bundled) | single small host; no external DB |
| Reverse proxy | Caddy 2 (auto-HTTPS) | any proxy that terminates TLS works |
| Resources | 1 vCPU, 512 MB RAM, 2 GB disk | comfortably enough for a handful of servers |

## VPN servers (collectors)

| Type | What is observed | Requirements |
|---|---|---|
| `awg-host` | AmneziaWG kernel module interface on the host | read-only helper user, `awg`/`wg` tools |
| `awg-docker` | AmneziaWG inside a Docker container (Amnezia default) | read-only helper user with access to `docker exec … wg show` through a restricted wrapper |
| `hiddify` | Hiddify Manager (Xray) plus optional AmneziaWG | read access to the panel's data; connections reported per protocol |

The collector never changes server configuration and never needs root for steady state.

## Probes

| Probe | Platform | Status |
|---|---|---|
| PC | Linux VM (bridged network) or a dedicated small Linux box; isolated network namespaces per target | planned |
| Android | Android 10+; the app must be excluded from the VPN client via split tunneling; cellular data | planned |
| Cross-server | runs on each VPN server; AmneziaWG test key with narrow `AllowedIPs` | planned |

## Telegram

- Mini App inside Telegram for Android, iOS, Desktop and Web; `initData` verification;
  BackButton and theme parameters are used when available.
- The bot must be a member (preferably an administrator) of the group whose members may open
  the app; membership is checked with `getChatMember`.

## Browsers (Mini App)

Chromium 110+, Safari 16+, Firefox 115+. The prototypes were verified in Chromium from
320 × 568 to 1280 × 800, light and dark themes, RU/EN, 200 % text scaling and reduced motion.

## Languages

Russian and English. Server names come from the configuration, so any script works there.
