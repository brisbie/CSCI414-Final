#!/bin/bash
# Controlled link failure on the router (Module F).
# usage: linkctl down <zone> | up <zone> | up-all | status | down-list
set -e
. /usr/local/bin/lib.sh

case "$1" in
  down)   i=$(zone_if "$2"); ip link set "$i" down; echo "link $2 ($i) DOWN" ;;
  up)     i=$(zone_if "$2"); ip link set "$i" up;   echo "link $2 ($i) UP" ;;
  up-all) for i in $(ip -o link show | awk -F': ' '$2 ~ /^eth/ { split($2,a,"@"); print a[1] }'); do
            ip link set "$i" up
          done; echo "all eth links UP" ;;
  down-list)  # interfaces that are administratively down
          ip -o link show | awk -F': ' '$2 ~ /^eth/ && $3 !~ /[<,]UP[,>]/ { split($2,a,"@"); print a[1] }' ;;
  status|"") ip -br link show; ip -br -4 addr show ;;
  *) echo "usage: linkctl down|up <client|service|data|ops> | up-all | down-list | status" >&2; exit 2 ;;
esac
