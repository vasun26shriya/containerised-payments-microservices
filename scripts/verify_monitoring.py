"""Verify real Prometheus/Alertmanager firing against API dependency failures.
Requires local MongoDB, Prometheus and Alertmanager binaries supplied as arguments.
Creates only isolated local processes/data; always shuts them down.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
import socket
import httpx
from pymongo import MongoClient


def port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def stop(p):
    if p.poll() is None:
        p.terminate()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait(timeout=5)


def main(a):
    work = Path(".run/monitoring-demo")
    work.mkdir(parents=True, exist_ok=True)
    (work / "evidence.json").unlink(missing_ok=True)
    data = work / "mongo"
    data.mkdir(exist_ok=True)
    mongo_port, pay_port, order_port, prom_port, am_port = [port() for _ in range(5)]
    processes = []
    logs = []

    def spawn(command, env=None):
        log = (work / f"process-{len(processes)}.log").open("w")
        logs.append(log)
        p = subprocess.Popen(command, env=env, stdout=log, stderr=log)
        processes.append(p)
        return p

    def wait(url, p):
        for _ in range(200):
            if p.poll() is not None:
                raise RuntimeError("Process exited; see .run/monitoring-demo logs")
            try:
                if httpx.get(url, timeout=1).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        raise RuntimeError("Startup timeout")

    uri = f"mongodb://127.0.0.1:{mongo_port}"
    try:
        mongo = spawn(
            [
                a.mongo_bin,
                "--dbpath",
                str(data),
                "--bind_ip",
                "127.0.0.1",
                "--port",
                str(mongo_port),
            ]
        )
        with MongoClient(uri, serverSelectionTimeoutMS=10000) as client:
            client.admin.command("ping")
        env = {
            **os.environ,
            "MONGO_URI": uri,
            "MONGO_DATABASE": "monitoring_demo_payments",
        }
        pay = spawn(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "services.payments:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(pay_port),
            ],
            env,
        )
        wait(f"http://127.0.0.1:{pay_port}/health/ready", pay)
        env = {
            **env,
            "MONGO_DATABASE": "monitoring_demo_orders",
            "PAYMENTS_URL": f"http://127.0.0.1:{pay_port}",
        }
        orders = spawn(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "services.orders:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(order_port),
            ],
            env,
        )
        wait(f"http://127.0.0.1:{order_port}/health/ready", orders)
        shutil.copyfile("monitoring/alerts.yml", work / "alerts.yml")
        shutil.copyfile("monitoring/alertmanager.yml", work / "alertmanager.yml")
        config = {
            "global": {"scrape_interval": "15s", "evaluation_interval": "15s"},
            "rule_files": ["alerts.yml"],
            "alerting": {
                "alertmanagers": [
                    {"static_configs": [{"targets": [f"127.0.0.1:{am_port}"]}]}
                ]
            },
            "scrape_configs": [
                {
                    "job_name": "payments-apis",
                    "static_configs": [
                        {
                            "targets": [
                                f"127.0.0.1:{pay_port}",
                                f"127.0.0.1:{order_port}",
                            ]
                        }
                    ],
                }
            ],
        }
        (work / "prometheus.yml").write_text(json.dumps(config))
        am = spawn(
            [
                a.alertmanager_bin,
                "--config.file=" + str(work / "alertmanager.yml"),
                "--storage.path=" + str(work / "alertmanager-data"),
                "--web.listen-address=127.0.0.1:" + str(am_port),
                "--cluster.listen-address=",
            ]
        )
        wait(f"http://127.0.0.1:{am_port}/-/ready", am)
        prom = spawn(
            [
                a.prometheus_bin,
                "--config.file=" + str(work / "prometheus.yml"),
                "--storage.tsdb.path=" + str(work / "prometheus-data"),
                "--web.listen-address=127.0.0.1:" + str(prom_port),
            ]
        )
        wait(f"http://127.0.0.1:{prom_port}/-/ready", prom)
        stop(mongo)
        print(
            "Dependencies stopped; generating readiness 503 traffic for actual 2-minute alert rules.",
            flush=True,
        )
        deadline = time.monotonic() + a.seconds

        def load():
            with httpx.Client(timeout=10) as client:
                while time.monotonic() < deadline:
                    client.get(f"http://127.0.0.1:{pay_port}/health/ready")
                    time.sleep(0.1)

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(load) for _ in range(5)]
            while time.monotonic() < deadline:
                time.sleep(min(15, max(0, deadline - time.monotonic())))
                alerts = httpx.get(
                    f"http://127.0.0.1:{prom_port}/api/v1/alerts"
                ).json()["data"]["alerts"]
                firing = {
                    x["labels"]["alertname"] for x in alerts if x["state"] == "firing"
                }
                print("Firing:", sorted(firing), flush=True)
                if {"HighErrorRate", "SlowResponses"} <= firing:
                    received = httpx.get(
                        f"http://127.0.0.1:{am_port}/api/v2/alerts"
                    ).json()
                    if {"HighErrorRate", "SlowResponses"} <= {
                        x["labels"]["alertname"] for x in received
                    }:
                        deadline = time.monotonic()
                        (work / "evidence.json").write_text(
                            json.dumps(
                                {"prometheus": alerts, "alertmanager": received},
                                indent=2,
                            )
                        )
                        print(
                            "PASS: both alerts fired and reached Alertmanager.",
                            flush=True,
                        )
                        break
            for f in futures:
                f.result()
        assert (work / "evidence.json").exists(), (
            "Alerts did not fire and arrive within deadline"
        )
    finally:
        for p in reversed(processes):
            stop(p)
        for log in logs:
            log.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--mongo-bin", required=True)
    p.add_argument("--prometheus-bin", required=True)
    p.add_argument("--alertmanager-bin", required=True)
    p.add_argument("--seconds", type=int, default=300)
    main(p.parse_args())
