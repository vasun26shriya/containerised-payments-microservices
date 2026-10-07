"""Back up the authenticated local demo and verify restores in isolated databases."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import uuid


def run(arguments):
    return subprocess.run(arguments, check=True, capture_output=True, text=True).stdout


def main(args):
    compose = [
        "docker",
        "compose",
        "-p",
        args.project,
        "-f",
        "compose.yaml",
        "-f",
        "compose.secure.yaml",
    ]
    container = run(compose + ["ps", "-q", "mongo"]).strip()
    if not container:
        raise RuntimeError("Start the secured Compose demo first")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = Path(args.output) / (stamp + "-" + uuid.uuid4().hex[:8])
    directory.mkdir(parents=True, mode=0o700)
    evidence = {"executed_at": stamp, "databases": {}}
    for database, collection in (("orders", "orders"), ("payments", "transactions")):
        suffix = uuid.uuid4().hex
        remote = f"/tmp/{suffix}.archive.gz"
        config = f"/tmp/{suffix}.yaml"
        restored = "restore_drill_" + suffix
        local = directory / (database + ".archive.gz")
        # Password stays in a short-lived private config inside the container,
        # never in Python arguments, reports, or host command output.
        config_command = (
            'umask 077; printf \'password: "%s"\\n\' "$(cat /run/secrets/mongo-root-password)" > '
            + config
        )
        run(["docker", "exec", container, "sh", "-c", config_command])
        auth = [
            "--host",
            "127.0.0.1",
            "--username",
            "admin",
            "--authenticationDatabase",
            "admin",
            "--config",
            config,
        ]
        try:
            run(
                [
                    "docker",
                    "exec",
                    container,
                    "mongodump",
                    *auth,
                    "--db",
                    database,
                    "--gzip",
                    "--archive=" + remote,
                ]
            )
            run(["docker", "cp", container + ":" + remote, str(local)])
            run(
                [
                    "docker",
                    "exec",
                    container,
                    "mongorestore",
                    *auth,
                    "--gzip",
                    "--archive=" + remote,
                    "--nsFrom",
                    database + ".*",
                    "--nsTo",
                    restored + ".*",
                ]
            )
            javascript = (
                "db.getSiblingDB('admin').auth('admin',require('fs').readFileSync('/run/secrets/mongo-root-password','utf8').trim());"
                f"const source=db.getSiblingDB('{database}').getCollection('{collection}');"
                f"const target=db.getSiblingDB('{restored}').getCollection('{collection}');"
                "print(JSON.stringify({source:source.countDocuments({}),restored:target.countDocuments({}),"
                "documents_equal:JSON.stringify(source.find().sort({_id:1}).toArray())===JSON.stringify(target.find().sort({_id:1}).toArray()),"
                "indexes_equal:JSON.stringify(source.getIndexes())===JSON.stringify(target.getIndexes())}));"
            )
            result = json.loads(
                run(
                    [
                        "docker",
                        "exec",
                        container,
                        "mongosh",
                        "--quiet",
                        "--eval",
                        javascript,
                    ]
                )
                .strip()
                .splitlines()[-1]
            )
            if not (
                result["source"] > 0
                and result["documents_equal"]
                and result["indexes_equal"]
            ):
                raise AssertionError(
                    f"Restore verification failed for {database}: {result}"
                )
            evidence["databases"][database] = result
        finally:
            cleanup = (
                "db.getSiblingDB('admin').auth('admin',require('fs').readFileSync('/run/secrets/mongo-root-password','utf8').trim());"
                f"db.getSiblingDB('{restored}').dropDatabase();"
            )
            run(["docker", "exec", container, "mongosh", "--quiet", "--eval", cleanup])
            run(["docker", "exec", container, "rm", "-f", remote, config])
    Path(args.evidence).parent.mkdir(parents=True, exist_ok=True)
    Path(args.evidence).write_text(json.dumps(evidence, indent=2) + "\n")
    print(f"PASS: backup and isolated restore of both databases; archives: {directory}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="payments-secure")
    parser.add_argument("--output", default=".run/backups")
    parser.add_argument("--evidence", default=".run/backup-restore.json")
    main(parser.parse_args())
