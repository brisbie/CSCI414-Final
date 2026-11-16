#!/bin/sh
# iperf3 server: target for throughput tests and competing traffic (Module E)
iperf3 -s -D --logfile /tmp/iperf3.log

# HTTPS only: the API never listens in plaintext (Module C)
exec uvicorn app:app --host 0.0.0.0 --port 8443 \
  --ssl-keyfile /certs/api.key --ssl-certfile /certs/api.crt \
  --no-access-log --timeout-keep-alive 30
