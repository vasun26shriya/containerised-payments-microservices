import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, HTTPException
from pymongo import AsyncMongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError
from services.common import PaymentInput, instrument


def create_app(mongo_uri=None, database=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.mongo = AsyncMongoClient(
            mongo_uri or os.getenv("MONGO_URI", "mongodb://localhost:27017"),
            serverSelectionTimeoutMS=2000,
        )
        app.state.collection = app.state.mongo[
            database or os.getenv("MONGO_DATABASE", "payments")
        ].transactions
        await app.state.collection.create_index("key", unique=True)
        try:
            yield
        finally:
            await app.state.mongo.close()

    app = FastAPI(title="Payments API", lifespan=lifespan)
    instrument(app, "payments")

    @app.get("/health/ready")
    async def ready():
        try:
            await app.state.mongo.admin.command("ping")
        except Exception:
            raise HTTPException(503, "MongoDB unavailable")
        return {"status": "ready"}

    @app.post("/payments")
    async def pay(
        payload: PaymentInput,
        idempotency_key: str = Header(min_length=1, max_length=128),
    ):
        # One atomic upsert persists the entire simulated result. No external side effect.
        record = {
            "key": idempotency_key,
            "payload": payload.model_dump(),
            "transaction_id": str(uuid.uuid4()),
            "status": "paid" if payload.outcome == "success" else "failed",
        }
        try:
            original = await app.state.collection.find_one_and_update(
                {"key": idempotency_key},
                {"$setOnInsert": record},
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            original = await app.state.collection.find_one({"key": idempotency_key})
        if original["payload"] != payload.model_dump():
            raise HTTPException(
                409, "Idempotency key already used with a different payload"
            )
        # Delay AFTER commit demonstrates an ambiguous response without duplicate processing.
        await asyncio.sleep(float(os.getenv("PAYMENT_RESPONSE_DELAY_SECONDS", "0")))
        return {k: original[k] for k in ("transaction_id", "status", "payload")}

    return app


app = create_app()
