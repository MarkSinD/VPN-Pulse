#!/usr/bin/env bash
# VPN Pulse installer — Ubuntu/Debian with systemd (docs/operations/doctor.md, docs/quickstart.md).
#
#   ./install.sh preflight                 check the machine; changes nothing
#   ./install.sh demo [--prefix DIR]       the Mini App on fictional data, no root, no Telegram
#   ./install.sh demo-stop [--prefix DIR]  stop the demo processes
#   sudo ./install.sh install [...]        system user, venv, config, secrets, units, Caddy, doctor
#   sudo ./install.sh upgrade              new release from this checkout: backup, migrate, restart, doctor (auto-rollback)
#   sudo ./install.sh rollback             previous release back: switch, restart, doctor
#   sudo ./install.sh uninstall [--purge]  remove units and the application; data and secrets stay unless --purge
#
# Every changing command accepts --dry-run (prints the plan) and --yes (no questions). A repeated
# run is idempotent. Secrets never appear in arguments, history, logs or config.yaml: the bot token
# is read from a hidden prompt or a file and written with 0600 by `vpn-pulse init`.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${VPN_PULSE_PREFIX:-/opt/vpn-pulse}"
ETC_DIR="${VPN_PULSE_ETC:-/etc/vpn-pulse}"
DATA_DIR="${VPN_PULSE_DATA:-/var/lib/vpn-pulse}"
SERVICE_USER="${VPN_PULSE_USER:-vpn-pulse}"
UNIT_DIR="${VPN_PULSE_UNIT_DIR:-/etc/systemd/system}"
CADDY_DIR="${VPN_PULSE_CADDY_DIR:-/etc/caddy}"
PORT=8765
KEEP_RELEASES=3
RELEASE_PATHS=(src contracts migrations i18n fixtures docs/prototypes deploy pyproject.toml requirements.lock README.md LICENSE install.sh)

DRY=0; YES=0; NO_SYSTEMD=0; NO_CADDY=0; DEMO_DATA=0; PURGE=0
LANGUAGE=""; TIMEZONE=""; CONTACT_URL=""; DOMAIN=""; GROUP_ID=""; ADMIN_ID=""; TOKEN_FILE=""; TOKEN_STDIN=0
DEMO_PREFIX="${HOME:-/tmp}/.vpn-pulse-demo"; DEMO_PORT=8765

say()  { printf '%s\n' "$*"; }
step() { printf '\n[%s] %s\n' "$1" "$2"; }
ok()   { printf '  OK      %s\n' "$*"; }
warn() { printf '  WARN    %s\n' "$*"; }
fail() { printf '  FAILED  %s\n' "$*" >&2; }
die()  { fail "$*"; exit 2; }
plan() { if [ "$DRY" = 1 ]; then printf '  would:  %s\n' "$*"; return 0; fi; return 1; }

usage() { sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; }

parse_flags() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --dry-run) DRY=1 ;;
      --yes|-y) YES=1 ;;
      --no-systemd) NO_SYSTEMD=1 ;;
      --no-caddy) NO_CADDY=1 ;;
      --demo-data) DEMO_DATA=1 ;;
      --purge) PURGE=1 ;;
      --keep-data) PURGE=0 ;;
      --language) LANGUAGE="$2"; shift ;;
      --timezone) TIMEZONE="$2"; shift ;;
      --contact-url) CONTACT_URL="$2"; shift ;;
      --domain) DOMAIN="$2"; shift ;;
      --group-chat-id) GROUP_ID="$2"; shift ;;
      --admin-chat-id) ADMIN_ID="$2"; shift ;;
      --telegram-token-file) TOKEN_FILE="$2"; shift ;;
      --telegram-token-stdin) TOKEN_STDIN=1 ;;
      --prefix) DEMO_PREFIX="$2"; shift ;;
      --port) DEMO_PORT="$2"; PORT="$2"; shift ;;
      -h|--help) usage; exit 0 ;;
      *) die "unknown option: $1 (see --help)" ;;
    esac
    shift
  done
}

# ---------- environment ----------
PYTHON=""
find_python() {
  local candidate
  for candidate in python3.13 python3.12 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
        PYTHON="$(command -v "$candidate")"; return 0
      fi
    fi
  done
  return 1
}

systemd_running() { [ "$NO_SYSTEMD" = 0 ] && command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; }
# git of the source checkout, also when root reads a checkout owned by another user (CI runners, sudo)
git_src() { command -v git >/dev/null 2>&1 && git -c safe.directory="$SRC_DIR" -C "$SRC_DIR" "$@" 2>/dev/null; }
is_root() { [ "$(id -u)" = 0 ]; }

preflight() {
  local rc=0 os="unknown"
  step "1/7" "Environment"
  if [ -r /etc/os-release ]; then os="$(. /etc/os-release; printf '%s %s' "${NAME:-?}" "${VERSION_ID:-}")"; fi
  case "$os" in
    Ubuntu*|Debian*) ok "OS: $os" ;;
    *) warn "OS: $os — Ubuntu 24.04 LTS is the tested platform" ;;
  esac
  ok "architecture: $(uname -m)"
  if find_python; then
    ok "python: $("$PYTHON" --version 2>&1) at $PYTHON"
    if "$PYTHON" -c 'import venv, ensurepip' 2>/dev/null; then ok "venv + ensurepip available"; else fail "python3-venv is missing (apt install python3-venv)"; rc=2; fi
  else
    fail "python 3.12+ not found (Ubuntu 24.04: apt install python3 python3-venv; older Ubuntu: deadsnakes or pyenv)"; rc=2
  fi
  local free_kb; free_kb="$(df -Pk "${TMPDIR:-/tmp}" 2>/dev/null | awk 'NR==2 {print $4}')"
  if [ -n "$free_kb" ] && [ "$free_kb" -lt 512000 ]; then fail "less than 500 MB free"; rc=2; else ok "disk: $((${free_kb:-0} / 1024)) MB free"; fi
  if systemd_running; then ok "systemd: running"; elif command -v systemctl >/dev/null 2>&1; then warn "systemd: installed but not running here (container?) — install with --no-systemd"; else warn "systemd: not found — install with --no-systemd and run the two processes yourself"; fi
  if command -v caddy >/dev/null 2>&1; then ok "caddy: $(caddy version 2>/dev/null | head -1)"; else warn "caddy: not installed — HTTPS is skipped; see https://caddyserver.com/docs/install"; fi
  if git_src rev-parse --short HEAD >/dev/null; then ok "source: git $(git_src rev-parse --short HEAD)"; else ok "source: $SRC_DIR"; fi
  say ""
  [ "$rc" = 0 ] && say "preflight: OK (nothing was changed)" || say "preflight: FAILED (nothing was changed)"
  return "$rc"
}

# ---------- demo (no root) ----------
demo() {
  step "demo" "Mini App on fictional data at $DEMO_PREFIX"
  find_python || die "python 3.12+ with venv is required"
  mkdir -p "$DEMO_PREFIX"
  if [ ! -x "$DEMO_PREFIX/venv/bin/vpn-pulse" ]; then
    "$PYTHON" -m venv "$DEMO_PREFIX/venv"
    "$DEMO_PREFIX/venv/bin/pip" install -q --disable-pip-version-check --require-hashes -r "$SRC_DIR/requirements.lock" || die "locked dependencies install failed"
    "$DEMO_PREFIX/venv/bin/pip" install -q --disable-pip-version-check --no-deps -e "$SRC_DIR" || die "pip install failed"
    ok "virtual environment created"
  else
    ok "virtual environment kept"
  fi
  local vp="$DEMO_PREFIX/venv/bin/vpn-pulse" cfg="$DEMO_PREFIX/config.yaml"
  if [ ! -f "$cfg" ]; then
    "$vp" init --dir "$DEMO_PREFIX" --language "${LANGUAGE:-ru}" ${CONTACT_URL:+--contact-url "$CONTACT_URL"} >/dev/null
    ok "config.yaml and database created"
  else
    ok "config.yaml kept"
  fi
  if [ ! -f "$DEMO_PREFIX/data/demo-data" ]; then
    "$vp" demo seed --config "$cfg" >/dev/null && ok "demo scenario seeded (three fictional servers, seven days of history)"
  else
    ok "demo data kept"
  fi
  demo_stop quiet
  nohup "$vp" run --demo --config "$cfg" --quiet >"$DEMO_PREFIX/run.log" 2>&1 &
  echo $! >"$DEMO_PREFIX/run.pid"
  nohup "$DEMO_PREFIX/venv/bin/python" -m vpnpulse.dev --sqlite "$DEMO_PREFIX/data/vpnpulse.sqlite3" --scenario demo --port "$DEMO_PORT" >"$DEMO_PREFIX/dev.log" 2>&1 &
  echo $! >"$DEMO_PREFIX/dev.pid"
  local i
  for i in $(seq 1 30); do
    if "$PYTHON" - "$DEMO_PORT" <<'PY' 2>/dev/null; then break; fi
import sys, urllib.request
urllib.request.urlopen(f"http://127.0.0.1:{sys.argv[1]}/api/v1/health/live", timeout=1).read()
PY
    sleep 1
  done
  ok "monitoring loop: pid $(cat "$DEMO_PREFIX/run.pid") (log: $DEMO_PREFIX/run.log)"
  ok "demo API + Mini App: pid $(cat "$DEMO_PREFIX/dev.pid") (log: $DEMO_PREFIX/dev.log)"
  say ""
  say "Open http://127.0.0.1:$DEMO_PORT/app/mvp.html — the 'Demo data' mark stays on; the showcase bar switches role and language."
  say "The world changes every few minutes (10 min fine → 5 min mobile problem → 10 min outage → 15 min recovery)."
  say "Stop with: ./install.sh demo-stop${DEMO_PREFIX:+ --prefix $DEMO_PREFIX}"
}

demo_stop() {
  local f pid stopped=0 i
  for f in run dev; do
    if [ -f "$DEMO_PREFIX/$f.pid" ]; then
      pid="$(cat "$DEMO_PREFIX/$f.pid")"
      if kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true; stopped=1
        for i in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done   # a graceful stop takes a moment
        kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
      fi
      rm -f "$DEMO_PREFIX/$f.pid"
    fi
  done
  [ "${1:-}" = quiet ] || { [ "$stopped" = 1 ] && say "demo stopped" || say "demo was not running"; }
}

# ---------- install / upgrade / rollback / uninstall (root) ----------
as_service_user() { runuser -u "$SERVICE_USER" -- "$@"; }
release_id() {
  local sha; sha="$(git_src rev-parse --short HEAD || true)"
  printf '%s-%s' "$(date -u +%Y%m%d%H%M%S)" "${sha:-src}"
}
current_release() { [ -L "$PREFIX/current" ] && readlink -f "$PREFIX/current" || true; }
source_sha() { git_src rev-parse HEAD || printf 'nogit'; }

ensure_user_and_dirs() {
  step "2/7" "Application"
  if id "$SERVICE_USER" >/dev/null 2>&1; then ok "user $SERVICE_USER exists"; else
    plan "create system user $SERVICE_USER" || { useradd --system --home-dir "$DATA_DIR" --shell /usr/sbin/nologin --user-group "$SERVICE_USER"; ok "user $SERVICE_USER created"; }
  fi
  plan "create $PREFIX/releases, $ETC_DIR/secrets (0700), $DATA_DIR (0750)" || {
    install -d -m 0755 "$PREFIX" "$PREFIX/releases"
    # the service user owns its configuration and data; the units mount /etc/vpn-pulse read-only,
    # so only the administrator's CLI (run as that user) can change it
    install -d -m 0750 -o "$SERVICE_USER" -g "$SERVICE_USER" "$ETC_DIR"
    install -d -m 0700 -o "$SERVICE_USER" -g "$SERVICE_USER" "$ETC_DIR/secrets"
    install -d -m 0750 -o "$SERVICE_USER" -g "$SERVICE_USER" "$DATA_DIR" "$DATA_DIR/backups"
    # a repeated run re-asserts owners and modes without touching contents
    [ -f "$ETC_DIR/config.yaml" ] && { chown "$SERVICE_USER:$SERVICE_USER" "$ETC_DIR/config.yaml"; chmod 0640 "$ETC_DIR/config.yaml"; }
    [ -f "$ETC_DIR/secrets/telegram-bot.token" ] && { chown "$SERVICE_USER:$SERVICE_USER" "$ETC_DIR/secrets/telegram-bot.token"; chmod 0600 "$ETC_DIR/secrets/telegram-bot.token"; }
    ok "directories ready"
  }
}

install_release() {
  # a new release directory with its own venv; `current` is switched by the caller
  local current; current="$(current_release)"
  if [ -n "$current" ] && [ -f "$current/RELEASE" ] && [ "$(sed -n 's/^source=//p' "$current/RELEASE")" = "$(source_sha)" ] && [ "$(source_sha)" != "nogit" ]; then
    ok "release $(basename "$current") already installed from this source"
    NEW_RELEASE="$current"; return 0
  fi
  NEW_RELEASE="$PREFIX/releases/$(release_id)"
  plan "copy the application to $NEW_RELEASE and build its virtual environment" && return 0
  mkdir -p "$NEW_RELEASE"
  local p
  for p in "${RELEASE_PATHS[@]}"; do
    if [ -e "$SRC_DIR/$p" ]; then mkdir -p "$NEW_RELEASE/$(dirname "$p")"; cp -R "$SRC_DIR/$p" "$NEW_RELEASE/$(dirname "$p")/"; fi
  done
  printf 'source=%s\ninstalled=%s\n' "$(source_sha)" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"$NEW_RELEASE/RELEASE"
  "$PYTHON" -m venv "$NEW_RELEASE/venv"
  "$NEW_RELEASE/venv/bin/pip" install -q --disable-pip-version-check --require-hashes -r "$NEW_RELEASE/requirements.lock" || die "locked dependencies install failed (network? see $NEW_RELEASE)"
  "$NEW_RELEASE/venv/bin/pip" install -q --disable-pip-version-check --no-deps -e "$NEW_RELEASE" || die "pip install failed"
  chown -R root:root "$NEW_RELEASE"; chmod -R a+rX "$NEW_RELEASE"
  ok "release $(basename "$NEW_RELEASE") installed"
}

switch_release() {
  local target="$1"
  plan "point $PREFIX/current at $(basename "$target")" || { ln -sfn "$target" "$PREFIX/current.tmp" && mv -Tf "$PREFIX/current.tmp" "$PREFIX/current"; ok "current → $(basename "$target")"; }
}

prune_releases() {
  local keep="$KEEP_RELEASES" r
  ls -1d "$PREFIX"/releases/*/ 2>/dev/null | sort | head -n -"$keep" | while read -r r; do
    [ "$(readlink -f "$r")" = "$(current_release)" ] && continue
    plan "remove old release $r" || { rm -rf "$r"; ok "removed old release $(basename "$r")"; }
  done
}

configure() {
  step "3/7" "Configuration and secrets"
  local vp="$PREFIX/current/venv/bin/vpn-pulse" cfg="$ETC_DIR/config.yaml"
  if [ -f "$cfg" ]; then ok "config.yaml exists — kept (edit it or run vpn-pulse init --force by hand)"; return 0; fi
  if [ "$DRY" = 1 ]; then plan "vpn-pulse init --dir $ETC_DIR --data-dir $DATA_DIR --secrets-dir $ETC_DIR/secrets ${LANGUAGE:+--language $LANGUAGE}"; return 0; fi
  if [ "$YES" = 0 ] && [ -t 0 ]; then
    [ -n "$LANGUAGE" ] || { read -r -p "  Language [ru/en] (ru): " LANGUAGE; LANGUAGE="${LANGUAGE:-ru}"; }
    [ -n "$TIMEZONE" ] || { read -r -p "  Timezone (UTC): " TIMEZONE; TIMEZONE="${TIMEZONE:-UTC}"; }
    [ -n "$DOMAIN" ] || read -r -p "  Mini App domain for Caddy (empty to skip HTTPS now): " DOMAIN
    [ -n "$CONTACT_URL" ] || read -r -p "  Administrator contact link https://t.me/... (empty to hide the button): " CONTACT_URL
    if [ -z "$GROUP_ID" ] && [ -z "$TOKEN_FILE" ] && [ "$TOKEN_STDIN" = 0 ]; then
      read -r -p "  Telegram group chat id (empty to configure Telegram later): " GROUP_ID
      if [ -n "$GROUP_ID" ]; then
        read -r -p "  Administrator Telegram user id (empty: the group): " ADMIN_ID
        TOKEN_PROMPT=1
      fi
    fi
  fi
  local args=(init --dir "$ETC_DIR" --data-dir "$DATA_DIR" --secrets-dir "$ETC_DIR/secrets" --language "${LANGUAGE:-ru}" --timezone "${TIMEZONE:-UTC}")
  [ -n "$CONTACT_URL" ] && args+=(--contact-url "$CONTACT_URL")
  [ -n "$GROUP_ID" ] && args+=(--group-chat-id "$GROUP_ID")
  [ -n "$ADMIN_ID" ] && args+=(--admin-chat-id "$ADMIN_ID")
  if [ -n "$TOKEN_FILE" ]; then
    args+=(--telegram-token-file "$TOKEN_FILE")
    "$vp" "${args[@]}" >/dev/null
  elif [ "$TOKEN_STDIN" = 1 ]; then
    args+=(--telegram-token-stdin)
    "$vp" "${args[@]}" >/dev/null   # the token arrives on our stdin and goes straight through
  elif [ "${TOKEN_PROMPT:-0}" = 1 ]; then
    local token
    read -r -s -p "  Bot token (hidden): " token; say ""
    args+=(--telegram-token-stdin)
    printf '%s\n' "$token" | "$vp" "${args[@]}" >/dev/null   # printf is a builtin: the token never becomes an argument
    unset token
  else
    "$vp" "${args[@]}" >/dev/null
  fi
  chown -R "$SERVICE_USER:$SERVICE_USER" "$ETC_DIR" "$DATA_DIR"
  chmod 0750 "$ETC_DIR"; chmod 0640 "$cfg"; chmod 0700 "$ETC_DIR/secrets"
  [ -f "$ETC_DIR/secrets/telegram-bot.token" ] && chmod 0600 "$ETC_DIR/secrets/telegram-bot.token"
  ok "config.yaml written ($cfg), database created ($DATA_DIR/vpnpulse.sqlite3)"
  if [ -f "$ETC_DIR/secrets/telegram-bot.token" ]; then ok "bot token stored (0600, owner $SERVICE_USER)"; else ok "Telegram not configured yet: messages go to the journal; add it later with vpn-pulse init --force …"; fi
}

demo_data() {
  [ "$DEMO_DATA" = 1 ] || return 0
  local vp="$PREFIX/current/venv/bin/vpn-pulse" cfg="$ETC_DIR/config.yaml"
  if [ -f "$DATA_DIR/demo-data" ]; then ok "demo data present — kept"; else
    plan "seed the demo scenario and set VPN_PULSE_RUN_ARGS=--demo" || {
      as_service_user env VPN_PULSE_CONFIG="$cfg" "$vp" demo seed >/dev/null && ok "demo data seeded (fictional servers; the Mini App shows 'Demo data')"
    }
  fi
  plan "write $ETC_DIR/run.env" || { printf 'VPN_PULSE_RUN_ARGS=--demo\n' >"$ETC_DIR/run.env"; chmod 0644 "$ETC_DIR/run.env"; }
}

caddy_snippet() {
  step "5/7" "HTTPS (Caddy)"
  if [ "$NO_CADDY" = 1 ]; then ok "skipped (--no-caddy)"; return 0; fi
  if [ -z "$DOMAIN" ]; then
    if [ -f "$CADDY_DIR/vpn-pulse.caddy" ]; then ok "existing $CADDY_DIR/vpn-pulse.caddy kept"; else ok "no domain given — run again with --domain monitor.example.org when the DNS record exists"; fi
    return 0
  fi
  local snippet="$CADDY_DIR/vpn-pulse.caddy"
  plan "write $snippet for $DOMAIN and import it from $CADDY_DIR/Caddyfile" && return 0
  if [ ! -d "$CADDY_DIR" ]; then
    mkdir -p "$ETC_DIR/caddy"; snippet="$ETC_DIR/caddy/vpn-pulse.caddy"
    warn "Caddy is not installed: the snippet is written to $snippet — install Caddy and import it"
  fi
  sed "s/{{DOMAIN}}/$DOMAIN/" "$PREFIX/current/deploy/caddy/vpn-pulse.caddy" >"$snippet"
  ok "snippet written: $snippet"
  if [ -f "$CADDY_DIR/Caddyfile" ] && ! grep -q "import $snippet" "$CADDY_DIR/Caddyfile"; then
    printf '\nimport %s\n' "$snippet" >>"$CADDY_DIR/Caddyfile"; ok "import line added to $CADDY_DIR/Caddyfile"
  fi
  if systemd_running && systemctl is-active --quiet caddy 2>/dev/null; then
    if caddy validate --config "$CADDY_DIR/Caddyfile" >/dev/null 2>&1; then systemctl reload caddy && ok "caddy reloaded"; else warn "Caddyfile did not validate — Caddy was not reloaded; check: caddy validate --config $CADDY_DIR/Caddyfile"; fi
  fi
}

services() {
  step "6/7" "Services"
  local u
  for u in vpn-pulse-api vpn-pulse-run vpn-pulse-bot; do
    plan "install $UNIT_DIR/$u.service" || { install -m 0644 "$PREFIX/current/deploy/systemd/$u.service" "$UNIT_DIR/$u.service"; }
  done
  [ "$DRY" = 1 ] && return 0
  ok "units installed: vpn-pulse-api.service, vpn-pulse-run.service, vpn-pulse-bot.service"
  if systemd_running; then
    systemctl daemon-reload
    systemctl enable --quiet vpn-pulse-api.service vpn-pulse-run.service vpn-pulse-bot.service
    if [ "${RESTART_SERVICES:-0}" = 1 ]; then systemctl restart vpn-pulse-api.service vpn-pulse-run.service vpn-pulse-bot.service; else systemctl start vpn-pulse-api.service vpn-pulse-run.service vpn-pulse-bot.service; fi
    sleep 2
    for u in vpn-pulse-api vpn-pulse-run; do
      if systemctl is-active --quiet "$u.service"; then ok "$u: active"; else fail "$u: not active — journalctl -u $u.service -n 50"; return 2; fi
    done
    # the bot listener exits at once without a telegram block: inactive is fine then
    if systemctl is-active --quiet vpn-pulse-bot.service; then ok "vpn-pulse-bot: active"; else ok "vpn-pulse-bot: inactive (Telegram not configured yet, or see journalctl -u vpn-pulse-bot)"; fi
  else
    warn "systemd is not running here: start the processes yourself —"
    say "          VPN_PULSE_CONFIG=$ETC_DIR/config.yaml $PREFIX/current/venv/bin/vpn-pulse serve"
    say "          VPN_PULSE_CONFIG=$ETC_DIR/config.yaml $PREFIX/current/venv/bin/vpn-pulse run $( [ "$DEMO_DATA" = 1 ] && echo --demo )"
  fi
}

doctor() {
  step "7/7" "Doctor"
  [ "$DRY" = 1 ] && { plan "vpn-pulse doctor (as $SERVICE_USER)"; return 0; }
  local rc=0
  as_service_user env VPN_PULSE_CONFIG="$ETC_DIR/config.yaml" "$PREFIX/current/venv/bin/vpn-pulse" doctor || rc=$?
  return "$rc"
}

wrapper() {
  # /usr/local/bin/vpn-pulse: the administrator's commands run as the service user with the installed config
  local w="${VPN_PULSE_BIN:-/usr/local/bin/vpn-pulse}"
  plan "write $w" && return 0
  mkdir -p "$(dirname "$w")"
  cat >"$w" <<EOF
#!/bin/sh
# VPN Pulse — runs the installed CLI as the service user so files keep their owner
if [ "\$(id -u)" = 0 ]; then
  exec runuser -u $SERVICE_USER -- env VPN_PULSE_CONFIG=$ETC_DIR/config.yaml $PREFIX/current/venv/bin/vpn-pulse "\$@"
fi
exec env VPN_PULSE_CONFIG=$ETC_DIR/config.yaml $PREFIX/current/venv/bin/vpn-pulse "\$@"
EOF
  chmod 0755 "$w"
  ok "command installed: $w (sudo vpn-pulse doctor)"
}

summary() {
  say ""
  say "VPN Pulse is installed."
  say "  configuration: $ETC_DIR/config.yaml   data: $DATA_DIR   releases: $PREFIX/releases (current → $(basename "$(current_release)"))"
  [ -n "$DOMAIN" ] && say "  Mini App: https://$DOMAIN/app/mvp.html (once DNS and Caddy are in place)"
  say "  next: sudo vpn-pulse server add …  ·  sudo vpn-pulse probe enroll pc  ·  sudo vpn-pulse doctor"
}

require_root() { [ "$DRY" = 1 ] || is_root || die "run as root: sudo ./install.sh $1"; }

install_cmd() {
  require_root install
  preflight || { [ "$DRY" = 1 ] || die "fix the preflight findings first"; }
  find_python || die "python 3.12+ not found"
  if ! systemd_running && [ "$NO_SYSTEMD" = 0 ] && [ "$DRY" = 0 ]; then die "systemd is not running here; pass --no-systemd to install without services"; fi
  ensure_user_and_dirs
  local previous; previous="$(current_release)"
  install_release
  [ "$DRY" = 1 ] || switch_release "$NEW_RELEASE"
  [ -n "$previous" ] && [ "$previous" != "${NEW_RELEASE:-}" ] && RESTART_SERVICES=1
  wrapper
  configure
  step "4/7" "Demo data"
  if [ "$DEMO_DATA" = 1 ]; then demo_data; else ok "none requested (--demo-data seeds a fictional world for a first look)"; fi
  caddy_snippet
  services || true
  local rc=0
  doctor || rc=$?
  [ "$DRY" = 1 ] && { say ""; say "dry run: nothing was changed"; return 0; }
  prune_releases
  summary
  case "$rc" in
    0) say "  doctor: OK" ;;
    1) say "  doctor: warnings — read them above; the installation works" ;;
    *) say "  doctor: FAILED — the services are installed but something needs attention (see above)" ;;
  esac
  return "$rc"
}

backup_db() {
  local db="$DATA_DIR/vpnpulse.sqlite3" out="$DATA_DIR/backups/vpnpulse-$(date -u +%Y%m%d%H%M%S).sqlite3"
  [ -f "$db" ] || { ok "no database to back up"; return 0; }
  plan "back up $db to $out" && return 0
  as_service_user "$PREFIX/current/venv/bin/python" - "$db" "$out" <<'PY'
import sqlite3, sys
src = sqlite3.connect(sys.argv[1]); dst = sqlite3.connect(sys.argv[2])
with dst: src.backup(dst)
dst.close(); src.close()
PY
  chmod 0600 "$out"
  ok "database backed up to $out"
  ls -1t "$DATA_DIR"/backups/vpnpulse-*.sqlite3 2>/dev/null | tail -n +8 | xargs -r rm -f
}

upgrade_cmd() {
  require_root upgrade
  local previous; previous="$(current_release)"
  [ -n "$previous" ] || die "nothing is installed yet: sudo ./install.sh install"
  step "upgrade" "from $(basename "$previous") to a release built from $SRC_DIR"
  preflight >/dev/null || die "preflight failed (run ./install.sh preflight)"
  find_python || die "python 3.12+ not found"
  install_release
  if [ "${NEW_RELEASE:-}" = "$previous" ]; then ok "already up to date"; return 0; fi
  [ "$DRY" = 1 ] && { plan "back up the database, stop vpn-pulse-run, migrate, switch current, restart, doctor (auto-rollback on failure)"; say ""; say "dry run: nothing was changed"; return 0; }
  backup_db
  if systemd_running; then systemctl stop vpn-pulse-run.service || true; fi
  # migrations are applied by the first command that opens the database with the new code
  as_service_user env VPN_PULSE_CONFIG="$ETC_DIR/config.yaml" "$NEW_RELEASE/venv/bin/vpn-pulse" doctor storage >/dev/null || warn "doctor storage reported findings; continuing"
  switch_release "$NEW_RELEASE"
  RESTART_SERVICES=1 services || true
  local rc=0
  doctor || rc=$?
  if [ "$rc" = 2 ]; then
    fail "doctor reports failures after the upgrade — rolling back to $(basename "$previous")"
    switch_release "$previous"
    RESTART_SERVICES=1 services || true
    doctor || true
    return 2
  fi
  prune_releases
  say ""; say "upgrade done: current → $(basename "$NEW_RELEASE") (previous $(basename "$previous") kept for rollback)"
  return "$rc"
}

rollback_cmd() {
  require_root rollback
  local current previous
  current="$(current_release)"; [ -n "$current" ] || die "nothing is installed"
  previous="$(ls -1d "$PREFIX"/releases/*/ 2>/dev/null | sed 's#/$##' | sort | grep -v -x "$current" | tail -n 1 || true)"
  [ -n "$previous" ] || die "no previous release to roll back to"
  step "rollback" "from $(basename "$current") to $(basename "$previous")"
  [ "$DRY" = 1 ] && { plan "switch current to $(basename "$previous"), restart the services, run doctor"; say ""; say "dry run: nothing was changed"; return 0; }
  say "  the database keeps its schema: migrations are additive, so the previous release reads it"
  switch_release "$previous"
  RESTART_SERVICES=1 services || true
  doctor
}

uninstall_cmd() {
  require_root uninstall
  step "uninstall" "services and application ($( [ "$PURGE" = 1 ] && echo 'data and secrets too' || echo 'data and secrets are kept' ))"
  say "  the VPN servers and their configuration are not touched by anything here"
  if [ "$YES" = 0 ] && [ "$DRY" = 0 ]; then
    read -r -p "  Continue? [y/N] " answer; case "$answer" in y|Y|yes) ;; *) say "nothing changed"; return 1 ;; esac
  fi
  local u
  for u in vpn-pulse-api vpn-pulse-run vpn-pulse-bot; do
    if systemd_running; then plan "stop and disable $u" || { systemctl disable --now --quiet "$u.service" 2>/dev/null || true; }; fi
    plan "remove $UNIT_DIR/$u.service" || rm -f "$UNIT_DIR/$u.service"
  done
  if systemd_running && [ "$DRY" = 0 ]; then systemctl daemon-reload; fi
  if [ -f "$CADDY_DIR/Caddyfile" ] && grep -q "import $CADDY_DIR/vpn-pulse.caddy" "$CADDY_DIR/Caddyfile"; then
    plan "remove the import line from $CADDY_DIR/Caddyfile and $CADDY_DIR/vpn-pulse.caddy" || {
      sed -i "\#import $CADDY_DIR/vpn-pulse.caddy#d" "$CADDY_DIR/Caddyfile"; rm -f "$CADDY_DIR/vpn-pulse.caddy"
      if systemd_running && systemctl is-active --quiet caddy 2>/dev/null; then systemctl reload caddy || true; fi
    }
  fi
  plan "remove $PREFIX and ${VPN_PULSE_BIN:-/usr/local/bin/vpn-pulse}" || { rm -rf "$PREFIX"; rm -f "${VPN_PULSE_BIN:-/usr/local/bin/vpn-pulse}"; }
  if [ "$PURGE" = 1 ]; then
    plan "remove $ETC_DIR and $DATA_DIR" || rm -rf "$ETC_DIR" "$DATA_DIR"
    if id "$SERVICE_USER" >/dev/null 2>&1; then plan "remove user $SERVICE_USER" || userdel "$SERVICE_USER" 2>/dev/null || true; fi
  else
    ok "kept: $ETC_DIR (config, secrets) and $DATA_DIR (database, backups)"
  fi
  [ "$DRY" = 1 ] && { say ""; say "dry run: nothing was changed"; return 0; }
  say "uninstalled"
}

main() {
  local cmd="${1:-}"; [ $# -gt 0 ] && shift
  case "$cmd" in
    preflight) parse_flags "$@"; preflight ;;
    demo) parse_flags "$@"; demo ;;
    demo-stop) parse_flags "$@"; demo_stop ;;
    install) parse_flags "$@"; install_cmd ;;
    upgrade) parse_flags "$@"; upgrade_cmd ;;
    rollback) parse_flags "$@"; rollback_cmd ;;
    uninstall) parse_flags "$@"; uninstall_cmd ;;
    ""|-h|--help|help) usage ;;
    *) die "unknown command: $cmd (see --help)" ;;
  esac
}

main "$@"
