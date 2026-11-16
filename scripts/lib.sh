#!/usr/bin/env bash
# Shared helpers for the host-side scripts. Source this file; do not run it.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

DC="docker compose"
API_URL="https://api.shop.local:8443"

c_green=$'\e[32m'; c_red=$'\e[31m'; c_yel=$'\e[33m'; c_off=$'\e[0m'
info() { echo "${c_yel}==>${c_off} $*"; }
ok()   { echo "${c_green}PASS${c_off} $*"; }
bad()  { echo "${c_red}FAIL${c_off} $*"; }

now() { date +%s.%N | cut -c1-14; }   # epoch seconds with 3 decimals

# HTTP status of the API health check as seen from the CLIENT zone (000 = no answer)
probe() {
  $DC exec -T client curl -s -o /dev/null -m "${1:-2}" --cacert /certs/ca.crt \
    -w '%{http_code}' "$API_URL/health" 2>/dev/null || true
}

wait_healthy() {  # wait_healthy <timeout_s>
  local t=${1:-90} i=0
  while [ "$i" -lt "$t" ]; do
    [ "$(probe)" = "200" ] && return 0
    sleep 1; i=$((i + 1))
  done
  return 1
}

is_running() { [ -n "$($DC ps --status running -q "$1" 2>/dev/null)" ]; }
