#!/bin/sh
# Shared entrypoint for every non-router container.
# Docker gives each container a default route via the bridge gateway (x.x.x.1),
# which is the HOST, not our router. Traffic between our subnets must instead go
# through the router container, so we add one route for the whole lab range.
set -e

LAB_RANGE="${LAB_RANGE:-10.41.0.0/16}"

if [ -n "$ROUTE_VIA" ]; then
  ip route replace "$LAB_RANGE" via "$ROUTE_VIA"
  echo "[net-init] $(hostname): route $LAB_RANGE via $ROUTE_VIA"
fi

exec "$@"
