#!/usr/bin/env bash
# Continuous self-healing watchdog (Module F). Leave it running in a terminal
# during the demo; break something in another terminal and watch it recover.
#
# usage: scripts/watchdog.sh   (Ctrl-C to stop; log in logs/watchdog.log)
set -uo pipefail
source "$(dirname "$0")/lib.sh"

INTERVAL="${INTERVAL:-1}"; DETECT_N="${DETECT_N:-3}"
LOG=logs/watchdog.log; mkdir -p logs
fails=0
info "watchdog: probing every ${INTERVAL}s, healing after $DETECT_N consecutive failures"
while :; do
  code=$(probe 2)
  ts=$(date -Is)
  if [ "$code" = "200" ]; then
    [ $fails -ge "$DETECT_N" ] && echo "$ts RECOVERED" | tee -a "$LOG"
    fails=0
  else
    fails=$((fails + 1))
    echo "$ts health=$code failures=$fails" | tee -a "$LOG"
    if [ $fails -eq "$DETECT_N" ]; then
      echo "$ts OUTAGE DETECTED -> healing" | tee -a "$LOG"
      echo "$ts $(bash scripts/heal.sh)" | tee -a "$LOG"
    elif [ $fails -gt $((DETECT_N + 20)) ]; then
      echo "$ts still down, healing again" | tee -a "$LOG"
      echo "$ts $(bash scripts/heal.sh)" | tee -a "$LOG"; fails=$DETECT_N
    fi
  fi
  sleep "$INTERVAL"
done
