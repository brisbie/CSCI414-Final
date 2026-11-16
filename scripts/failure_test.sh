#!/usr/bin/env bash
# Controlled failure + automated detection + automated recovery (Module F).
#
# usage: scripts/failure_test.sh <scenario|all> [run_id]
#   api-crash   kill the API container            (service failure)
#   db-crash    kill the MongoDB container        (backend failure; API stays up but returns 503)
#   link-down   take the router's service-subnet interface down  (network failure)
#   all         run all three in sequence
#
# Timeline recorded for each scenario (epoch seconds):
#   t_fail        failure injected
#   t_detect      watchdog saw DETECT_N consecutive failed health probes
#   t_heal_start / t_heal_done   heal.sh diagnosed and fixed it
#   t_recovered   first successful health probe afterwards
# then the SAME client request (GET /products?limit=5) is repeated to prove recovery.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

SCEN="${1:?usage: failure_test.sh <api-crash|db-crash|link-down|all> [run_id]}"
RUN="${2:-$(date +%Y%m%d-%H%M%S)}"
DETECT_N="${DETECT_N:-3}"     # consecutive failed probes before declaring an outage
OUTDIR="results/$RUN/recovery"; mkdir -p "$OUTDIR"

verify_request() {
  $DC exec -T client curl -s -o /dev/null -m 5 --cacert /certs/ca.crt -w '%{http_code}' \
    "$API_URL/products?limit=5" 2>/dev/null || true
}

run_one() {
  local s="$1" log="$OUTDIR/$1.log" csv="$OUTDIR/$1.csv"
  : > "$log"
  say() { echo "$(date +%H:%M:%S.%3N) $*" | tee -a "$log"; }

  info "scenario: $s"
  wait_healthy 60 || { bad "service not healthy before test; aborting"; return 1; }
  say "pre-check: health=$(probe)  verify_request=$(verify_request)"

  local t_fail t_detect t_hs t_hd t_rec action fails=0
  t_fail=$(now)
  case "$s" in
    api-crash) $DC kill api >/dev/null 2>&1 ;;
    db-crash)  $DC kill mongo >/dev/null 2>&1 ;;
    link-down) $DC exec -T router linkctl down service >/dev/null ;;
    *) bad "unknown scenario $s"; return 2 ;;
  esac
  say "FAILURE INJECTED ($s)"

  # Detect: poll health from the client zone
  local deadline=$(( $(date +%s) + 60 ))
  while :; do
    code=$(probe 2)
    if [ "$code" = "200" ]; then fails=0; else fails=$((fails + 1)); fi
    say "probe health=$code consecutive_failures=$fails"
    [ "$fails" -ge "$DETECT_N" ] && break
    [ "$(date +%s)" -gt "$deadline" ] && { bad "failure never detected"; return 1; }
    sleep 1
  done
  t_detect=$(now); say "OUTAGE DETECTED"

  # Recover automatically
  t_hs=$(now)
  action=$(bash scripts/heal.sh | sed -n 's/^action=//p')
  t_hd=$(now); say "HEAL action=$action"

  deadline=$(( $(date +%s) + 120 ))
  until [ "$(probe 2)" = "200" ]; do
    [ "$(date +%s)" -gt "$deadline" ] && { bad "not recovered within 120 s"; return 1; }
    sleep 0.5
  done
  t_rec=$(now); say "SERVICE RECOVERED"

  local v; v=$(verify_request); say "post-check: verify_request=$v"

  python3 - "$s" "$t_fail" "$t_detect" "$t_hs" "$t_hd" "$t_rec" "$action" "$v" > "$csv" <<'PY'
import sys
s, f, d, hs, hd, r, a, v = sys.argv[1:]
f, d, hs, hd, r = map(float, (f, d, hs, hd, r))
print("scenario,t_fail,t_detect,t_heal_start,t_heal_done,t_recovered,detect_s,heal_s,recover_s,outage_s,action,verify")
print(f"{s},{f:.3f},{d:.3f},{hs:.3f},{hd:.3f},{r:.3f},{d-f:.2f},{hd-hs:.2f},{r-d:.2f},{r-f:.2f},{a},HTTP {v}")
PY
  ok "$s: detected after $(awk -F, 'NR==2{print $7}' "$csv")s, outage $(awk -F, 'NR==2{print $10}' "$csv")s, action=$action, verify=HTTP $v"
  sleep 5   # let the monitor record a stable healthy period between scenarios
}

if [ "$SCEN" = all ]; then
  for s in api-crash db-crash link-down; do run_one "$s"; done
else
  run_one "$SCEN"
fi

info "analyzing recovery results"
$DC exec -T ops python /app/analyze.py "/results/$RUN" || true
info "results in $OUTDIR/ (and charts/recovery_*.png)"
