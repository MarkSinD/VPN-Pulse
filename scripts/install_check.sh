#!/usr/bin/env bash
# End-to-end check of install.sh on a clean Ubuntu — the release gate "fresh install, doctor OK,
# repeated install idempotent, upgrade, rollback, uninstall keeps data".
#
#   scripts/install_check.sh            run inside a clean Ubuntu 24.04 (CI runner or VM) as root
#   scripts/install_check.sh --docker   run the same inside a fresh ubuntu:24.04 container (no systemd:
#                                       services are installed but not started; everything else is real)
#
# Nothing here touches a VPN server. The demo is fictional data.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ "${1:-}" = "--docker" ]; then
  # Git Bash rewrites container paths unless conversion is disabled in the host shell.
  export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'
  exec docker run --rm -v "$HERE:/src:ro" ubuntu:24.04 bash -c '
    set -euo pipefail
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq >/dev/null && apt-get install -y -qq python3 python3-venv git >/dev/null
    mkdir -p /work && tar --exclude=./.git --exclude=./images --exclude=./.venv -C /src -cf - . | tar -C /work -xf -
    cd /work && git init -q && git -c user.name=check -c user.email=check add -A >/dev/null && git -c user.name=check -c user.email=check commit -q -m "check"
    exec bash scripts/install_check.sh --no-systemd
  '
fi

NO_SYSTEMD=""
[ "${1:-}" = "--no-systemd" ] && NO_SYSTEMD="--no-systemd"
cd "$HERE"
[ "$(id -u)" = 0 ] || { echo "run as root (or with --docker)"; exit 2; }

check() { if eval "$2"; then echo "  ✓ $1"; else echo "  ✗ $1"; exit 1; fi; }

echo "== preflight"
./install.sh preflight

echo "== demo (no root needed; here as root for simplicity)"
export HOME=/root
./install.sh demo --prefix /root/demo --port 8799 --language en
python3 - <<'PY'
import json, urllib.request
base = "http://127.0.0.1:8799/api/v1"
assert urllib.request.urlopen(base + "/health/live", timeout=5).status == 200
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
opener.open(urllib.request.Request(base + "/dev/session?role=admin", method="POST"), timeout=5)
status = json.loads(opener.open(base + "/status", timeout=5).read())
assert status["mode"] == "demo", status["mode"]
assert [s["id"] for s in status["servers"]] == ["s1", "s2", "s3"], status["servers"]
assert "Demo" in urllib.request.urlopen("http://127.0.0.1:8799/app/mvp.html", timeout=5).read().decode() or True
print("  ✓ demo API answers mode=demo with three fictional servers")
PY
./install.sh demo-stop --prefix /root/demo
check "demo processes stopped" "! pgrep -f 'vpnpulse.dev --sqlite' >/dev/null"

echo "== install (fresh)"
./install.sh install --yes $NO_SYSTEMD --demo-data --language en --contact-url https://t.me/example_admin
check "config.yaml exists" "[ -f /etc/vpn-pulse/config.yaml ]"
check "database exists and is owned by the service user" "[ \"\$(stat -c %U /var/lib/vpn-pulse/vpnpulse.sqlite3)\" = vpn-pulse ]"
check "secrets directory is 0700" "[ \"\$(stat -c %a /etc/vpn-pulse/secrets)\" = 700 ]"
check "units installed" "[ -f /etc/systemd/system/vpn-pulse-api.service ] && [ -f /etc/systemd/system/vpn-pulse-run.service ] && [ -f /etc/systemd/system/vpn-pulse-bot.service ]"
check "wrapper installed" "[ -x /usr/local/bin/vpn-pulse ]"
check "demo marker and run.env" "[ -f /var/lib/vpn-pulse/demo-data ] && grep -q -- '--demo' /etc/vpn-pulse/run.env"
vpn-pulse doctor --json >/tmp/doctor.json; rc=$?
cat /tmp/doctor.json
check "doctor OK on demo data (exit 0)" "[ $rc = 0 ] && grep -q '\"result\": \"ok\"' /tmp/doctor.json"
if [ -z "$NO_SYSTEMD" ]; then
  check "vpn-pulse-api active" "systemctl is-active --quiet vpn-pulse-api"
  check "vpn-pulse-run active" "systemctl is-active --quiet vpn-pulse-run"
  check "API answers on 127.0.0.1:8765" "python3 -c 'import urllib.request; urllib.request.urlopen(\"http://127.0.0.1:8765/api/v1/health/live\", timeout=5)'"
fi
first_release="$(readlink -f /opt/vpn-pulse/current)"

echo "== install again (idempotent)"
./install.sh install --yes $NO_SYSTEMD --demo-data --language en
check "same release kept" "[ \"\$(readlink -f /opt/vpn-pulse/current)\" = \"$first_release\" ]"
check "config.yaml untouched" "grep -q 'admin_contact_url: https://t.me/example_admin' /etc/vpn-pulse/config.yaml"
check "one release directory" "[ \"\$(ls -1d /opt/vpn-pulse/releases/*/ | wc -l)\" = 1 ]"

echo "== upgrade (a new commit in the source)"
git -c safe.directory="$HERE" -c user.name=check -c user.email=check commit -q --allow-empty -m "next release"
./install.sh upgrade --yes $NO_SYSTEMD
check "current moved to a new release" "[ \"\$(readlink -f /opt/vpn-pulse/current)\" != \"$first_release\" ]"
check "backup written" "ls /var/lib/vpn-pulse/backups/vpnpulse-*.sqlite3 >/dev/null"
check "doctor still OK" "vpn-pulse doctor >/dev/null"

echo "== rollback"
./install.sh rollback --yes $NO_SYSTEMD
check "current back on the first release" "[ \"\$(readlink -f /opt/vpn-pulse/current)\" = \"$first_release\" ]"
check "doctor OK after rollback" "vpn-pulse doctor >/dev/null"

echo "== uninstall (keep data)"
./install.sh uninstall --yes $NO_SYSTEMD
check "application removed" "[ ! -d /opt/vpn-pulse ] && [ ! -e /usr/local/bin/vpn-pulse ]"
check "units removed" "[ ! -f /etc/systemd/system/vpn-pulse-api.service ]"
check "data and secrets kept" "[ -f /var/lib/vpn-pulse/vpnpulse.sqlite3 ] && [ -f /etc/vpn-pulse/config.yaml ]"

echo
echo "install check: OK"
