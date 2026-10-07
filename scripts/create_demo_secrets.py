"""Create disposable local credentials without printing or replacing existing secrets."""

import argparse
import os
from pathlib import Path
import secrets


def main(directory: Path):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    names = (
        "mongo-root-password",
        "orders-db-password",
        "payments-db-password",
        "orders-api-token",
        "payments-api-token",
        "grafana-password",
    )
    for name in names:
        path = directory / name
        if not path.exists():
            with path.open("x", encoding="utf-8") as stream:
                stream.write(secrets.token_hex(32))
            # Private parent directory protects files on the host. Compose bind-mounted
            # secrets must be readable by the nonroot API process inside containers.
            os.chmod(path, 0o644)
    for service in ("orders", "payments"):
        path = directory / (service + "-mongo-uri")
        if not path.exists():
            password = (directory / (service + "-db-password")).read_text().strip()
            with path.open("x", encoding="utf-8") as stream:
                stream.write(
                    f"mongodb://{service}:{password}@mongo:27017/{service}?authSource={service}"
                )
            os.chmod(path, 0o644)
    print(f"Local demo credentials ready in {directory}; values were not printed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, default=Path(".run/secure/secrets"))
    main(parser.parse_args().directory)
