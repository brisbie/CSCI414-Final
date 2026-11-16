#!/bin/bash
# Helpers shared by the router scripts.
# Docker does not guarantee eth0/eth1/... ordering, so interfaces are always
# looked up by the subnet they sit on.

CLIENT_NET="10.41.1"
SERVICE_NET="10.41.2"
DATA_NET="10.41.3"
OPS_NET="10.41.4"

# ifname <subnet-prefix>  e.g. ifname 10.41.2  -> eth1
ifname() {
  ip -o -4 addr show | awk -v p="$1." 'index($4, p) == 1 { print $2; exit }'
}

# zone name -> subnet prefix
zone_prefix() {
  case "$1" in
    client)  echo "$CLIENT_NET" ;;
    service) echo "$SERVICE_NET" ;;
    data)    echo "$DATA_NET" ;;
    ops)     echo "$OPS_NET" ;;
    *) echo "unknown zone: $1 (use client|service|data|ops)" >&2; return 1 ;;
  esac
}

zone_if() {
  local p; p=$(zone_prefix "$1") || return 1
  local i; i=$(ifname "$p")
  if [ -z "$i" ]; then echo "no interface found on $p.0/24" >&2; return 1; fi
  echo "$i"
}
