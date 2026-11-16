#!/bin/bash
# Packet capture on the router (Module D).
# Captures on ONE interface (client-facing by default). Capturing on "any" on a
# router records each forwarded packet twice, which Wireshark/tshark would then
# misreport as retransmissions.
#
# usage:
#   capture start <name> [zone] [bpf filter]   -> /captures/<name>.pcap
#   capture stop
#   capture stats <name>                       -> key=value TCP statistics
set -e
. /usr/local/bin/lib.sh
PIDFILE=/tmp/capture.pid

case "$1" in
  start)
    name="$2"; zone="${3:-client}"; filter="${4:-tcp port 8443 or icmp}"
    dev=$(zone_if "$zone")
    [ -f "$PIDFILE" ] && kill "$(cat "$PIDFILE")" 2>/dev/null || true
    setsid tcpdump --immediate-mode -Z root -i "$dev" -s 200 -U -w "/captures/$name.pcap" "$filter" >/tmp/tcpdump.log 2>&1 < /dev/null &
    echo $! > "$PIDFILE"
    sleep 1
    echo "capturing on $dev ($zone) -> /captures/$name.pcap  filter: $filter"
    ;;
  stop)
    if [ -f "$PIDFILE" ]; then kill -INT "$(cat "$PIDFILE")" 2>/dev/null || true; rm -f "$PIDFILE"; sleep 1; fi
    cat /tmp/tcpdump.log 2>/dev/null | tail -3
    ;;
  stats)
    f="/captures/$2.pcap"
    count() { tshark -r "$f" -Y "$1" -T fields -e frame.number 2>/dev/null | wc -l; }
    echo "pcap=$2.pcap"
    echo "frames=$(tshark -r "$f" -T fields -e frame.number 2>/dev/null | wc -l)"
    echo "tcp_syn=$(count 'tcp.flags.syn==1 && tcp.flags.ack==0')"
    echo "tls_client_hello=$(count 'tls.handshake.type==1')"
    echo "retransmissions=$(count 'tcp.analysis.retransmission')"
    echo "fast_retransmissions=$(count 'tcp.analysis.fast_retransmission')"
    echo "duplicate_acks=$(count 'tcp.analysis.duplicate_ack')"
    echo "out_of_order=$(count 'tcp.analysis.out_of_order')"
    echo "icmp_admin_prohibited=$(count 'icmp.type==3 && (icmp.code==13 || icmp.code==10)')"
    ;;
  *) echo "usage: capture start <name> [zone] [filter] | stop | stats <name>" >&2; exit 2 ;;
esac
