import asyncio
import logging
import json
import os
import uuid
import time
from contextlib import asynccontextmanager, suppress
from fastapi import FastAPI, HTTPException
import httpx
from pymongo import AsyncMongoClient
from services.common import OrderInput, instrument

log = logging.getLogger("payments_demo")


def create_app(mongo_uri=None, database=None, transport=None):
    async def settle(app, order):
        payload = {"order_id": order["_id"], **order["request"]}
        for attempt in range(app.state.attempts):
            try:
                response = await app.state.http.post(
                    "/payments",
                    json=payload,
                    headers={"Idempotency-Key": order["payment_key"]},
                )
                if response.status_code in (429, 502, 503, 504):
                    raise httpx.TransportError("Temporary payment failure")
                response.raise_for_status()
                result = response.json()
                if result["payload"] != payload or result["status"] not in (
                    "paid",
                    "failed",
                ):
                    raise ValueError("Invalid payment result")
                await app.state.collection.update_one(
                    {"_id": order["_id"], "status": "pending"},
                    {
                        "$set": {
                            "status": result["status"],
                            "transaction_id": result["transaction_id"],
                        }
                    },
                )
                return
            except (
                httpx.TransportError,
                httpx.HTTPStatusError,
                ValueError,
                KeyError,
            ) as exc:
                log.warning(
                    json.dumps(
                        {
                            "event": "payment_retry",
                            "order_id": order["_id"],
                            "attempt": attempt + 1,
                            "error_type": type(exc).__name__,
                        }
                    )
                )
                if (
                    isinstance(exc, httpx.HTTPStatusError)
                    and exc.response.status_code < 500
                    and exc.response.status_code != 429
                ):
                    await app.state.collection.update_one(
                        {"_id": order["_id"], "status": "pending"},
                        {
                            "$set": {
                                "next_attempt_at": time.time() + 60,
                                "last_error": "permanent_payment_error",
                            }
                        },
                    )
                    return  # Requires investigation; never invent a failed payment.
                if attempt + 1 < app.state.attempts:
                    await asyncio.sleep(0.1 * (2**attempt))
        await app.state.collection.update_one(
            {"_id": order["_id"], "status": "pending"},
            {
                "$set": {
                    "next_attempt_at": time.time() + app.state.recovery_interval,
                    "last_error": "payment_response_unavailable",
                }
            },
        )

    async def recover(app):
        while True:
            try:
                async for order in (
                    app.state.collection.find(
                        {"status": "pending", "next_attempt_at": {"$lte": time.time()}}
                    )
                    .sort("next_attempt_at", 1)
                    .limit(100)
                ):
                    await settle(app, order)
            except Exception as exc:
                log.error(
                    json.dumps(
                        {"event": "recovery_error", "error_type": type(exc).__name__}
                    )
                )
            await asyncio.sleep(app.state.recovery_interval)

    @asynccontextmanager
    async def lifespan(app):
        app.state.mongo = AsyncMongoClient(
            mongo_uri or os.getenv("MONGO_URI", "mongodb://localhost:27017"),
            serverSelectionTimeoutMS=2000,
        )
        app.state.collection = app.state.mongo[
            database or os.getenv("MONGO_DATABASE", "orders")
        ].orders
        await app.state.collection.create_index([("status", 1), ("next_attempt_at", 1)])
        app.state.attempts = int(os.getenv("PAYMENT_ATTEMPTS", "3"))
        app.state.recovery_interval = float(os.getenv("RECOVERY_INTERVAL_SECONDS", "5"))
        if not 1 <= app.state.attempts <= 10 or app.state.recovery_interval <= 0:
            raise ValueError(
                "PAYMENT_ATTEMPTS must be 1..10 and RECOVERY_INTERVAL_SECONDS positive"
            )
        app.state.http = httpx.AsyncClient(
            base_url=os.getenv("PAYMENTS_URL", "http://localhost:8001"),
            timeout=httpx.Timeout(
                float(os.getenv("PAYMENT_TIMEOUT_SECONDS", "2")), connect=1
            ),
            transport=transport,
        )
        worker = asyncio.create_task(recover(app))
        try:
            yield
        finally:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker
            await app.state.http.aclose()
            await app.state.mongo.close()

    app = FastAPI(title="Orders API", lifespan=lifespan)
    instrument(app, "orders")

    @app.get("/health/ready")
    async def ready():
        try:
            await app.state.mongo.admin.command("ping")
            r = await app.state.http.get("/health/ready")
            r.raise_for_status()
        except Exception:
            raise HTTPException(503, "Required dependency unavailable")
        return {"status": "ready"}

    def public(order):
        return {
            "id": order["_id"],
            "amount": order["request"]["amount"],
            "currency": order["request"]["currency"],
            "status": order["status"],
            "transaction_id": order.get("transaction_id"),
        }

    @app.post("/orders", status_code=201)
    async def create(payload: OrderInput):
        oid = str(uuid.uuid4())
        order = {
            "_id": oid,
            "request": payload.model_dump(),
            "payment_key": "order:" + oid,
            "status": "pending",
            "next_attempt_at": time.time() + app.state.recovery_interval,
        }
        await app.state.collection.insert_one(order)
        await settle(app, order)
        return public(await app.state.collection.find_one({"_id": oid}))

    @app.get("/orders/{order_id}")
    async def get(order_id: str):
        order = await app.state.collection.find_one({"_id": order_id})
        if not order:
            raise HTTPException(404, "Order not found")
        return public(order)

    return app


app = create_app()
