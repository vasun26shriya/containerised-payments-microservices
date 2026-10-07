"""Verify deployed APIs, Prometheus targets and provisioned Grafana resources."""

import argparse
import json
import os
from pathlib import Path
import time
import uuid
import httpx


def eventually(check, seconds=120):
    deadline = time.monotonic() + seconds
    last = None
    while time.monotonic() < deadline:
        try:
            return check()
        except (AssertionError, httpx.HTTPError, KeyError) as exc:
            last = exc
            time.sleep(2)
    raise AssertionError(f"Readiness check failed: {last}")


def main(a):
    def authorize(request):
        for base, name in (
            (a.orders, "ORDERS_API_TOKEN"),
            (a.payments, "PAYMENTS_API_TOKEN"),
        ):
            if str(request.url).startswith(base.rstrip("/") + "/"):
                token = os.getenv(name)
                if token:
                    request.headers["Authorization"] = "Bearer " + token

    with httpx.Client(timeout=10, event_hooks={"request": [authorize]}) as client:

        def ready(base):
            r = client.get(base + "/health/ready")
            r.raise_for_status()
            assert r.json()["status"] == "ready"

        eventually(lambda: ready(a.orders))
        eventually(lambda: ready(a.payments))
        evidence = {"orders_url": a.orders, "payments_url": a.payments}
        for outcome, status in [("success", "paid"), ("failure", "failed")]:
            r = client.post(
                a.orders + "/orders",
                json={"amount": 1234, "currency": "INR", "outcome": outcome},
            )
            assert r.status_code == 201, r.text
            order = r.json()
            assert order["status"] == status, order
            assert client.get(a.orders + "/orders/" + order["id"]).json() == order
            evidence[outcome] = order
        payload = {"order_id": "smoke", "amount": 100, "currency": "USD"}
        headers = {"Idempotency-Key": "smoke-" + uuid.uuid4().hex}
        first = client.post(a.payments + "/payments", json=payload, headers=headers)
        first.raise_for_status()
        duplicate = client.post(a.payments + "/payments", json=payload, headers=headers)
        assert duplicate.status_code == 200 and duplicate.json() == first.json()
        conflict = client.post(
            a.payments + "/payments", json={**payload, "amount": 101}, headers=headers
        )
        assert conflict.status_code == 409
        if a.previous:
            prior = json.loads(Path(a.previous).read_text())
            assert (
                client.get(a.orders + "/orders/" + prior["success"]["id"]).json()
                == prior["success"]
            ), "Persisted order changed across release"
        for base in (a.orders, a.payments):
            assert "http_requests_total" in client.get(base + "/metrics").text
        if a.prometheus:

            def targets():
                r = client.get(a.prometheus + "/api/v1/targets")
                r.raise_for_status()
                active = r.json()["data"]["activeTargets"]
                assert len(active) >= 2 and all(t["health"] == "up" for t in active), (
                    active
                )
                return active

            evidence["prometheus_targets"] = eventually(targets)
        if a.grafana:
            auth = (
                "admin",
                os.getenv("GRAFANA_ADMIN_PASSWORD", "local-demo-change-me"),
            )

            def dashboard():
                r = client.get(a.grafana + "/api/dashboards/uid/payments", auth=auth)
                r.raise_for_status()
                data = r.json()
                assert data["meta"]["provisioned"] is True
                assert len(data["dashboard"]["panels"]) == 3
                ds = client.get(
                    a.grafana + "/api/datasources/uid/prometheus/health", auth=auth
                )
                ds.raise_for_status()
                assert ds.json()["status"] == "OK", ds.text
                return data["dashboard"]

            evidence["grafana_dashboard"] = eventually(dashboard)
        out = Path(a.evidence)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(evidence, indent=2))
        print(f"PASS: deployed stack smoke checks; evidence: {out}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--orders", default="http://127.0.0.1:8000")
    p.add_argument("--payments", default="http://127.0.0.1:8001")
    p.add_argument("--prometheus", default="")
    p.add_argument("--grafana", default="")
    p.add_argument("--previous")
    p.add_argument("--evidence", default=".run/smoke.json")
    main(p.parse_args())
