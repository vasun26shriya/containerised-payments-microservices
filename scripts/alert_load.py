"""Run alongside Compose: python scripts/alert_load.py slow|errors (at least 5 minutes)."""

import asyncio
import argparse
import time
import uuid
import httpx


async def main(mode, base, seconds):
    deadline = time.monotonic() + seconds
    async with httpx.AsyncClient(timeout=15) as client:

        async def worker():
            while time.monotonic() < deadline:
                try:
                    if mode == "slow":
                        await client.post(
                            base + "/payments",
                            json={
                                "order_id": "alert-demo",
                                "amount": 100,
                                "currency": "USD",
                            },
                            headers={"Idempotency-Key": str(uuid.uuid4())},
                        )
                    else:
                        await client.get(base + "/health/ready")
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.2)

        await asyncio.gather(*(worker() for _ in range(5)))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["slow", "errors"])
    p.add_argument("--base", default="http://localhost:8001")
    p.add_argument("--seconds", type=int, default=360)
    a = p.parse_args()
    asyncio.run(main(a.mode, a.base, a.seconds))
