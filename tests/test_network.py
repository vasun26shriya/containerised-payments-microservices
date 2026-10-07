"""Real TCP and process-restart recovery against a real MongoDB."""

import os
import socket
import subprocess
import sys
import time
import uuid
import httpx
import pytest
from pymongo import MongoClient

pytestmark = pytest.mark.integration


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_live(url, process):
    for _ in range(100):
        if process.poll() is not None:
            raise AssertionError("API exited during startup")
        try:
            if httpx.get(url + "/health/live", timeout=0.5).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    raise AssertionError("API did not start")


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_real_timeout_and_process_restart():
    uri = os.getenv("TEST_MONGO_URI")
    if not uri:
        pytest.skip("Requires real MongoDB")
    db = "network_" + uuid.uuid4().hex
    pay_port, order_port = free_port(), free_port()
    pay_url, order_url = (
        f"http://127.0.0.1:{pay_port}",
        f"http://127.0.0.1:{order_port}",
    )
    processes = []

    def start(service, port, delay="0"):
        env = {
            **os.environ,
            "MONGO_URI": uri,
            "MONGO_DATABASE": db + "_" + service,
            "PAYMENTS_URL": pay_url,
            "PAYMENT_TIMEOUT_SECONDS": "0.15",
            "PAYMENT_ATTEMPTS": "2",
            "RECOVERY_INTERVAL_SECONDS": "0.1",
            "PAYMENT_RESPONSE_DELAY_SECONDS": delay,
        }
        p = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                f"services.{service}:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        processes.append(p)
        wait_live(f"http://127.0.0.1:{port}", p)
        return p

    mongo = MongoClient(uri, serverSelectionTimeoutMS=2000)
    try:
        pay = start("payments", pay_port, "2")
        orders = start("orders", order_port)
        r = httpx.post(
            order_url + "/orders", json={"amount": 9900, "currency": "USD"}, timeout=5
        )
        assert r.status_code == 201 and r.json()["status"] == "pending"
        oid = r.json()["id"]
        original = mongo[db + "_payments"].transactions.find_one(
            {"key": "order:" + oid}
        )
        assert original and original["status"] == "paid"
        # Restart BOTH processes; neither can rely on in-memory state.
        stop(orders)
        stop(pay)
        start("payments", pay_port)
        start("orders", order_port)
        for _ in range(100):
            recovered = httpx.get(order_url + "/orders/" + oid, timeout=3).json()
            if recovered["status"] == "paid":
                break
            time.sleep(0.1)
        assert recovered["status"] == "paid"
        assert recovered["transaction_id"] == original["transaction_id"]
        assert (
            mongo[db + "_payments"].transactions.count_documents(
                {"key": "order:" + oid}
            )
            == 1
        )
    finally:
        for p in processes:
            stop(p)
        mongo.drop_database(db + "_payments")
        mongo.drop_database(db + "_orders")
        mongo.close()
