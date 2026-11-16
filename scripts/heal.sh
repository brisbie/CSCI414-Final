#!/usr/bin/env bash
# Diagnose why the service is unhealthy and apply the matching fix (Module F).
# Prints a single line:  action=<what was done>
# Order matters: fix the network, then the database, then the API.
set -uo pipefail
source "$(dirname "$0")/lib.sh"

actions=()

if ! is_running router; then
  $DC start router >/dev/null 2>&1; actions+=("start_router"); sleep 2
fi

down_links=$($DC exec -T router linkctl down-list 2>/dev/null | tr '\n' ' ')
if [ -n "${down_links// /}" ]; then
  $DC exec -T router linkctl up-all >/dev/null; actions+=("link_up(${down_links% })")
fi

if ! is_running mongo; then
  $DC start mongo >/dev/null 2>&1; actions+=("start_mongo")
fi

if ! is_running api; then
  $DC start api >/dev/null 2>&1; actions+=("start_api")
fi

# Nothing obviously broken but still unhealthy -> restart the API process
if [ ${#actions[@]} -eq 0 ]; then
  $DC restart api >/dev/null 2>&1; actions+=("restart_api")
fi

echo "action=$(IFS=+; echo "${actions[*]}")"
