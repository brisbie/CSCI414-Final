#!/usr/bin/env bash
# Automated validation of the network and security policy (Modules A, C, F).
# Every check prints PASS/FAIL; the full transcript is saved to
# evidence/validation-<timestamp>.txt. Exit code = number of failed checks.
set -uo pipefail
source "$(dirname "$0")/lib.sh"

TS=$(date +%Y%m%d-%H%M%S)
OUT="evidence/validation-$TS.txt"
mkdir -p evidence
exec > >(tee "$OUT") 2>&1

FAILS=0
check() {  # check "<description>" <expect: pass|fail> <command...>
  local desc="$1" expect="$2"; shift 2
  local out rc
  out=$("$@" 2>&1); rc=$?
  if { [ "$expect" = pass ] && [ $rc -eq 0 ]; } || { [ "$expect" = fail ] && [ $rc -ne 0 ]; }; then
    ok "$desc"
  else
    bad "$desc  (exit=$rc, expected $expect)"; FAILS=$((FAILS + 1))
  fi
  echo "$out" | sed 's/^/      /' | head -15
}
x() { $DC exec -T "$@"; }

echo "ShopNet validation  $(date -Is)"
echo

info "Addressing and routes (Module A)"
for s in client api mongo ops; do
  echo "--- $s"; x "$s" sh -c 'ip -br -4 addr show | grep -v "^lo"; ip route'
done
echo "--- router"; x router sh -c 'ip -br -4 addr show | grep -v "^lo"; ip route; echo ip_forward=$(cat /proc/sys/net/ipv4/ip_forward)'
echo

info "Connectivity along permitted paths (Module A)"
check "client -> API ping (crosses router)"            pass x client ping -c 3 -W 2 api.shop.local
check "client -> API traceroute shows router hop"      pass x client sh -c 'traceroute -I -n -w 2 -q 1 api.shop.local | tee /dev/stderr | grep -q 10.41.1.254'
check "API -> MongoDB TCP 27017"                       pass x api nc -z -w 3 10.41.3.10 27017
check "ops -> API health over HTTPS"                   pass x ops curl -sf --cacert /certs/ca.crt https://api.shop.local:8443/health
check "ops -> MongoDB TCP 27017 (admin/import path)"   pass x ops nc -z -w 3 10.41.3.10 27017
echo

info "Security policy (Module C)"
check "ALLOWED: client -> API over TLS, CA-verified"   pass x client curl -sS -f --cacert /certs/ca.crt https://api.shop.local:8443/health
check "TLS details (protocol/cipher/cert subject)"     pass x client sh -c 'curl -sv --cacert /certs/ca.crt -o /dev/null https://api.shop.local:8443/health 2>&1 | grep -E "SSL connection|subject:|issuer:|subjectAltName"'
check "REJECTED: client without CA trust (untrusted cert)" fail x client curl -sS -f https://api.shop.local:8443/health
check "REJECTED: plaintext HTTP to the API port"       fail x client curl -sS -f -m 3 http://api.shop.local:8443/health
check "DENIED: client -> MongoDB 27017 (bypass API)"   fail x client nc -z -v -w 3 10.41.3.10 27017
check "DENIED: client -> MongoDB ping"                 fail x client ping -c 2 -W 2 10.41.3.10
check "DENIED: client -> API on a non-allowed port (22)" fail x client nc -z -v -w 3 10.41.2.10 22
check "DENIED: API -> client zone (no inbound to clients)" fail x api nc -z -w 3 10.41.1.10 80
echo

info "Firewall counters after the tests (deny_* should be > 0)"
x router nft list counters
echo

info "Service health (Module F)"
check "API /health reports db=up"                      pass x client sh -c 'curl -s --cacert /certs/ca.crt https://api.shop.local:8443/health | grep -q "\"db\":\"up\""'
for s in router mongo api client ops; do
  if is_running "$s"; then ok "container $s running"; else bad "container $s not running"; FAILS=$((FAILS + 1)); fi
done

echo
if [ $FAILS -eq 0 ]; then ok "ALL CHECKS PASSED"; else bad "$FAILS check(s) failed"; fi
echo "transcript: $OUT"
exit $FAILS
