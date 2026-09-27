#!/bin/sh
# Manual R-17 check: one userspace AmneziaWG tunnel in an isolated namespace.
set -eu

PROFILE=${1:?usage: pc-check.sh PROFILE TARGET_ID EXPECTED_EXIT_IP [NAMESPACE]}
TARGET_ID=${2:?target id required}
EXPECTED_EXIT=${3:?expected VPN exit address required}
NS=${4:-pc-$TARGET_ID}
AWG_GO=${AWG_GO:-/opt/vpn-pulse-probe/awg31/amneziawg-go}
AWG=${AWG:-/opt/vpn-pulse-probe/awg31/awg}
AWG_QUICK=${AWG_QUICK:-/opt/vpn-pulse-probe/awg31/awg-quick}
AWG_LOADER=${AWG_LOADER:-/lib/ld-musl-x86_64.so.1}
DNS_NAME=${DNS_NAME:-one.one.one.one}
IFACE=awgpc0
RUNTIME=/run/amneziawg
started=$(date -u +%Y-%m-%dT%H:%M:%SZ)

result=success; control_result=failure; control_error='"CONTROL_INTERNET_FAILED"'
handshake=failure; handshake_error='"HANDSHAKE_FAILED"'
https=failure; https_error='"HTTPS_FAILED"'; route=false
cleanup() {
  ip netns exec "$NS" ip link del "$IFACE" 2>/dev/null || true
  ip netns del "$NS" 2>/dev/null || true
  rm -rf "/etc/netns/$NS"
}
trap cleanup EXIT INT TERM

control=0
curl -fsS --max-time 10 -o /dev/null https://www.gstatic.com/generate_204 && control=$((control + 1)) || true
curl -fsS --max-time 10 -o /dev/null https://cloudflare.com/cdn-cgi/trace && control=$((control + 1)) || true
# One flaky call to the address service must not decide route_verified, so retry.
home_ip=''
for _ in 1 2 3; do
  home_ip=$(curl -4 -fsS --max-time 10 https://api.ipify.org || true)
  [ -n "$home_ip" ] && break
  sleep 2
done
if [ "$control" -gt 0 ]; then control_result=success; control_error=null; else result=failure; fi

mkdir -p "$RUNTIME" "/etc/netns/$NS"
# A momentary resolver hiccup used to abort here with no JSON row at all, which silently
# drops a target from the matrix instead of reporting it. Retry briefly first.
dns_ip=''
for _ in $(seq 1 10); do
  dns_ip=$(getent ahostsv4 "$DNS_NAME" | awk 'NR == 1 { print $1 }')
  [ -n "$dns_ip" ] && break
  sleep 1
done
[ -n "$dns_ip" ] || { echo "cannot resolve DNS_NAME outside the namespace" >&2; exit 2; }
printf 'nameserver %s\n' "$dns_ip" >"/etc/netns/$NS/resolv.conf"
ip netns add "$NS"
"$AWG_GO" "$IFACE" >/dev/null 2>&1
for _ in $(seq 1 50); do [ -e "$RUNTIME/$IFACE.sock" ] && break; sleep .1; done
# awg-quick is a shell script, so the musl loader rejects it with "Not a valid dynamic
# program" and set -e aborts before any row is printed. Only awg and amneziawg-go are ELF
# binaries that need $AWG_LOADER. Strip the wg-quick-only keys directly instead; awg setconf
# rejects them, and that is all awg-quick strip removed from these generated profiles.
stripped=$(mktemp)
sed -E '/^[[:space:]]*(Address|DNS|MTU|Table|PreUp|PostUp|PreDown|PostDown|SaveConfig)[[:space:]]*=/d' "$PROFILE" >"$stripped"
env WG_I_PREFER_BUGGY_USERSPACE_TO_POLISHED_KMOD=1 "$AWG_LOADER" "$AWG" setconf "$IFACE" "$stripped"
rm -f "$stripped"
ip link set "$IFACE" netns "$NS"
address=$(sed -n 's/^[[:space:]]*Address[[:space:]]*=[[:space:]]*//p' "$PROFILE" | head -1)
ip netns exec "$NS" ip address add "$address" dev "$IFACE"
ip netns exec "$NS" ip link set "$IFACE" up
ip netns exec "$NS" ip route add default dev "$IFACE"

deadline=$(( $(date +%s) + 20 ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  latest=$(ip netns exec "$NS" env WG_I_PREFER_BUGGY_USERSPACE_TO_POLISHED_KMOD=1 "$AWG_LOADER" "$AWG" show "$IFACE" latest-handshakes | cut -f2 | sort -nr | head -1)
  [ "${latest:-0}" -gt 0 ] && [ $(( $(date +%s) - latest )) -le 20 ] && { handshake=success; break; }
  sleep 1
done
[ "$handshake" = success ] && handshake_error=null || result=failure
code=$(ip netns exec "$NS" curl -sS --max-time 10 -o /dev/null -w '%{http_code}' https://www.gstatic.com/generate_204 || true)
[ "$code" = 204 ] && { https=success; https_error=null; } || result=failure
tunnel_ip=''
for _ in 1 2 3; do
  tunnel_ip=$(ip netns exec "$NS" curl -4 -fsS --max-time 10 https://api.ipify.org || true)
  [ -n "$tunnel_ip" ] && break
  sleep 2
done
[ -n "$home_ip" ] && [ "$tunnel_ip" = "$EXPECTED_EXIT" ] && [ "$home_ip" != "$tunnel_ip" ] && route=true || result=failure
# The JSON deliberately carries no addresses, which makes a route_verified=false
# impossible to explain afterwards. Record the three conditions as booleans only -
# no address ever reaches this file - so a failure can be attributed later.
diag=/var/lib/vpn-pulse/r17/route-diag.log
{
  printf '%s target=%s route=%s home_empty=%s tunnel_empty=%s tunnel_eq_expected=%s home_eq_tunnel=%s\n' \
    "$(date -u +%FT%TZ)" "$TARGET_ID" "$route" \
    "$([ -z "$home_ip" ] && echo yes || echo no)" \
    "$([ -z "$tunnel_ip" ] && echo yes || echo no)" \
    "$([ "$tunnel_ip" = "$EXPECTED_EXIT" ] && echo yes || echo no)" \
    "$([ "$home_ip" = "$tunnel_ip" ] && echo yes || echo no)"
} >>"$diag" 2>/dev/null || true
duration=$(( $(date -u +%s) - $(date -u -d "$started" +%s) ))
printf '{"target_id":"%s","observed_at":"%s","duration_ms":%s,"network":{"type":"home","ip_family":"ipv4","route_verified":%s},"results":[{"check":"control_internet","result":"%s","duration_ms":null,"error_code":%s},{"check":"handshake","result":"%s","duration_ms":null,"error_code":%s},{"check":"https","result":"%s","duration_ms":null,"error_code":%s}]}\n' \
  "$TARGET_ID" "$started" "$((duration * 1000))" "$route" "$control_result" "$control_error" "$handshake" "$handshake_error" "$https" "$https_error"
[ "$result" = success ]
