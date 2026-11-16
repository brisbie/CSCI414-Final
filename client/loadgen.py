#!/usr/bin/env python3
"""
Repeatable workload generator (Modules D and E).

Runs the SAME seeded sequence of operations every time so baseline, congested
and recovered runs are directly comparable. Each iteration does 5 requests:

    list_products   GET   /products?limit=50     (larger response: ~10 KB)
    get_product     GET   /products/{id}
    create_order    POST  /orders                (with Idempotency-Key)
    get_order       GET   /orders/{id}
    pay_order       PATCH /orders/{id}/status    created -> paid

For every request it records client-side latency and the server's own timing
(Server-Timing header), so:
    network+TLS+client overhead  ~=  total_ms - app_ms
    database time                 =  db_ms

Output: <out>/loadgen.csv (one row per request) and <out>/summary.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import statistics
import time
import uuid

import httpx

OPS = ["list_products", "get_product", "create_order", "get_order", "pay_order"]


def parse_server_timing(h: str | None) -> tuple[float | None, float | None]:
    if not h:
        return None, None
    vals = dict(re.findall(r"(\w+);dur=([\d.]+)", h))
    app = float(vals["app"]) if "app" in vals else None
    db = float(vals["db"]) if "db" in vals else None
    return app, db


def pct(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * p / 100.0
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 3)


def summarize(rows: list[dict], wall_s: float) -> dict:
    ok = [r for r in rows if r["ok"]]
    lat = [r["total_ms"] for r in ok]

    def block(rs):
        l_ = [r["total_ms"] for r in rs if r["ok"]]
        net = [r["total_ms"] - r["app_ms"] for r in rs if r["ok"] and r["app_ms"] is not None]
        dbm = [r["db_ms"] for r in rs if r["ok"] and r["db_ms"] is not None]
        app = [r["app_ms"] for r in rs if r["ok"] and r["app_ms"] is not None]
        return {
            "requests": len(rs),
            "success": len(l_),
            "errors": len(rs) - len(l_),
            "error_rate": round((len(rs) - len(l_)) / len(rs), 4) if rs else None,
            "mean_ms": round(statistics.mean(l_), 3) if l_ else None,
            "p50_ms": pct(l_, 50), "p95_ms": pct(l_, 95), "p99_ms": pct(l_, 99),
            "max_ms": round(max(l_), 3) if l_ else None,
            "stdev_ms": round(statistics.stdev(l_), 3) if len(l_) > 1 else None,
            "median_app_ms": pct(app, 50),
            "median_db_ms": pct(dbm, 50),
            "median_network_ms": pct(net, 50),
        }

    return {
        "overall": block(rows),
        "by_op": {op: block([r for r in rows if r["op"] == op]) for op in OPS},
        "wall_time_s": round(wall_s, 3),
        "throughput_rps": round(len(ok) / wall_s, 3) if wall_s > 0 else None,
        "latency_unit": "ms",
        "measurement": "client-side wall clock (time.perf_counter) per HTTP request over a kept-alive TLS connection",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.environ.get("API_URL", "https://api.shop.local:8443"))
    ap.add_argument("--ca", default=os.environ.get("CA_CERT", "/certs/ca.crt"))
    ap.add_argument("--requests", type=int, default=300, help="total requests (multiple of 5)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--label", default="run")
    ap.add_argument("--out", default="/results/adhoc")
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--new-connection", action="store_true",
                    help="open a fresh TCP+TLS connection for every request")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    rng = random.Random(args.seed)
    iterations = max(1, args.requests // len(OPS))
    run_tag = uuid.uuid4().hex[:6]

    def make_client():
        return httpx.Client(base_url=args.base_url, verify=args.ca, timeout=args.timeout,
                            limits=httpx.Limits(max_keepalive_connections=1, max_connections=1))

    client = make_client()

    # Warm-up (not measured): TLS handshake + fetch a fixed product catalogue
    r = client.get("/products", params={"limit": 200})
    r.raise_for_status()
    product_ids = sorted(p["product_id"] for p in r.json()["items"])
    if not product_ids:
        raise SystemExit("no products in database: run the import step first")

    rows: list[dict] = []
    t_start = time.perf_counter()

    def do(op: str, method: str, url: str, i: int, **kw) -> httpx.Response | None:
        nonlocal client
        rid = f"{args.label}-{run_tag}-{i:04d}-{op}"
        headers = kw.pop("headers", {}) | {"X-Request-ID": rid}
        if args.new_connection:
            client.close()
            client = make_client()
        t0 = time.perf_counter()
        epoch = time.time()
        resp, err = None, ""
        try:
            resp = client.request(method, url, headers=headers, **kw)
        except httpx.HTTPError as e:
            err = type(e).__name__
        total = (time.perf_counter() - t0) * 1000.0
        app_ms, db_ms = parse_server_timing(resp.headers.get("server-timing") if resp else None)
        ok = resp is not None and resp.status_code < 400
        rows.append({
            "epoch": round(epoch, 6), "label": args.label, "iteration": i, "op": op,
            "request_id": rid, "status": resp.status_code if resp else 0, "ok": ok,
            "total_ms": round(total, 3), "app_ms": app_ms, "db_ms": db_ms,
            "bytes": len(resp.content) if resp else 0, "error": err or ("" if ok else f"HTTP {resp.status_code}"),
        })
        return resp if ok else None

    for i in range(iterations):
        pid = rng.choice(product_ids)
        cust = f"cust-{rng.randint(1, 500):04d}"
        qty = rng.randint(1, 3)
        do("list_products", "GET", "/products", i, params={"limit": 50, "skip": rng.randint(0, 100)})
        do("get_product", "GET", f"/products/{pid}", i)
        created = do("create_order", "POST", "/orders", i,
                     json={"customer_id": cust, "items": [{"product_id": pid, "qty": qty}]},
                     headers={"Idempotency-Key": f"{args.label}-{run_tag}-{i}"})
        if created is not None:
            oid = created.json()["order_id"]
            do("get_order", "GET", f"/orders/{oid}", i)
            do("pay_order", "PATCH", f"/orders/{oid}/status", i, json={"status": "paid"})
        else:  # keep the request count identical even if creation failed
            rows.append({"epoch": round(time.time(), 6), "label": args.label, "iteration": i, "op": "get_order",
                         "request_id": "", "status": 0, "ok": False, "total_ms": 0, "app_ms": None,
                         "db_ms": None, "bytes": 0, "error": "skipped: create failed"})
            rows.append({**rows[-1], "op": "pay_order"})

    wall = time.perf_counter() - t_start
    client.close()

    with open(os.path.join(args.out, "loadgen.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    summary = {"label": args.label, "seed": args.seed, "iterations": iterations,
               "new_connection_per_request": args.new_connection, **summarize(rows, wall)}
    with open(os.path.join(args.out, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    o = summary["overall"]
    print(f"[{args.label}] {o['success']}/{o['requests']} ok  p50={o['p50_ms']}ms  p95={o['p95_ms']}ms  "
          f"p99={o['p99_ms']}ms  err={o['error_rate']}  {summary['throughput_rps']} req/s")


if __name__ == "__main__":
    main()
