#!/bin/sh
# install-helper.sh — put the read-only collector helper on a VPN server (run as root on that server).
#
#   sudo ./install-helper.sh --kind awg-host   --iface awg0 --pubkey "ssh-ed25519 AAAA… vpn-pulse collector"
#   sudo ./install-helper.sh --kind awg-docker --container amnezia-awg --iface awg0 --domain vpn.example.org --pubkey-file collector.pub
#   sudo ./install-helper.sh --remove
#
# What it creates (and --remove takes away again):
#   user `vpnpulse`           no password, home /var/lib/vpn-pulse-helper, shell /bin/sh (needed for the forced command)
#   ~vpnpulse/.ssh/authorized_keys   the collector's public key with command="/usr/local/bin/vpn-pulse-helper",restrict
#   /usr/local/bin/vpn-pulse-helper  unprivileged: system facts → JSON (this repository's deploy/helper/vpn-pulse-helper)
#   /usr/local/bin/vpn-pulse-dump    root-only: the key-free interface view (deploy/helper/vpn-pulse-dump)
#   /etc/sudoers.d/vpn-pulse-helper  `vpnpulse ALL=(root) NOPASSWD: /usr/local/bin/vpn-pulse-dump` — the only privilege
#   /etc/vpn-pulse-helper/config     KIND / IFACE / CONTAINER / DOMAIN
# The VPN itself is not touched: no config edits, no restarts, no keys read by anything but vpn-pulse-dump,
# which strips them before printing. Re-running with new arguments updates the files in place.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
USER_NAME=vpnpulse
HOME_DIR=/var/lib/vpn-pulse-helper
KIND=""; IFACE=awg0; CONTAINER=""; DOMAIN=""; PUBKEY=""; REMOVE=0; DRY=0

usage() { sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; }
while [ $# -gt 0 ]; do
  case "$1" in
    --kind) KIND=$2; shift 2 ;;
    --iface) IFACE=$2; shift 2 ;;
    --container) CONTAINER=$2; shift 2 ;;
    --domain) DOMAIN=$2; shift 2 ;;
    --pubkey) PUBKEY=$2; shift 2 ;;
    --pubkey-file) PUBKEY=$(cat "$2"); shift 2 ;;
    --remove) REMOVE=1; shift ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 2; }
backup() {
  [ -e "$1" ] || return 0
  dest="$1.bak-$(date +%F)"
  [ ! -e "$dest" ] || dest="$dest.$(date +%s).$$"
  cp -a "$1" "$dest"
}

if [ "$REMOVE" -eq 1 ]; then
  echo "removing the collector helper (the VPN is not touched)"
  [ "$DRY" -eq 1 ] && exit 0
  rm -f /etc/sudoers.d/vpn-pulse-helper /usr/local/bin/vpn-pulse-helper /usr/local/bin/vpn-pulse-dump
  rm -rf /etc/vpn-pulse-helper
  if id "$USER_NAME" >/dev/null 2>&1; then userdel -r "$USER_NAME" 2>/dev/null || userdel "$USER_NAME"; fi
  echo "done"; exit 0
fi

case "$KIND" in
  awg-host) ;;
  awg-docker) [ -n "$CONTAINER" ] || { echo "--container is required for awg-docker" >&2; exit 2; } ;;
  *) echo "--kind must be awg-host or awg-docker" >&2; exit 2 ;;
esac
case "$PUBKEY" in
  ssh-ed25519\ *|ecdsa-sha2-*|ssh-rsa\ *) ;;
  *) echo "--pubkey / --pubkey-file must hold one OpenSSH public key (ssh-ed25519 …)" >&2; exit 2 ;;
esac
case "$PUBKEY" in *"
"*) echo "the public key must be a single line" >&2; exit 2 ;; esac
# These values become shell assignments in a root-owned config. Reject shell syntax.
case "$IFACE" in ''|*[!a-zA-Z0-9_.-]*) echo "invalid interface" >&2; exit 2 ;; esac
case "$CONTAINER" in *[!a-zA-Z0-9_.-]*) echo "invalid container" >&2; exit 2 ;; esac
case "$DOMAIN" in *[!a-zA-Z0-9.-]*) echo "invalid domain" >&2; exit 2 ;; esac
for f in vpn-pulse-helper vpn-pulse-dump; do [ -f "$HERE/$f" ] || { echo "missing $HERE/$f" >&2; exit 2; }; done

echo "plan:"
echo "  user $USER_NAME (home $HOME_DIR, shell /bin/sh, no password)"
echo "  authorized_keys: command=\"/usr/local/bin/vpn-pulse-helper\",restrict <your collector key>"
echo "  /usr/local/bin/vpn-pulse-helper (0755), /usr/local/bin/vpn-pulse-dump (0750 root)"
echo "  /etc/sudoers.d/vpn-pulse-helper: $USER_NAME may run vpn-pulse-dump as root, nothing else"
echo "  /etc/vpn-pulse-helper/config: KIND=$KIND IFACE=$IFACE${CONTAINER:+ CONTAINER=$CONTAINER}${DOMAIN:+ DOMAIN=$DOMAIN}"
[ "$DRY" -eq 1 ] && { echo "dry run: nothing was changed"; exit 0; }
command -v visudo >/dev/null 2>&1 || { echo "install sudo first" >&2; exit 2; }
printf '%s\n' "$PUBKEY" | ssh-keygen -lf - >/dev/null 2>&1 || { echo "invalid public key" >&2; exit 2; }
if id "$USER_NAME" >/dev/null 2>&1; then
  [ "$(getent passwd "$USER_NAME" | cut -d: -f6)" = "$HOME_DIR" ] || { echo "existing user has a different home" >&2; exit 2; }
fi
for f in /etc/passwd /etc/shadow /etc/group /etc/gshadow "$HOME_DIR/.ssh/authorized_keys" /usr/local/bin/vpn-pulse-helper /usr/local/bin/vpn-pulse-dump /etc/vpn-pulse-helper/config /etc/sudoers.d/vpn-pulse-helper; do
  backup "$f"
done

if ! id "$USER_NAME" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "$HOME_DIR" --shell /bin/sh "$USER_NAME"
fi
passwd -l "$USER_NAME" >/dev/null 2>&1 || true
chown root:root "$HOME_DIR"; chmod 0755 "$HOME_DIR"
install -d -m 0755 -o root -g root "$HOME_DIR/.ssh"
printf 'command="/usr/local/bin/vpn-pulse-helper",restrict %s\n' "$PUBKEY" > "$HOME_DIR/.ssh/authorized_keys"
chown root:root "$HOME_DIR/.ssh/authorized_keys"; chmod 0644 "$HOME_DIR/.ssh/authorized_keys"

install -m 0755 -o root -g root "$HERE/vpn-pulse-helper" /usr/local/bin/vpn-pulse-helper
install -m 0750 -o root -g root "$HERE/vpn-pulse-dump" /usr/local/bin/vpn-pulse-dump
install -d -m 0755 /etc/vpn-pulse-helper
{
  echo "KIND=$KIND"; echo "IFACE=$IFACE"
  [ -n "$CONTAINER" ] && echo "CONTAINER=$CONTAINER"
  [ -n "$DOMAIN" ] && echo "DOMAIN=$DOMAIN"
  :
} > /etc/vpn-pulse-helper/config
chmod 0644 /etc/vpn-pulse-helper/config
printf '%s ALL=(root) NOPASSWD: /usr/local/bin/vpn-pulse-dump ""\n' "$USER_NAME" > /etc/sudoers.d/vpn-pulse-helper
chmod 0440 /etc/sudoers.d/vpn-pulse-helper
if command -v visudo >/dev/null 2>&1 && ! visudo -cf /etc/sudoers.d/vpn-pulse-helper >/dev/null; then
  rm -f /etc/sudoers.d/vpn-pulse-helper; echo "sudoers line rejected by visudo" >&2; exit 1
fi

echo "self-test as $USER_NAME:"
if out=$(su -s /bin/sh -c /usr/local/bin/vpn-pulse-helper "$USER_NAME" 2>&1); then
  printf '%s\n' "$out" | head -c 400; echo
  case "$out" in *'"errors":[]'*) echo "helper OK" ;; *) echo "helper answered with errors — check sudoers, the interface name or the container" ;; esac
else
  echo "helper failed:"; printf '%s\n' "$out" | tail -5; exit 1
fi
