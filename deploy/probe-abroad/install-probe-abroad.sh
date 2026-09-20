#!/bin/sh
# install-probe-abroad.sh — put the cross-server probe on this host (root): the namespace, the
# directories, the agent, the unit and the timer (enabled, not started). `--remove` takes it away and
# keeps the profiles and the state. Idempotent; existing files are backed up next to themselves.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 2; }
if [ "${1:-}" = "--remove" ]; then
  systemctl disable --now vpn-pulse-probe-abroad.timer 2>/dev/null || true
  rm -f /etc/systemd/system/vpn-pulse-probe-abroad.service /etc/systemd/system/vpn-pulse-probe-abroad.timer /usr/local/bin/vpn-pulse-probe-abroad
  ip netns delete vpprobe 2>/dev/null || true
  systemctl daemon-reload; echo "removed; configuration and state kept"; exit 0
fi
backup() { [ ! -e "$1" ] || cp -a "$1" "$1.bak-$(date -u +%Y%m%dT%H%M%SZ)"; }
for f in /usr/local/bin/vpn-pulse-probe-abroad /etc/systemd/system/vpn-pulse-probe-abroad.service /etc/systemd/system/vpn-pulse-probe-abroad.timer; do backup "$f"; done
install -d -m 0700 /etc/vpn-pulse-probe /etc/vpn-pulse-probe/peers /etc/vpn-pulse-probe/keys
install -d -m 0700 /var/lib/vpn-pulse-probe
install -m 0755 "$HERE/vpn-pulse-probe-abroad" /usr/local/bin/vpn-pulse-probe-abroad
install -m 0644 "$HERE/vpn-pulse-probe-abroad.service" /etc/systemd/system/
install -m 0644 "$HERE/vpn-pulse-probe-abroad.timer" /etc/systemd/system/
ip netns list | grep -q '^vpprobe\b' || ip netns add vpprobe
systemctl daemon-reload
systemctl enable vpn-pulse-probe-abroad.timer
echo "installed; add config, peer profiles and token, then start the timer"
