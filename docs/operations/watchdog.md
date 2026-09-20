# Independent watchdog

The watchdog answers one question from a different host: is the VPN Pulse application itself
still ready? It does not inspect or change VPN traffic and does not run Telegram `getUpdates`.

Install `deploy/watchdog/` on another systemd host:

```bash
sudo sh deploy/watchdog/install-watchdog.sh
sudo install -m 0600 -o vpn-pulse-watchdog -g vpn-pulse-watchdog config /etc/vpn-pulse-watchdog/config
sudo install -m 0600 -o vpn-pulse-watchdog -g vpn-pulse-watchdog bot.token /etc/vpn-pulse-watchdog/bot.token
sudo systemctl start vpn-pulse-watchdog.service
```

Start from `config.example`. The timer checks `/api/v1/health/ready` every minute with a ten-second
deadline and refuses redirects. After three consecutive failures, or five minutes of a non-ready
response, it sends the administrator one audible Telegram message. It sends one recovery message
when readiness returns. A continuing incident may be repeated after six hours.

State lives in `/var/lib/vpn-pulse-watchdog/state.json`; configuration and the bot-token copy live
in `/etc/vpn-pulse-watchdog/` with mode `0600`. Logs contain only `ok`, a short failure category,
`alert`, or `recovered`. They contain no token, URL, response body, host address, or port.

Check or remove it with:

```bash
systemctl list-timers 'vpn-pulse-watchdog*'
journalctl -u vpn-pulse-watchdog -n 20
sudo systemctl disable --now vpn-pulse-watchdog.timer
sudo rm /etc/systemd/system/vpn-pulse-watchdog.service /etc/systemd/system/vpn-pulse-watchdog.timer /usr/local/bin/vpn-pulse-watchdog
sudo systemctl daemon-reload
```
