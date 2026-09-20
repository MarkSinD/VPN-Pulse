#!/bin/sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
USER_NAME=vpn-pulse-watchdog
CONFIG_DIR=/etc/vpn-pulse-watchdog

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 2; }
for file in vpn-pulse-watchdog vpn-pulse-watchdog.service vpn-pulse-watchdog.timer; do
  [ -f "$HERE/$file" ] || { echo "missing $HERE/$file" >&2; exit 2; }
done
if ! id "$USER_NAME" >/dev/null 2>&1; then
  useradd --system --home-dir /var/lib/vpn-pulse-watchdog --shell /usr/sbin/nologin "$USER_NAME"
fi
install -d -m 0700 -o "$USER_NAME" -g "$USER_NAME" "$CONFIG_DIR"
for target in /usr/local/bin/vpn-pulse-watchdog /etc/systemd/system/vpn-pulse-watchdog.service /etc/systemd/system/vpn-pulse-watchdog.timer; do
  if [ -f "$target" ]; then cp -a "$target" "$target.bak-$(date +%F)"; fi
done
install -m 0755 -o root -g root "$HERE/vpn-pulse-watchdog" /usr/local/bin/vpn-pulse-watchdog
install -m 0644 -o root -g root "$HERE/vpn-pulse-watchdog.service" /etc/systemd/system/vpn-pulse-watchdog.service
install -m 0644 -o root -g root "$HERE/vpn-pulse-watchdog.timer" /etc/systemd/system/vpn-pulse-watchdog.timer
systemctl daemon-reload
systemctl enable --now vpn-pulse-watchdog.timer
echo "installed; create $CONFIG_DIR/config and $CONFIG_DIR/bot.token as $USER_NAME with mode 0600"
