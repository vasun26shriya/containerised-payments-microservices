"""Record actual API responses as a portable interactive portfolio replay."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time
import uuid
import httpx


def main(args):
    steps = []
    tokens = {}
    if args.secure:
        for service in ("orders", "payments"):
            tokens[service] = (
                (Path(args.secrets) / (service + "-api-token")).read_text().strip()
            )

    def request(service, method, path, body=None, key=None, authorize=True):
        base = args.orders if service == "orders" else args.payments
        headers = {}
        if authorize and service in tokens:
            headers["Authorization"] = "Bearer " + tokens[service]
        if key:
            headers["Idempotency-Key"] = key
        result = client.request(method, base + path, json=body, headers=headers)
        return result

    def capture(title, explanation, method, path, result, body=None):
        steps.append(
            {
                "title": title,
                "explanation": explanation,
                "command": method + " " + path,
                "request": body,
                "http_status": result.status_code,
                "response": result.json(),
            }
        )
        print(f"{title}: HTTP {result.status_code}")

    with httpx.Client(timeout=15) as client:
        if args.secure:
            response = request(
                "orders",
                "POST",
                "/orders",
                {"amount": 1250, "currency": "INR"},
                authorize=False,
            )
            assert response.status_code == 401
            capture(
                "Authentication",
                "Requests without the Orders bearer token are rejected before database access.",
                "POST",
                "/orders",
                response,
            )
        for outcome, expected in (("success", "paid"), ("failure", "failed")):
            body = {"amount": 1250, "currency": "INR", "outcome": outcome}
            response = request("orders", "POST", "/orders", body)
            assert response.status_code == 201 and response.json()["status"] == expected
            capture(
                "Successful order" if outcome == "success" else "Declined payment",
                "1250 integer minor units = INR 12.50. A business decline is a terminal result, not a transport error.",
                "POST",
                "/orders",
                response,
                body,
            )
            if outcome == "success":
                oid = response.json()["id"]
                fetched = request("orders", "GET", "/orders/" + oid)
                assert fetched.json() == response.json()
                capture(
                    "Retrieve persisted order",
                    "The order and transaction ID are persisted in MongoDB.",
                    "GET",
                    "/orders/" + oid,
                    fetched,
                )
        key = "portfolio-" + uuid.uuid4().hex
        payload = {"order_id": "portfolio-demo", "amount": 1250, "currency": "INR"}
        first = request("payments", "POST", "/payments", payload, key)
        duplicate = request("payments", "POST", "/payments", payload, key)
        assert first.status_code == 200 and duplicate.json() == first.json()
        capture(
            "First payment",
            "A unique key and atomic upsert persist the simulated result together.",
            "POST",
            "/payments",
            first,
            payload,
        )
        capture(
            "Safe duplicate",
            "Same key and payload return the original transaction ID. No second transaction is created.",
            "POST",
            "/payments",
            duplicate,
            payload,
        )
        conflict = request(
            "payments", "POST", "/payments", {**payload, "amount": 1300}, key
        )
        assert conflict.status_code == 409
        capture(
            "Payload conflict",
            "Reusing that key for a different amount returns HTTP 409.",
            "POST",
            "/payments",
            conflict,
        )
        if args.exercise_recovery:
            if not args.secure:
                raise ValueError("Recovery exercise requires the separate secured demo")
            import os

            compose = [
                "docker",
                "compose",
                "-p",
                "payments-secure",
                "-f",
                "compose.yaml",
                "-f",
                "compose.secure.yaml",
            ]
            environment = dict(os.environ, PAYMENT_RESPONSE_DELAY_SECONDS="4")
            try:
                subprocess.run(
                    compose + ["up", "-d", "--force-recreate", "--wait", "payments"],
                    env=environment,
                    check=True,
                    capture_output=True,
                )
                response = request(
                    "orders", "POST", "/orders", {"amount": 2500, "currency": "INR"}
                )
                assert (
                    response.status_code == 201
                    and response.json()["status"] == "pending"
                )
                recovering_id = response.json()["id"]
                capture(
                    "Ambiguous timeout",
                    "Payments persists the result before delaying its response. Orders keeps pending because a timeout cannot prove a decline.",
                    "POST",
                    "/orders",
                    response,
                )
                subprocess.run(
                    compose + ["restart", "orders"], check=True, capture_output=True
                )
            finally:
                subprocess.run(
                    compose + ["up", "-d", "--force-recreate", "--wait", "payments"],
                    env=dict(os.environ, PAYMENT_RESPONSE_DELAY_SECONDS="0"),
                    check=True,
                    capture_output=True,
                )
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                try:
                    recovered = request("orders", "GET", "/orders/" + recovering_id)
                    if (
                        recovered.status_code == 200
                        and recovered.json()["status"] == "paid"
                    ):
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(2)
            else:
                raise AssertionError("Restart recovery did not converge")
            capture(
                "Recovered after restart",
                "The restarted Orders worker reuses the persisted key and receives the original payment result.",
                "GET",
                "/orders/" + recovering_id,
                recovered,
            )
    recording = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "mode": "secured" if args.secure else "development",
        "steps": steps,
    }
    destination = Path(args.output)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "session.json").write_text(json.dumps(recording, indent=2) + "\n")
    template = Path("docs/demo/player-template.html").read_text(encoding="utf-8")
    safe_json = json.dumps(recording).replace("<", "\\u003c")
    (destination / "index.html").write_text(
        template.replace("__RECORDING__", safe_json), encoding="utf-8"
    )
    print(f"PASS: recorded actual responses; replay: {destination / 'index.html'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--orders", default="http://127.0.0.1:8000")
    parser.add_argument("--payments", default="http://127.0.0.1:8001")
    parser.add_argument("--secure", action="store_true")
    parser.add_argument("--secrets", default=".run/secure/secrets")
    parser.add_argument("--exercise-recovery", action="store_true")
    parser.add_argument("--output", default="docs/demo")
    main(parser.parse_args())
