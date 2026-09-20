#!/bin/sh
# add-probe-peer.sh — add the probe's test peer to an AmneziaWG server that runs in Amnezia's Docker
# container, the way the Amnezia client does it: the peer goes into the interface config and into
# `clientsTable` (so the server owner sees it under its name), then it is applied live — no restart.
#
#   printf '%s\n%s\n' "$PEER_PUBLIC_KEY" "$PRESHARED_KEY" | CONTAINER=<awg container> NAME=probe-from-lv ADDRESS=10.8.1.250/32 sh add-probe-peer.sh
#
# Run on the target server as root. The two keys come on stdin (never as arguments — they would
# show in the process list). Both files are backed up next to themselves before the change, and the
# edited clientsTable must still be valid JSON or nothing is applied. Afterwards put the peer's
# public key into PROBE_PEERS of /etc/vpn-pulse-helper/config so the collector never counts it.
set -eu
CONTAINER=${CONTAINER:?CONTAINER (the Amnezia AmneziaWG container, see docker ps)}
NAME=${NAME:?NAME (the client name in clientsTable, e.g. probe-from-lv)}
ADDRESS=${ADDRESS:?ADDRESS (the tunnel address of the peer, /32)}
ADDRESS_FIELD=${ADDRESS_FIELD:-allowedIps}
CONF_DIR=/opt/amnezia/awg
case "$ADDRESS_FIELD" in allowedIps|allowed_ips) ;; *) echo "ADDRESS_FIELD must be allowedIps or allowed_ips" >&2; exit 2 ;; esac
IFS= read -r PUB
IFS= read -r PSK
[ -n "$PUB" ] && [ -n "$PSK" ] || { echo "expected the public key and the preshared key on stdin" >&2; exit 2; }

stamp=$(date -u +%Y%m%dT%H%M%SZ)
work=$(mktemp -d /root/probe-peer-XXXXXX)
chmod 700 "$work"
docker cp "$CONTAINER:$CONF_DIR/awg0.conf" "$work/awg0.conf"
docker cp "$CONTAINER:$CONF_DIR/clientsTable" "$work/clientsTable"
docker exec "$CONTAINER" cp -a "$CONF_DIR/awg0.conf" "$CONF_DIR/awg0.conf.bak-probe-$stamp"
docker exec "$CONTAINER" cp -a "$CONF_DIR/clientsTable" "$CONF_DIR/clientsTable.bak-probe-$stamp"

# clientsTable: a JSON list of {clientId: <public key>, userData: {clientName, creationDate, allowedIps}}
PUB="$PUB" NAME="$NAME" ADDRESS="$ADDRESS" ADDRESS_FIELD="$ADDRESS_FIELD" python3 - "$work/clientsTable" <<'PY'
import json, os, sys, time
path = sys.argv[1]
with open(path, encoding="utf-8") as stream:
    table = json.load(stream)
if any(row.get("clientId") == os.environ["PUB"] for row in table):
    sys.exit("this public key is already in clientsTable")
table.append({"clientId": os.environ["PUB"], "userData": {
    "clientName": os.environ["NAME"],
    "creationDate": time.strftime("%a %b %d %H:%M:%S %Y", time.gmtime()),
    os.environ["ADDRESS_FIELD"]: os.environ["ADDRESS"],
}})
with open(path, "w", encoding="utf-8") as stream:
    json.dump(table, stream, ensure_ascii=False, separators=(",", ":"))
PY
python3 -m json.tool "$work/clientsTable" >/dev/null
docker cp "$work/clientsTable" "$CONTAINER:$CONF_DIR/clientsTable"
docker exec -i "$CONTAINER" sh -c "cat >> $CONF_DIR/awg0.conf" <<EOF

[Peer]
PublicKey = $PUB
PresharedKey = $PSK
AllowedIPs = $ADDRESS
EOF
# live: the preshared key goes through a 0600 file inside the container, never through an argument
printf '%s\n' "$PSK" | docker exec -i "$CONTAINER" sh -c 'umask 077; cat > /tmp/probe.psk; tool=$(command -v awg || command -v wg); "$tool" set awg0 peer "$1" preshared-key /tmp/probe.psk allowed-ips "$2"; rm -f /tmp/probe.psk' sh "$PUB" "$ADDRESS"
rm -rf "$work"
count=$(docker exec "$CONTAINER" sh -c 'tool=$(command -v awg || command -v wg); "$tool" show awg0 peers' | wc -l)
echo "added $NAME ($ADDRESS); live peers: $count; backups: *.bak-probe-$stamp in $CONF_DIR"
