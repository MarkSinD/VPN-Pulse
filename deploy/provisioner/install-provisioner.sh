#!/bin/sh
set -eu

usage() { echo "usage: $0 --public-key 'ssh-ed25519 …' --kind awg-host|awg-docker --config PATH [--clients-table PATH] [--interface NAME] [--container NAME] [--enable-writes] [--dry-run]" >&2; exit 2; }
kind= config= clients= iface=awg0 container= public_key= writes=false dry=false
while [ "$#" -gt 0 ]; do
  case "$1" in
    --kind) kind=${2-}; shift 2;; --config) config=${2-}; shift 2;;
    --clients-table) clients=${2-}; shift 2;; --interface) iface=${2-}; shift 2;;
    --container) container=${2-}; shift 2;; --public-key) public_key=${2-}; shift 2;;
    --enable-writes) writes=true; shift;; --dry-run) dry=true; shift;; *) usage;;
  esac
done
[ "$kind" = awg-host ] || [ "$kind" = awg-docker ] || usage
[ -n "$config" ] && [ -n "$public_key" ] || usage
printf '%s' "$iface$container" | grep -Eq '^[A-Za-z0-9_.-]+$' || usage
printf '%s' "$public_key" | grep -Eq '^ssh-(ed25519|rsa) [A-Za-z0-9+/=]+( .*)?$' || usage
[ "$kind" != awg-docker ] || [ -n "$container" ] || usage
root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
module="$root/src/vpnpulse/provisioner.py"
[ -f "$module" ] || { echo "run from the VPN Pulse source tree" >&2; exit 2; }
live="/usr/bin/awg,set,$iface"
inspect="/usr/bin/awg,show,$iface,dump"
if [ "$kind" = awg-docker ]; then
  live="/usr/bin/docker,exec,$container,awg,set,$iface"
  inspect="/usr/bin/docker,exec,$container,awg,show,$iface,dump"
fi
if [ "$dry" = true ]; then
  echo "would install dedicated forced-command user; kind=$kind; writes=$writes"
  exit 0
fi
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 2; }
id vpnpulse-provisioner >/dev/null 2>&1 || useradd --create-home --shell /bin/sh vpnpulse-provisioner
install -d -m 0755 /usr/local/lib/vpn-pulse-provisioner /etc/vpn-pulse-provisioner
install -m 0644 "$module" /usr/local/lib/vpn-pulse-provisioner/provisioner.py
cat >/usr/local/bin/vpn-pulse-provisioner-root <<'PY'
#!/usr/bin/env python3
import json,os,sys
sys.path.insert(0,"/usr/local/lib/vpn-pulse-provisioner")
from provisioner import ProvisionerError, forced_command
try:
    print(json.dumps(forced_command(sys.argv[1] if len(sys.argv)>1 else os.environ.get("SSH_ORIGINAL_COMMAND","")),separators=(",",":")))
except (ProvisionerError,OSError,ValueError,KeyError) as error:
    print(json.dumps({"ok":False,"error":type(error).__name__},separators=(",",":")))
    raise SystemExit(2)
PY
chmod 0755 /usr/local/bin/vpn-pulse-provisioner-root
cat >/usr/local/bin/vpn-pulse-provisioner-ssh <<'SH'
#!/bin/sh
[ "${SSH_ORIGINAL_COMMAND-}" = vpn-pulse-provisioner ] || exit 2
exec sudo -n /usr/local/bin/vpn-pulse-provisioner-root "$SSH_ORIGINAL_COMMAND"
SH
chmod 0755 /usr/local/bin/vpn-pulse-provisioner-ssh
printf '%s\n' 'vpnpulse-provisioner ALL=(root) NOPASSWD: /usr/local/bin/vpn-pulse-provisioner-root vpn-pulse-provisioner' >/etc/sudoers.d/vpn-pulse-provisioner
chmod 0440 /etc/sudoers.d/vpn-pulse-provisioner
visudo -cf /etc/sudoers.d/vpn-pulse-provisioner >/dev/null
home=$(getent passwd vpnpulse-provisioner | cut -d: -f6)
install -d -o vpnpulse-provisioner -g vpnpulse-provisioner -m 0700 "$home/.ssh"
printf 'restrict,command="/usr/local/bin/vpn-pulse-provisioner-ssh" %s\n' "$public_key" >"$home/.ssh/authorized_keys"
chown vpnpulse-provisioner:vpnpulse-provisioner "$home/.ssh/authorized_keys"
chmod 0600 "$home/.ssh/authorized_keys"
KIND=$kind CONFIG=$config CLIENTS=$clients IFACE=$iface CONTAINER=$container WRITES=$writes LIVE=$live INSPECT=$inspect python3 - <<'PY'
import json,os
live=os.environ["LIVE"].split(",")
value={"kind":os.environ["KIND"],"persistent_config":os.environ["CONFIG"],"writes_enabled":os.environ["WRITES"]=="true","live_command":live,"inspect_command":os.environ["INSPECT"].split(",")}
if os.environ.get("CLIENTS"): value["clients_table"]=os.environ["CLIENTS"]
if os.environ.get("CONTAINER"): value["container"]=os.environ["CONTAINER"]
open("/etc/vpn-pulse-provisioner/config.json","w",encoding="utf-8").write(json.dumps(value,indent=2)+"\n")
PY
chmod 0600 /etc/vpn-pulse-provisioner/config.json
echo "installed; writes_enabled=$writes"
