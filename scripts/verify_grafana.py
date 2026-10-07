"""Verify Grafana provisioning in an isolated native stack; keep it open for visual QA."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid
import socket
import httpx
from pymongo import MongoClient
from smoke_stack import main as smoke
from smoke_stack import eventually


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main(a):
    root = Path(a.root)
    work = root / ".run/grafana-demo"
    work.mkdir(parents=True, exist_ok=True)
    mongo_port, pay_port, order_port, prom_port, grafana_port = [
        free_port() for _ in range(5)
    ]
    processes = []
    logs = []

    def start(command, env=None):
        log = (work / f"process-{len(processes)}.log").open("w")
        logs.append(log)
        p = subprocess.Popen(command, cwd=root, env=env, stdout=log, stderr=log)
        processes.append(p)
        return p

    def ready(url):
        if any(p.poll() is not None for p in processes):
            raise RuntimeError(
                "A native stack process exited; inspect .run/grafana-demo logs"
            )
        r = httpx.get(url, timeout=3)
        r.raise_for_status()
        return r

    try:
        data = work / ("mongo-" + uuid.uuid4().hex)
        data.mkdir(exist_ok=True)
        start(
            [
                a.mongo_bin,
                "--dbpath",
                str(data),
                "--bind_ip",
                "127.0.0.1",
                "--port",
                str(mongo_port),
                "--setParameter",
                "diagnosticDataCollectionEnabled=false",
            ]
        )
        uri = f"mongodb://127.0.0.1:{mongo_port}"
        with MongoClient(uri, serverSelectionTimeoutMS=10000) as mongo:
            mongo.admin.command("ping")
        env = {
            **os.environ,
            "MONGO_URI": uri,
            "MONGO_DATABASE": "grafana_demo_payments",
        }
        start(
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
        eventually(lambda: ready(f"http://127.0.0.1:{pay_port}/health/ready"))
        env = {
            **env,
            "MONGO_DATABASE": "grafana_demo_orders",
            "PAYMENTS_URL": f"http://127.0.0.1:{pay_port}",
        }
        start(
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
        eventually(lambda: ready(f"http://127.0.0.1:{order_port}/health/ready"))
        config = {
            "global": {"scrape_interval": "5s"},
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
        start(
            [
                a.prometheus_bin,
                "--config.file=" + str(work / "prometheus.yml"),
                "--storage.tsdb.path=" + str(work / "prometheus-data"),
                "--web.listen-address=127.0.0.1:" + str(prom_port),
            ]
        )
        eventually(lambda: ready(f"http://127.0.0.1:{prom_port}/-/ready"))
        provisioning = work / "provisioning"
        shutil.copytree(
            root / "monitoring/grafana/provisioning", provisioning, dirs_exist_ok=True
        )
        datasource = provisioning / "datasources/default.yml"
        datasource.write_text(
            datasource.read_text().replace(
                "http://prometheus:9090", f"http://127.0.0.1:{prom_port}"
            )
        )
        provider = provisioning / "dashboards/default.yml"
        provider.write_text(
            provider.read_text().replace(
                "/var/lib/grafana/dashboards",
                (root / "monitoring/grafana/dashboards").as_posix(),
            )
        )
        for directory in ("grafana-data", "grafana-logs"):
            (work / directory).mkdir(exist_ok=True)
        env = {
            **os.environ,
            "GF_PATHS_DATA": str(work / "grafana-data"),
            "GF_PATHS_LOGS": str(work / "grafana-logs"),
            "GF_PATHS_PROVISIONING": str(provisioning),
            "GF_SERVER_HTTP_ADDR": "127.0.0.1",
            "GF_SERVER_HTTP_PORT": str(grafana_port),
            "GF_SECURITY_ADMIN_PASSWORD": "local-demo-change-me",
            "GF_ANALYTICS_REPORTING_ENABLED": "false",
            "GF_ANALYTICS_CHECK_FOR_UPDATES": "false",
            "GF_PLUGINS_PREINSTALL_DISABLED": "true",
        }
        start([a.grafana_bin, "server", "--homepath", a.grafana_home], env)
        eventually(lambda: ready(f"http://127.0.0.1:{grafana_port}/api/health"))
        args = argparse.Namespace(
            orders=f"http://127.0.0.1:{order_port}",
            payments=f"http://127.0.0.1:{pay_port}",
            prometheus=f"http://127.0.0.1:{prom_port}",
            grafana=f"http://127.0.0.1:{grafana_port}",
            previous=None,
            evidence=str(root / "docs/grafana-evidence.json"),
        )
        smoke(args)
        (work / "endpoints.json").write_text(json.dumps(vars(args), indent=2))
        print(
            "Grafana dashboard: " + args.grafana + "/d/payments/payments-microservices",
            flush=True,
        )
        print("Keeping native stack open for visual verification.", flush=True)
        deadline = time.monotonic() + a.keep_seconds
        with httpx.Client(timeout=10) as client:
            while time.monotonic() < deadline:
                client.post(
                    args.orders + "/orders", json={"amount": 100, "currency": "USD"}
                )
                client.get(args.orders + "/orders/demo-missing")
                time.sleep(2)
    finally:
        for p in reversed(processes):
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait(timeout=5)
        for log in logs:
            log.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True)
    p.add_argument("--mongo-bin", required=True)
    p.add_argument("--prometheus-bin", required=True)
    p.add_argument("--grafana-bin", required=True)
    p.add_argument("--grafana-home", required=True)
    p.add_argument("--keep-seconds", type=int, default=300)
    main(p.parse_args())
