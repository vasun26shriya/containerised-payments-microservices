import httpx
from services.payments import create_app


async def test_live_validation_metrics_and_unknown_routes_without_database():
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        assert (await c.get("/health/live")).json() == {"status": "alive"}
        bad = await c.post("/payments", json={"amount": 0})
        assert bad.status_code == 422
        assert bad.json()["error"]["code"] == "validation_error"
        await c.get("/unknown-a")
        await c.get("/unknown-b")
        metrics = (await c.get("/metrics")).text
        assert 'route="unmatched"' in metrics
        assert "unknown-a" not in metrics
        assert "http_requests_total" in metrics
        assert "http_request_duration_seconds_bucket" in metrics
