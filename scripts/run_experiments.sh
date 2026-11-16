#!/usr/bin/env bash
# Performance experiments (Modules D and E).
#
# For each network condition the SAME measurements run in the same order:
#   1. tc/netem profile applied on the router (client <-> API path)
#   2. packet capture started on the router's client-facing interface
#   3. ICMP RTT: 50 pings client -> API
#   4. Fresh-connection timing: 20 curl requests (TCP connect, TLS handshake)
#   5. Application workload: loadgen.py, identical seed and request count
#      (in 'congested', a competing iperf3 bulk flow runs at the same time)
#   6. TCP throughput: iperf3 for 10 s (not in 'congested'; the link is busy)
#   7. capture stopped; retransmissions / dup ACKs counted with tshark
# Then impairment is cleared and analyze.py builds tables + charts.
#
# usage: scripts/run_experiments.sh [run_id] [conditions...]
#   default conditions: baseline delay loss rate congested dbdelay
#   env: REQUESTS=300  SEED=42   (and DELAY, JITTER, LOSS, RATE, LIMIT for impair)
set -euo pipefail
source "$(dirname "$0")/lib.sh"

RUN="${1:-$(date +%Y%m%d-%H%M%S)}"; shift || true
CONDS=("$@"); [ ${#CONDS[@]} -eq 0 ] && CONDS=(baseline delay loss rate congested dbdelay)
REQUESTS="${REQUESTS:-300}"; SEED="${SEED:-42}"
IMPAIR_ENV=(-e "DELAY=${DELAY:-25ms}" -e "JITTER=${JITTER:-5ms}" -e "LOSS=${LOSS:-3%}" -e "RATE=${RATE:-10mbit}" -e "LIMIT=${LIMIT:-200}" -e "DB_DELAY=${DB_DELAY:-10ms}")

wait_healthy 30 || { bad "API not healthy, aborting (run scripts/up.sh)"; exit 1; }
info "run $RUN: conditions = ${CONDS[*]}, $REQUESTS requests each, seed $SEED"
mkdir -p "results/$RUN"
{ echo "run=$RUN"; echo "date=$(date -Is)"; echo "requests=$REQUESTS"; echo "seed=$SEED"
  echo "conditions=${CONDS[*]}"; echo "host_kernel=$(uname -r)"; echo "${IMPAIR_ENV[*]}"; } > "results/$RUN/meta.txt"

cleanup() { $DC exec -T router impair clear >/dev/null 2>&1 || true
            $DC exec -T router capture stop >/dev/null 2>&1 || true
            $DC exec -T client pkill iperf3 >/dev/null 2>&1 || true; }
trap cleanup EXIT

for c in "${CONDS[@]}"; do
  D="results/$RUN/$c"; mkdir -p "$D"
  info "[$c] applying impairment"
  if [ "$c" = baseline ]; then
    $DC exec -T router impair clear > "$D/tc.txt"
  else
    $DC exec -T "${IMPAIR_ENV[@]}" router impair "$c" > "$D/tc.txt"
  fi
  sleep 2

  $DC exec -T router capture start "$RUN-$c" client "tcp port 8443 or icmp" >/dev/null

  info "[$c] ping x50"
  $DC exec -T client ping -c 50 -i 0.2 api.shop.local > "$D/ping.txt" || true
  tail -2 "$D/ping.txt" | sed 's/^/     /'

  info "[$c] 20 fresh TCP+TLS connections"
  $DC exec -T client sh -c '
    echo "time_connect,time_appconnect,time_starttransfer,time_total,http_code"
    for i in $(seq 1 20); do
      curl -s -o /dev/null -m 15 --cacert /certs/ca.crt \
        -w "%{time_connect},%{time_appconnect},%{time_starttransfer},%{time_total},%{http_code}\n" \
        https://api.shop.local:8443/health || echo "0,0,0,0,000"
    done' > "$D/curl_timing.csv"

  if [ "$c" = congested ]; then
    info "[$c] starting competing iperf3 bulk flow"
    $DC exec -d client iperf3 -c 10.41.2.10 -t 600 -J --logfile "/results/$RUN/$c/competing_iperf.json"
    sleep 3
  fi

  info "[$c] application workload"
  $DC exec -T client python /app/loadgen.py --requests "$REQUESTS" --seed "$SEED" \
      --label "$c" --out "/results/$RUN/$c" | tee "$D/loadgen.log"

  if [ "$c" = congested ]; then
    $DC exec -T client pkill -INT iperf3 || true; sleep 2
  else
    info "[$c] iperf3 throughput (10 s)"
    $DC exec -T client iperf3 -c 10.41.2.10 -t 10 -J > "$D/iperf.json" || true
  fi

  $DC exec -T router capture stop >/dev/null
  $DC exec -T router capture stats "$RUN-$c" > "$D/capture_stats.txt" || true
  $DC exec -T router nft list counters > "$D/nft_counters.txt" || true
  sed 's/^/     /' "$D/capture_stats.txt"
done

$DC exec -T router impair clear >/dev/null
info "analyzing"
$DC exec -T ops python /app/analyze.py "/results/$RUN"
cp "evidence/pcap/$RUN-"*.pcap "results/$RUN/" 2>/dev/null || true
info "done. Results: results/$RUN/  (summary.md, summary.csv, charts/*.png, *.pcap)"
