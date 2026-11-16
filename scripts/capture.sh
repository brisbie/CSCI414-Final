#!/usr/bin/env bash
# Ad-hoc packet capture for Wireshark (Module D).
#
# usage: scripts/capture.sh <name> <seconds> [zone] [bpf filter]
#   zone: client (default) | service | data | ops   (router interface to capture on)
# examples:
#   scripts/capture.sh tls-flow 15                          # client <-> API HTTPS
#   scripts/capture.sh db-flow 15 data "tcp port 27017"     # API <-> MongoDB
#   scripts/capture.sh denied 10 client "host 10.41.3.10"   # blocked bypass attempt
# While it runs, generate traffic in another terminal (e.g. demo_queries.sh).
set -euo pipefail
source "$(dirname "$0")/lib.sh"

NAME="${1:?name}"; SECS="${2:-15}"; ZONE="${3:-client}"; FILTER="${4:-tcp port 8443 or icmp}"
$DC exec -T router capture start "$NAME" "$ZONE" "$FILTER"
sleep "$SECS"
$DC exec -T router capture stop
$DC exec -T router capture stats "$NAME"
info "saved evidence/pcap/$NAME.pcap  (open in Wireshark)"
