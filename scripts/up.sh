#!/usr/bin/env bash
# One-command launch: prerequisites -> secrets -> certs -> build -> start ->
# load data -> validate. Safe to re-run.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

command -v docker >/dev/null || { bad "docker is not installed"; exit 1; }
docker compose version >/dev/null 2>&1 || { bad "docker compose v2 is required"; exit 1; }
docker info >/dev/null 2>&1 || { bad "cannot talk to Docker (is the daemon running? are you in the docker group?)"; exit 1; }

# Kernel modules used inside the router container (containers cannot load modules)
info "loading kernel modules (sch_netem, nf_tables, nft_reject_inet)"
if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi
$SUDO modprobe -a sch_netem nf_tables nft_reject_inet 2>/dev/null \
  || echo "   warning: modprobe failed; netem/nftables may still autoload"
# Let nftables 'log' rules inside the router container reach the host kernel log
$SUDO sysctl -qw net.netfilter.nf_log_all_netns=1 2>/dev/null \
  || echo "   note: nf_log_all_netns not set; firewall LOG lines will not appear in journalctl -k (counters still work)"

mkdir -p logs results evidence/pcap data/olist certs

if [ ! -f .env ]; then
  info "creating .env with a random MongoDB password"
  printf 'MONGO_USER=shopadmin\nMONGO_PASSWORD=%s\n' "$(openssl rand -hex 16)" > .env
  chmod 600 .env
fi

bash scripts/gen_certs.sh

info "building and starting containers"
$DC up -d --build

info "waiting for the API to report healthy (from the client zone)"
if ! wait_healthy 120; then
  bad "API not healthy after 120 s. Check: docker compose logs api mongo router"; exit 1
fi
ok "API healthy"

info "checking that tc/netem works inside the router"
if $DC exec -T router sh -c 'tc qdisc add dev lo root netem delay 1ms && tc qdisc del dev lo root' >/dev/null 2>&1; then
  ok "netem available"
else
  bad "netem is not available in this kernel. Module E needs it. Fix, then re-run:"
  echo "     Ubuntu/Debian: sudo apt install linux-modules-extra-\$(uname -r) && sudo modprobe sch_netem"
  echo "     Fedora/RHEL:   sudo dnf install kernel-modules-extra && sudo modprobe sch_netem"
fi

info "loading data (skipped if already loaded)"
$DC exec -T ops python /app/import_data.py --if-empty

info "running validation suite"
bash scripts/validate.sh || true

echo
info "ready. Next steps:"
echo "   bash scripts/demo_queries.sh      # API success + error examples (Module B)"
echo "   bash scripts/run_experiments.sh   # baseline / delay / loss / rate / congested (Module E)"
echo "   bash scripts/failure_test.sh all  # failure + automated recovery (Module F)"
