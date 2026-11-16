#!/usr/bin/env bash
# Create a private lab CA and a server certificate for the API (Module C).
# The client and ops containers trust only this CA, so certificate validation
# is real (no -k / verify=False anywhere).
set -euo pipefail
source "$(dirname "$0")/lib.sh"

D=certs
mkdir -p "$D"
if [ -f "$D/api.crt" ] && [ "${1:-}" != "--force" ]; then
  info "certificates already exist (use --force to regenerate)"; exit 0
fi

openssl req -x509 -new -nodes -newkey rsa:2048 -sha256 -days 365 \
  -keyout "$D/ca.key" -out "$D/ca.crt" -subj "/CN=ShopNet Lab CA" \
  -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
  -addext "keyUsage=critical,keyCertSign,cRLSign" \
  -addext "subjectKeyIdentifier=hash" 2>/dev/null

openssl req -new -nodes -newkey rsa:2048 -keyout "$D/api.key" -out "$D/api.csr" \
  -subj "/CN=api.shop.local" 2>/dev/null

cat > "$D/api.ext" <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid,issuer
subjectAltName=DNS:api.shop.local,DNS:api,IP:10.41.2.10
EOF

openssl x509 -req -in "$D/api.csr" -CA "$D/ca.crt" -CAkey "$D/ca.key" -CAcreateserial \
  -out "$D/api.crt" -days 365 -sha256 -extfile "$D/api.ext" 2>/dev/null

rm -f "$D/api.csr" "$D/api.ext" "$D/ca.srl"
chmod 644 "$D/ca.crt" "$D/api.crt"
chmod 600 "$D/ca.key" "$D/api.key"   # private keys: owner-only, never committed (root in the container can still read)
info "certificates written to $D/ (ignored by git)"
openssl x509 -in "$D/api.crt" -noout -subject -issuer -ext subjectAltName
