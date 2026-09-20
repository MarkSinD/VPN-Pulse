#!/bin/sh
# create-probe-profile.sh — make the probe's key pair and its peer profile for one target, on the
# probe host. The private key and the preshared key are generated here and never leave this host;
# what goes to the target server is the public key and the preshared key (see add-probe-peer.sh).
#
#   ID=backup LOCAL_ADDRESS=10.8.1.250/32 TARGET_ADDRESS=10.8.1.0 ENDPOINT=vpn.example.org:51820 \
#     JC=4 JMIN=10 JMAX=50 S1=113 S2=106 H1=1 H2=2 H3=3 H4=4 \
#     sh create-probe-profile.sh < target-public-key.txt
#
# The AmneziaWG parameters must match the target server's (read them from its interface config;
# AmneziaWG 2.x servers may add S3, S4, I1…I5 and the timing knobs — pass any of them through EXTRA,
# one "Key = value" per line). Prints the public key to give to the target; keeps everything 0600.
set -eu
ID=${ID:?ID (the server id of the target in config.yaml)}
LOCAL_ADDRESS=${LOCAL_ADDRESS:?LOCAL_ADDRESS (the tunnel address of the probe, /32)}
TARGET_ADDRESS=${TARGET_ADDRESS:?TARGET_ADDRESS (the tunnel address of the target)}
ENDPOINT=${ENDPOINT:?ENDPOINT (host:port of the target)}
: "${JC:?}" "${JMIN:?}" "${JMAX:?}" "${S1:?}" "${S2:?}" "${H1:?}" "${H2:?}" "${H3:?}" "${H4:?}"
EXTRA=${EXTRA:-}
BASE=${BASE:-/etc/vpn-pulse-probe}
IFS= read -r SERVER_PUBLIC
SERVER_PUBLIC=$(printf '%s' "$SERVER_PUBLIC" | tr -d '\r')
case "$SERVER_PUBLIC" in ''|*[!a-zA-Z0-9+/=]*) echo "expected the public key of the target on stdin" >&2; exit 2 ;; esac

umask 077
mkdir -p "$BASE/peers" "$BASE/keys"
tool=$(command -v awg || command -v wg)
[ -f "$BASE/keys/$ID.key" ] || "$tool" genkey > "$BASE/keys/$ID.key"
[ -f "$BASE/keys/$ID.psk" ] || "$tool" genpsk > "$BASE/keys/$ID.psk"
"$tool" pubkey < "$BASE/keys/$ID.key" > "$BASE/keys/$ID.pub"
{
  echo "[Interface]"
  echo "Address = $LOCAL_ADDRESS"
  echo "PrivateKey = $(cat "$BASE/keys/$ID.key")"
  echo "Jc = $JC"; echo "Jmin = $JMIN"; echo "Jmax = $JMAX"
  echo "S1 = $S1"; echo "S2 = $S2"
  echo "H1 = $H1"; echo "H2 = $H2"; echo "H3 = $H3"; echo "H4 = $H4"
  [ -z "$EXTRA" ] || printf '%s\n' "$EXTRA"
  echo
  echo "[Peer]"
  echo "PublicKey = $SERVER_PUBLIC"
  echo "PresharedKey = $(cat "$BASE/keys/$ID.psk")"
  echo "AllowedIPs = $TARGET_ADDRESS/32"
  echo "Endpoint = $ENDPOINT"
  echo "PersistentKeepalive = 25"
} > "$BASE/peers/$ID.conf"
chmod 0600 "$BASE/peers/$ID.conf"
echo "profile $BASE/peers/$ID.conf written; the probe's public key for the target:"
cat "$BASE/keys/$ID.pub"
