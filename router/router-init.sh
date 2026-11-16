#!/bin/bash
# Router container entrypoint: confirm forwarding, load the firewall, print the
# interface map, then stay alive.
set -e
. /usr/local/bin/lib.sh

echo "[router] ip_forward=$(cat /proc/sys/net/ipv4/ip_forward)"

nft -f /etc/nftables.conf
echo "[router] nftables ruleset loaded"

for z in client service data ops; do
  echo "[router] zone $z -> $(zone_if "$z") ($(zone_prefix "$z").254)"
done

exec tail -f /dev/null
