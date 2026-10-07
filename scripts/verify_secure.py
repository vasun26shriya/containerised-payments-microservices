"""Verify bearer auth, database access controls and the secured deployed stack."""

import argparse
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import httpx
from smoke_stack import main as smoke


def main(args):
    root = Path(args.secrets)
    orders_token = (root / "orders-api-token").read_text().strip()
    payments_token = (root / "payments-api-token").read_text().strip()
    with httpx.Client(timeout=10) as client:
        for base, token in (
            (args.orders, payments_token),
            (args.payments, orders_token),
        ):
            path = "/orders/missing" if base == args.orders else "/payments"
            method = "GET" if base == args.orders else "POST"
            for headers in (
                {},
                {"Authorization": "Bearer wrong"},
                {"Authorization": "Bearer " + token},
            ):
                response = client.request(
                    method,
                    base + path,
                    headers=headers,
                    json={"order_id": "x", "amount": 100, "currency": "INR"}
                    if method == "POST"
                    else None,
                )
                assert response.status_code == 401, (base, response.status_code)
    # The general smoke verifier uses service-specific bearer tokens and confirms
    # the Orders -> Payments credential works, not just individual endpoints.
    import os

    os.environ["ORDERS_API_TOKEN"] = orders_token
    os.environ["PAYMENTS_API_TOKEN"] = payments_token
    os.environ["GRAFANA_ADMIN_PASSWORD"] = (
        (root / "grafana-password").read_text().strip()
    )
    smoke(
        SimpleNamespace(
            orders=args.orders,
            payments=args.payments,
            prometheus=args.prometheus,
            grafana=args.grafana,
            previous=None,
            evidence=args.evidence,
        )
    )
    compose = [
        "docker",
        "compose",
        "-p",
        args.project,
        "-f",
        "compose.yaml",
        "-f",
        "compose.secure.yaml",
        "exec",
        "-T",
        "mongo",
        "mongosh",
        "--quiet",
        "--eval",
    ]
    for service, other in (("orders", "payments"), ("payments", "orders")):
        js = (
            f"const own=db.getSiblingDB('{service}');"
            f"own.auth('{service}',require('fs').readFileSync('/run/secrets/{service}-db-password','utf8').trim());"
            f"const allowed=own.runCommand({{find:'{service}',limit:1}}).ok;"
            f"let forbidden=0;try {{db.getSiblingDB('{other}').runCommand({{find:'transactions',limit:1}});}} catch(error) {{forbidden=error.code;}}"
            "print(JSON.stringify({allowed,forbidden}));"
        )
        result = subprocess.run(
            compose + [js], check=True, capture_output=True, text=True
        )
        access = json.loads(result.stdout.strip().splitlines()[-1])
        assert access == {"allowed": 1, "forbidden": 13}, access
    result = json.loads(Path(args.evidence).read_text())
    result["security_checks"] = {
        "unauthenticated_rejected": True,
        "wrong_and_cross_service_tokens_rejected": True,
        "service_to_service_auth_verified": True,
        "database_users_cannot_read_other_service_database": True,
    }
    Path(args.evidence).write_text(json.dumps(result, indent=2) + "\n")
    print("PASS: secured APIs, per-service MongoDB authorization and monitoring")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--secrets", default=".run/secure/secrets")
    parser.add_argument("--project", default="payments-secure")
    parser.add_argument("--orders", default="http://127.0.0.1:28000")
    parser.add_argument("--payments", default="http://127.0.0.1:28001")
    parser.add_argument("--prometheus", default="http://127.0.0.1:29090")
    parser.add_argument("--grafana", default="http://127.0.0.1:23000")
    parser.add_argument("--evidence", default=".run/secure-smoke.json")
    main(parser.parse_args())
