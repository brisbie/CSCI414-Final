#!/usr/bin/env python3

import argparse
import csv
import os
import random
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient

OLIST = os.environ.get("OLIST_DIR", "/data/olist")
STATUS_MAP = {  # Olist order_status -> our lifecycle
    "created": "created", "approved": "paid", "invoiced": "paid", "processing": "paid",
    "shipped": "shipped", "delivered": "delivered", "canceled": "canceled", "unavailable": "canceled",
}


def read_csv(name):
    with open(os.path.join(OLIST, name), newline="", encoding="utf-8-sig") as f:
        yield from csv.DictReader(f)


def olist_available() -> bool:
    need = ["olist_orders_dataset.csv", "olist_order_items_dataset.csv", "olist_products_dataset.csv"]
    return all(os.path.exists(os.path.join(OLIST, n)) for n in need)


def load_olist(n_orders: int, rng: random.Random):
    tr = {}
    if os.path.exists(os.path.join(OLIST, "product_category_name_translation.csv")):
        tr = {r["product_category_name"]: r["product_category_name_english"]
              for r in read_csv("product_category_name_translation.csv")}

    orders_raw = sorted(read_csv("olist_orders_dataset.csv"), key=lambda r: r["order_purchase_timestamp"])
    items_by_order = defaultdict(list)
    for r in read_csv("olist_order_items_dataset.csv"):
        items_by_order[r["order_id"]].append(r)
    pay = {}
    if os.path.exists(os.path.join(OLIST, "olist_order_payments_dataset.csv")):
        for r in read_csv("olist_order_payments_dataset.csv"):
            pay.setdefault(r["order_id"], r["payment_type"])

    chosen = [o for o in orders_raw if o["order_id"] in items_by_order][:n_orders]
    prices = defaultdict(list)
    orders = []
    for o in chosen:
        qty = defaultdict(int)
        unit = {}
        for it in items_by_order[o["order_id"]]:  # one row per unit in Olist
            qty[it["product_id"]] += 1
            unit[it["product_id"]] = float(it["price"])
            prices[it["product_id"]].append(float(it["price"]))
        items = [{"product_id": p, "qty": q, "unit_price": unit[p]} for p, q in qty.items()]
        ts = o["order_purchase_timestamp"].replace(" ", "T") + "+00:00"
        doc = {"_id": o["order_id"], "customer_id": o["customer_id"], "items": items,
               "total": round(sum(i["qty"] * i["unit_price"] for i in items), 2),
               "status": STATUS_MAP.get(o["order_status"], "created"),
               "created_at": ts, "updated_at": ts, "source": "olist"}
        if o["order_id"] in pay:
            doc["payment_type"] = pay[o["order_id"]]
        orders.append(doc)

    products = []
    for r in read_csv("olist_products_dataset.csv"):
        pid = r["product_id"]
        if pid not in prices:
            continue
        cat = tr.get(r["product_category_name"], r["product_category_name"] or "uncategorized")
        products.append({"_id": pid, "name": f"{cat.replace('_', ' ')} item {pid[:6]}", "category": cat,
                         "price": round(statistics.median(prices[pid]), 2),
                         "weight_g": int(float(r["product_weight_g"] or 0)),
                         "stock": 100000, "source": "olist"})
    return products, orders


CATEGORIES = ["electronics", "home", "toys", "sports", "books", "garden", "beauty", "auto", "office", "pet"]
ADJ = ["Basic", "Pro", "Compact", "Deluxe", "Eco", "Smart", "Classic", "Mini", "Ultra", "Travel"]
NOUN = ["Lamp", "Kettle", "Drone", "Backpack", "Notebook", "Speaker", "Mug", "Charger", "Chair", "Bottle",
        "Headset", "Planter", "Brush", "Toolkit", "Blanket"]


def load_synthetic(n_orders: int, rng: random.Random, n_products: int = 500):
    products = []
    for i in range(n_products):
        cat = rng.choice(CATEGORIES)
        products.append({"_id": f"P{i:05d}", "name": f"{rng.choice(ADJ)} {rng.choice(NOUN)}", "category": cat,
                         "price": round(rng.uniform(4, 400), 2), "weight_g": rng.randint(50, 8000),
                         "stock": 100000, "source": "synthetic"})
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    statuses = ["delivered"] * 7 + ["shipped", "paid", "canceled"]
    orders = []
    for i in range(n_orders):
        items = []
        for p in rng.sample(products, rng.randint(1, 3)):
            items.append({"product_id": p["_id"], "qty": rng.randint(1, 3), "unit_price": p["price"]})
        ts = (start + timedelta(minutes=rng.randint(0, 60 * 24 * 300))).isoformat()
        orders.append({"_id": f"O{i:06d}", "customer_id": f"cust-{rng.randint(1, 500):04d}", "items": items,
                       "total": round(sum(x["qty"] * x["unit_price"] for x in items), 2),
                       "status": rng.choice(statuses), "created_at": ts, "updated_at": ts, "source": "synthetic"})
    return products, orders


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="drop existing collections first")
    ap.add_argument("--if-empty", action="store_true", help="do nothing if products already exist")
    ap.add_argument("--orders", type=int, default=5000)
    ap.add_argument("--source", choices=["auto", "olist", "synthetic"], default="auto")
    ap.add_argument("--seed", type=int, default=414)
    a = ap.parse_args()

    uri = os.environ.get("MONGO_URI", "mongodb://db.shop.local:27017")
    db = MongoClient(uri, serverSelectionTimeoutMS=5000)[os.environ.get("MONGO_DB", "shop")]

    if a.if_empty and db.products.estimated_document_count() > 0:
        print(f"[import] products already loaded ({db.products.estimated_document_count()}), skipping")
        return

    src = a.source
    if src == "auto":
        src = "olist" if olist_available() else "synthetic"
    if src == "olist" and not olist_available():
        sys.exit(f"[import] Olist CSVs not found in {OLIST}")

    rng = random.Random(a.seed)
    products, orders = (load_olist if src == "olist" else load_synthetic)(a.orders, rng)

    if a.reset:
        db.products.drop()
        db.orders.drop()
    db.products.insert_many(products, ordered=False)
    db.orders.insert_many(orders, ordered=False)
    db.orders.create_index("customer_id")
    db.orders.create_index("status")
    db.orders.create_index("idempotency_key", unique=True, sparse=True)
    db.products.create_index("category")

    print(f"[import] source={src}  products={len(products)}  orders={len(orders)}")
    print("[import] sample product:", products[0])
    print("[import] sample order:  ", orders[0])


if __name__ == "__main__":
    main()
