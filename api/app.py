"""
ShopNet Orders API (Module B)

A small e-commerce order service backed by MongoDB, served over HTTPS.

Every response carries timing headers so a client can separate network time
from server time:
    Server-Timing: app;dur=<total ms in the API>, db;dur=<ms spent in MongoDB>
    X-Request-ID:  echoed from the client (or generated)

Every request is also written as one JSON line to /logs/api.log for correlation
with packet captures and load-generator records (Module D).
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from pymongo import AsyncMongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://db.shop.local:27017")
MONGO_DB = os.environ.get("MONGO_DB", "shop")
LOG_FILE = os.environ.get("API_LOG_FILE", "/logs/api.log")

# ---------------------------------------------------------------- logging ---
log = logging.getLogger("shopnet")
log.setLevel(logging.INFO)
_fmt = logging.Formatter("%(message)s")
_sh = logging.StreamHandler()
_sh.setFormatter(_fmt)
log.addHandler(_sh)
try:
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    _fh = logging.FileHandler(LOG_FILE)
    _fh.setFormatter(_fmt)
    log.addHandler(_fh)
except OSError:
    pass  # stdout-only if /logs is not mounted


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def emit(event: str, **fields: Any) -> None:
    log.info(json.dumps({"ts": now_iso(), "epoch": round(time.time(), 3), "event": event, **fields}))


# ---------------------------------------------------------------- MongoDB ---
# Short timeouts so a database or network failure shows up within ~2 s
# instead of hanging requests (important for the failure/recovery tests).
client = AsyncMongoClient(
    MONGO_URI,
    serverSelectionTimeoutMS=2000,
    connectTimeoutMS=2000,
    socketTimeoutMS=4000,
    appname="shopnet-api",
)
db = client[MONGO_DB]
products = db["products"]
orders = db["orders"]

app = FastAPI(title="ShopNet Orders API", version="1.0")


async def timed(request: Request, awaitable):
    """Await a MongoDB operation and add its duration to request.state.db_ms."""
    t0 = time.perf_counter()
    try:
        return await awaitable
    finally:
        request.state.db_ms += (time.perf_counter() - t0) * 1000.0


@app.on_event("startup")
async def startup() -> None:
    emit("startup", mongo_db=MONGO_DB)
    try:
        await orders.create_index("customer_id")
        await orders.create_index("status")
        await orders.create_index("idempotency_key", unique=True, sparse=True)
        await products.create_index("category")
        emit("indexes_ready")
    except PyMongoError as e:  # DB may not be up yet; health check will show it
        emit("db_unavailable_at_startup", error=str(e))


@app.middleware("http")
async def access_log(request: Request, call_next):
    request.state.db_ms = 0.0
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    t0 = time.perf_counter()
    status, err = 500, None
    try:
        response = await call_next(request)
        status = response.status_code
    except Exception as e:  # noqa: BLE001
        err = repr(e)
        response = JSONResponse({"error": "internal error"}, status_code=500)
    total = (time.perf_counter() - t0) * 1000.0
    db_ms = request.state.db_ms
    response.headers["X-Request-ID"] = rid
    response.headers["Server-Timing"] = f"app;dur={total:.2f}, db;dur={db_ms:.2f}"
    emit(
        "request",
        request_id=rid,
        client=request.client.host if request.client else None,
        method=request.method,
        path=request.url.path,
        status=status,
        app_ms=round(total, 2),
        db_ms=round(db_ms, 2),
        error=err,
    )
    return response


@app.exception_handler(PyMongoError)
async def mongo_error(request: Request, exc: PyMongoError):
    emit("db_error", path=request.url.path, error=type(exc).__name__, detail=str(exc)[:300])
    return JSONResponse({"error": "database unavailable", "type": type(exc).__name__}, status_code=503)


# ----------------------------------------------------------------- models ---
class OrderItem(BaseModel):
    product_id: str = Field(min_length=1)
    qty: int = Field(ge=1, le=100)


class OrderCreate(BaseModel):
    customer_id: str = Field(min_length=1, max_length=64)
    items: list[OrderItem] = Field(min_length=1, max_length=20)


class StatusUpdate(BaseModel):
    status: str


# Allowed order lifecycle transitions
TRANSITIONS = {
    "created": {"paid", "canceled"},
    "paid": {"shipped", "canceled"},
    "shipped": {"delivered"},
    "delivered": set(),
    "canceled": set(),
}


def public_order(doc: dict) -> dict:
    doc = dict(doc)
    doc["order_id"] = doc.pop("_id")
    doc.pop("idempotency_key", None)
    return doc


# -------------------------------------------------------------- endpoints ---
@app.get("/health")
async def health(request: Request):
    """Liveness + database reachability. 200 only if MongoDB answers a ping."""
    try:
        await timed(request, client.admin.command("ping"))
        return {"status": "ok", "db": "up", "db_ms": round(request.state.db_ms, 2), "ts": now_iso()}
    except PyMongoError as e:
        emit("health_fail", error=type(e).__name__)
        return JSONResponse({"status": "degraded", "db": "down", "error": type(e).__name__, "ts": now_iso()},
                            status_code=503)


@app.get("/products")
async def list_products(request: Request, category: str | None = None,
                        limit: int = Query(20, ge=1, le=200), skip: int = Query(0, ge=0)):
    q = {"category": category} if category else {}
    cur = products.find(q).sort("_id", 1).skip(skip).limit(limit)
    docs = await timed(request, cur.to_list(length=limit))
    return {"count": len(docs), "items": [{"product_id": d.pop("_id"), **d} for d in docs]}


@app.get("/products/{product_id}")
async def get_product(request: Request, product_id: str):
    d = await timed(request, products.find_one({"_id": product_id}))
    if not d:
        raise HTTPException(404, f"product {product_id} not found")
    return {"product_id": d.pop("_id"), **d}


@app.post("/orders", status_code=201)
async def create_order(request: Request, body: OrderCreate,
                       idempotency_key: str | None = Header(default=None)):
    # Idempotency: a retried request with the same key returns the original order
    if idempotency_key:
        existing = await timed(request, orders.find_one({"idempotency_key": idempotency_key}))
        if existing:
            return JSONResponse(public_order(existing), status_code=200,
                                headers={"Idempotent-Replay": "true"})

    # Reserve stock atomically per item; roll back if any item fails
    reserved: list[tuple[str, int]] = []
    lines, total = [], 0.0
    for it in body.items:
        p = await timed(request, products.find_one_and_update(
            {"_id": it.product_id, "stock": {"$gte": it.qty}},
            {"$inc": {"stock": -it.qty}},
            return_document=ReturnDocument.AFTER))
        if not p:
            for pid, q in reserved:
                await timed(request, products.update_one({"_id": pid}, {"$inc": {"stock": q}}))
            exists = await timed(request, products.find_one({"_id": it.product_id}, {"_id": 1}))
            if not exists:
                raise HTTPException(404, f"product {it.product_id} not found")
            raise HTTPException(409, f"insufficient stock for {it.product_id}")
        reserved.append((it.product_id, it.qty))
        lines.append({"product_id": it.product_id, "qty": it.qty, "unit_price": p["price"]})
        total += p["price"] * it.qty

    ts = now_iso()
    doc = {"_id": uuid.uuid4().hex, "customer_id": body.customer_id, "items": lines,
           "total": round(total, 2), "status": "created", "created_at": ts, "updated_at": ts,
           "source": "api"}
    if idempotency_key:
        doc["idempotency_key"] = idempotency_key
    try:
        await timed(request, orders.insert_one(doc))
    except DuplicateKeyError:  # concurrent retry with the same key won the race
        for pid, q in reserved:
            await timed(request, products.update_one({"_id": pid}, {"$inc": {"stock": q}}))
        existing = await timed(request, orders.find_one({"idempotency_key": idempotency_key}))
        return JSONResponse(public_order(existing), status_code=200, headers={"Idempotent-Replay": "true"})
    return public_order(doc)


@app.get("/orders/{order_id}")
async def get_order(request: Request, order_id: str):
    d = await timed(request, orders.find_one({"_id": order_id}))
    if not d:
        raise HTTPException(404, f"order {order_id} not found")
    return public_order(d)


@app.get("/orders")
async def list_orders(request: Request, customer_id: str | None = None, status: str | None = None,
                      limit: int = Query(20, ge=1, le=200)):
    q: dict[str, Any] = {}
    if customer_id:
        q["customer_id"] = customer_id
    if status:
        q["status"] = status
    docs = await timed(request, orders.find(q).sort("created_at", -1).limit(limit).to_list(length=limit))
    return {"count": len(docs), "items": [public_order(d) for d in docs]}


@app.patch("/orders/{order_id}/status")
async def update_status(request: Request, order_id: str, body: StatusUpdate):
    if body.status not in TRANSITIONS:
        raise HTTPException(400, f"unknown status '{body.status}'")
    d = await timed(request, orders.find_one({"_id": order_id}, {"status": 1}))
    if not d:
        raise HTTPException(404, f"order {order_id} not found")
    cur = d["status"]
    if body.status not in TRANSITIONS.get(cur, set()):
        raise HTTPException(409, f"cannot change status {cur} -> {body.status}")
    # Conditional update guards against a concurrent change between read and write
    updated = await timed(request, orders.find_one_and_update(
        {"_id": order_id, "status": cur},
        {"$set": {"status": body.status, "updated_at": now_iso()}},
        return_document=ReturnDocument.AFTER))
    if not updated:
        raise HTTPException(409, "order changed concurrently, retry")
    return public_order(updated)


@app.get("/stats")
async def stats(request: Request):
    n_products = await timed(request, products.estimated_document_count())
    n_orders = await timed(request, orders.estimated_document_count())
    pipeline = [{"$group": {"_id": "$status", "n": {"$sum": 1}}}]
    cursor = await timed(request, orders.aggregate(pipeline))
    by_status = await timed(request, cursor.to_list(length=50))
    return {"products": n_products, "orders": n_orders,
            "orders_by_status": {r["_id"]: r["n"] for r in by_status}}
