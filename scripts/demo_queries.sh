#!/usr/bin/env bash
# Repeatable API examples from the client zone, success AND error cases (Module B).
# Output saved to evidence/queries-<timestamp>.txt
set -uo pipefail
source "$(dirname "$0")/lib.sh"

OUT="evidence/queries-$(date +%Y%m%d-%H%M%S).txt"
mkdir -p evidence
exec > >(tee "$OUT") 2>&1

req() {  # req "<title>" <curl args...>
  echo; echo "### $1"
  echo "\$ curl ${*:2}"
  $DC exec -T client curl -s --cacert /certs/ca.crt -w '\n[HTTP %{http_code}  total=%{time_total}s]\n' \
    -H 'Content-Type: application/json' "${@:2}"
  echo
}
U="$API_URL"

req "Health check"                        "$U/health"
req "Dataset statistics"                  "$U/stats"
req "List 3 products"                     "$U/products?limit=3"

PID=$($DC exec -T client curl -s --cacert /certs/ca.crt "$U/products?limit=1" | python3 -c 'import sys,json;print(json.load(sys.stdin)["items"][0]["product_id"])')
req "Get one product"                     "$U/products/$PID"

KEY="demo-$(date +%s)"
req "CREATE order (201)"                  -X POST "$U/orders" -H "Idempotency-Key: $KEY" \
                                          -d "{\"customer_id\":\"cust-demo\",\"items\":[{\"product_id\":\"$PID\",\"qty\":2}]}"
req "Retry same Idempotency-Key (200, same order, not duplicated)" -i -X POST "$U/orders" -H "Idempotency-Key: $KEY" \
                                          -d "{\"customer_id\":\"cust-demo\",\"items\":[{\"product_id\":\"$PID\",\"qty\":2}]}"

OID=$($DC exec -T client curl -s --cacert /certs/ca.crt "$U/orders?customer_id=cust-demo&limit=1" | python3 -c 'import sys,json;print(json.load(sys.stdin)["items"][0]["order_id"])')
req "READ order"                          "$U/orders/$OID"
req "UPDATE status created -> paid"       -X PATCH "$U/orders/$OID/status" -d '{"status":"paid"}'
req "Query orders by customer"            "$U/orders?customer_id=cust-demo&limit=5"
req "Response headers (Server-Timing splits app vs DB time)" -sS -D - -o /dev/null "$U/orders/$OID"

echo; echo "================ ERROR CASES ================"
req "404 unknown product"                 "$U/products/does-not-exist"
req "404 unknown order"                   "$U/orders/does-not-exist"
req "422 invalid body (qty=0)"            -X POST "$U/orders" -d "{\"customer_id\":\"c\",\"items\":[{\"product_id\":\"$PID\",\"qty\":0}]}"
req "404 order for unknown product"       -X POST "$U/orders" -d '{"customer_id":"c","items":[{"product_id":"nope","qty":1}]}'
req "409 illegal transition paid -> delivered" -X PATCH "$U/orders/$OID/status" -d '{"status":"delivered"}'
req "400 unknown status"                  -X PATCH "$U/orders/$OID/status" -d '{"status":"teleported"}'

echo; echo "saved: $OUT"
