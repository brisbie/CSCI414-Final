#!/bin/bash
# Apply controlled network impairment with tc/netem on the client <-> API path
# (Module E). netem is applied to the router's egress on BOTH the client-facing
# and service-facing interfaces, so requests and responses are each affected.
# One-way delay D therefore adds about 2*D to round-trip time.
#
# usage: impair <profile>
#   clear      remove all impairment
#   delay      DELAY (default 25ms) +/- JITTER (5ms) each way  -> ~+50ms RTT
#   loss       LOSS (default 3%) random loss each way
#   rate       RATE (default 10mbit) bandwidth cap, LIMIT (200) packet queue
#   congested  same shaping as 'rate'; run competing iperf3 traffic alongside
#   combo      delay + 1% loss
#   dbdelay    DB_DELAY (default 10ms) on the router's DATA-zone egress only, so
#              every API -> MongoDB round trip gets slower but the client path does not
#   show       print current qdiscs with statistics
#
# Override values with env vars, e.g.  DELAY=50ms impair delay   DB_DELAY=20ms impair dbdelay
set -e
. /usr/local/bin/lib.sh

DELAY="${DELAY:-25ms}"
JITTER="${JITTER:-5ms}"
LOSS="${LOSS:-3%}"
RATE="${RATE:-10mbit}"
LIMIT="${LIMIT:-200}"
DB_DELAY="${DB_DELAY:-10ms}"

CIF=$(zone_if client)
SIF=$(zone_if service)
DIF=$(zone_if data)

clear_if() { tc qdisc del dev "$1" root 2>/dev/null || true; }

apply() {
  for dev in "$CIF" "$SIF"; do
    clear_if "$dev"
    # shellcheck disable=SC2068
    tc qdisc add dev "$dev" root netem $@
  done
}

case "${1:-show}" in
  clear)     clear_if "$CIF"; clear_if "$SIF"; clear_if "$DIF" ;;
  delay)     apply delay "$DELAY" "$JITTER" distribution normal ;;
  loss)      apply loss "$LOSS" ;;
  rate|congested) apply rate "$RATE" limit "$LIMIT" ;;
  combo)     apply delay "$DELAY" "$JITTER" distribution normal loss 1% ;;
  dbdelay)   clear_if "$CIF"; clear_if "$SIF"; clear_if "$DIF"
             tc qdisc add dev "$DIF" root netem delay "$DB_DELAY" ;;
  show)      ;;
  *) echo "unknown profile '$1' (clear|delay|loss|rate|congested|combo|dbdelay|show)" >&2; exit 2 ;;
esac

echo "# impairment profile: ${1:-show}   client_if=$CIF service_if=$SIF data_if=$DIF"
for dev in "$CIF" "$SIF" "$DIF"; do tc -s qdisc show dev "$dev"; done
