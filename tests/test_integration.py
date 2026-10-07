import asyncio
import os
import uuid
from contextlib import AsyncExitStack
import httpx
import pytest
from pymongo import AsyncMongoClient
from services.payments import create_app as payments_app
from services.orders import create_app as orders_app

pytestmark = pytest.mark.integration


@pytest.fixture
async def system(monkeypatch):
    uri = os.getenv("TEST_MONGO_URI")
    if not uri:
        pytest.skip("Set TEST_MONGO_URI to a real MongoDB; CI always sets it")
    monkeypatch.setenv("RECOVERY_INTERVAL_SECONDS", "0.05")
    db = "test_" + uuid.uuid4().hex
    pay = payments_app(uri, db + "_payments")
    try:
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(pay.router.lifespan_context(pay))
            pc = await stack.enter_async_context(
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=pay), base_url="http://pay"
                )
            )
            order = orders_app(uri, db + "_orders", httpx.ASGITransport(app=pay))
            await stack.enter_async_context(order.router.lifespan_context(order))
            oc = await stack.enter_async_context(
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=order), base_url="http://orders"
                )
            )
            yield pay, order, pc, oc
    finally:
        mongo = AsyncMongoClient(uri, serverSelectionTimeoutMS=2000)
        try:
            await mongo.drop_database(db + "_payments")
            await mongo.drop_database(db + "_orders")
        finally:
            await mongo.close()


def body(outcome="success"):
    return {
        "order_id": "example",
        "amount": 1234,
        "currency": "INR",
        "outcome": outcome,
    }


@pytest.mark.parametrize("outcome,status", [("success", "paid"), ("failure", "failed")])
async def test_payment_and_order(system, outcome, status):
    pay, orders, pc, oc = system
    r = await pc.post(
        "/payments", json=body(outcome), headers={"Idempotency-Key": "key"}
    )
    assert r.status_code == 200 and r.json()["status"] == status
    r = await oc.post(
        "/orders", json={k: v for k, v in body(outcome).items() if k != "order_id"}
    )
    assert r.status_code == 201 and r.json()["status"] == status
    assert (await oc.get("/orders/" + r.json()["id"])).json() == r.json()
    assert (await oc.get("/orders/missing")).status_code == 404


async def test_sequential_concurrent_duplicates_and_conflict(system):
    pay, orders, pc, oc = system

    async def send(payload=None):
        return await pc.post(
            "/payments", json=payload or body(), headers={"Idempotency-Key": "same"}
        )

    results = await asyncio.gather(*(send() for _ in range(30)))
    assert all(r.status_code == 200 for r in results)
    assert len({r.json()["transaction_id"] for r in results}) == 1
    assert (await send()).json() == results[0].json()
    assert await pay.state.collection.count_documents({"key": "same"}) == 1
    indexes = await pay.state.collection.index_information()
    assert indexes["key_1"]["unique"]
    assert (await send({**body(), "amount": 99})).status_code == 409


async def test_timeout_retries_and_restart_recovery(system, monkeypatch):
    pay, orders, pc, oc = system
    attempts = []
    real = httpx.ASGITransport(app=pay)

    class TimeoutAfterCommit(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            if request.url.path == "/payments":
                attempts.append(request.headers["Idempotency-Key"])
                await real.handle_async_request(request)
                raise httpx.ReadTimeout("Response lost after commit", request=request)
            return await real.handle_async_request(request)

    await orders.state.http.aclose()
    orders.state.http = httpx.AsyncClient(
        base_url="http://pay", transport=TimeoutAfterCommit()
    )
    r = await oc.post("/orders", json={"amount": 1234, "currency": "INR"})
    assert r.status_code == 201 and r.json()["status"] == "pending"
    assert len(attempts) >= 3 and len(set(attempts)) == 1
    assert await pay.state.collection.count_documents({"key": attempts[0]}) == 1
    # A fresh application instance connects to the same persisted orders.
    uri = os.environ["TEST_MONGO_URI"]
    restarted = orders_app(
        uri, orders.state.collection.database.name, httpx.ASGITransport(app=pay)
    )
    async with restarted.router.lifespan_context(restarted):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=restarted), base_url="http://orders"
        ) as client:
            for _ in range(100):
                recovered = (await client.get("/orders/" + r.json()["id"])).json()
                if recovered["status"] == "paid":
                    break
                await asyncio.sleep(0.05)
            assert recovered["status"] == "paid"
    assert await pay.state.collection.count_documents({"key": attempts[0]}) == 1


async def test_health_metrics_and_validation(system):
    pay, orders, pc, oc = system
    for client in (pc, oc):
        assert (await client.get("/health/live")).status_code == 200
        assert (await client.get("/health/ready")).status_code == 200
    await oc.get("/orders/random-one")
    await oc.get("/orders/random-two")
    metrics = (await oc.get("/metrics")).text
    assert 'route="/orders/{order_id}"' in metrics
    assert "random-one" not in metrics
    assert "http_request_duration_seconds_bucket" in metrics
    assert (await pc.post("/payments", json=body())).status_code == 422
    assert (
        await pc.post(
            "/payments",
            json={**body(), "amount": 1.5},
            headers={"Idempotency-Key": "bad"},
        )
    ).status_code == 422

    class Unavailable:
        async def command(self, *args):
            raise RuntimeError("offline")

    class Offline:
        admin = Unavailable()

    original = pay.state.mongo
    pay.state.mongo = Offline()
    try:
        assert (await pc.get("/health/live")).status_code == 200
        assert (await pc.get("/health/ready")).status_code == 503
        assert (await oc.get("/health/ready")).status_code == 503
    finally:
        pay.state.mongo = original


async def test_concurrent_conflicting_payloads(system):
    pay, orders, pc, oc = system

    async def send(amount):
        return await pc.post(
            "/payments",
            json={**body(), "amount": amount},
            headers={"Idempotency-Key": "race-conflict"},
        )

    responses = await asyncio.gather(*(send(100 if i % 2 else 200) for i in range(30)))
    assert {r.status_code for r in responses} == {200, 409}
    winner = await pay.state.collection.find_one({"key": "race-conflict"})
    assert await pay.state.collection.count_documents({"key": "race-conflict"}) == 1
    assert all(
        r.json()["transaction_id"] == winner["transaction_id"]
        for r in responses
        if r.status_code == 200
    )


async def test_temporary_unavailable_retry(system):
    pay, orders, pc, oc = system
    requests = []
    real = httpx.ASGITransport(app=pay)

    class UnavailableOnce(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            if request.url.path == "/payments":
                requests.append((request.headers["Idempotency-Key"], request.content))
                if len(requests) == 1:
                    return httpx.Response(
                        503,
                        json={
                            "error": {
                                "code": "503",
                                "message": "temporarily unavailable",
                            }
                        },
                    )
            return await real.handle_async_request(request)

    await orders.state.http.aclose()
    orders.state.http = httpx.AsyncClient(
        base_url="http://pay", transport=UnavailableOnce()
    )
    r = await oc.post("/orders", json={"amount": 100, "currency": "USD"})
    assert r.json()["status"] == "paid"
    assert len(requests) >= 2 and len(set(requests)) == 1
