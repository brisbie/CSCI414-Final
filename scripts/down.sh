#!/usr/bin/env bash
# Stop everything. Pass --wipe to also delete the MongoDB volume.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
if [ "${1:-}" = "--wipe" ]; then
  $DC down -v --remove-orphans
else
  $DC down --remove-orphans
fi
# Files written by containers are owned by root; hand them back to you.
if [ "$(id -u)" -ne 0 ]; then
  sudo chown -R "$(id -u):$(id -g)" logs results evidence 2>/dev/null || true
fi
