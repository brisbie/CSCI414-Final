#!/usr/bin/env python3

import csv
import os
import time
from datetime import datetime, timezone

import httpx

URL = os.environ.get("HEALTH_URL", "https://api.shop.local:8443/health")
CA = os.environ.get("CA_CERT", "/certs/ca.crt")
INTERVAL = float(os.environ.get("MONITOR_INTERVAL", "0.5"))
TIMEOUT = float(os.environ.get("MONITOR_TIMEOUT", "1.5"))
OUT = os.environ.get("MONITOR_CSV", "/logs/monitor.csv")
EVENTS = os.environ.get("MONITOR_EVENTS", "/logs/monitor_events.log")


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="milliseconds")


def main() -> None:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    new = not os.path.exists(OUT)
    f = open(OUT, "a", newline="", buffering=1)
    w = csv.writer(f)
    if new:
        w.writerow(["epoch", "iso", "ok", "status", "latency_ms", "db", "error"])
    ev = open(EVENTS, "a", buffering=1)

    state, down_since = None, None
    print(f"[monitor] probing {URL} every {INTERVAL}s -> {OUT}", flush=True)
    while True:
        t = time.time()
        t0 = time.perf_counter()
        status, db, err = 0, "", ""
        try:
            with httpx.Client(verify=CA, timeout=TIMEOUT) as c:
                r = c.get(URL)
            status = r.status_code
            try:
                db = r.json().get("db", "")
            except ValueError:
                pass
        except httpx.HTTPError as e:
            err = type(e).__name__
        lat = (time.perf_counter() - t0) * 1000.0
        ok = status == 200
        w.writerow([f"{t:.3f}", iso(t), int(ok), status, f"{lat:.2f}", db, err])

        if state is not None and ok != state:
            if not ok:
                down_since = t
                ev.write(f"{iso(t)} DOWN status={status} error={err or db}\n")
            else:
                dur = t - down_since if down_since else 0
                ev.write(f"{iso(t)} UP   outage_s={dur:.2f}\n")
        state = ok
        time.sleep(max(0.0, INTERVAL - (time.perf_counter() - t0)))


if __name__ == "__main__":
    main()
