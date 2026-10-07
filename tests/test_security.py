import httpx
import pytest
from services.common import setting
from services.payments import create_app


async def test_auth_rejects_missing_wrong_and_basic_before_database():
    app = create_app(auth_token="a" * 64)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for headers in (
            {},
            {"Authorization": "Bearer wrong"},
            {"Authorization": "Basic abc"},
            {"Authorization": b"Bearer \xff"},
        ):
            result = await client.post(
                "/payments",
                json={"order_id": "x", "amount": 100, "currency": "INR"},
                headers={**headers, "Idempotency-Key": "x"},
            )
            assert result.status_code == 401
            assert result.headers["www-authenticate"] == "Bearer"
            assert result.json()["error"]["code"] == "401"
        assert (await client.get("/health/live")).status_code == 200
        assert (await client.get("/metrics")).status_code == 200
        schema = (await client.get("/openapi.json")).json()
        assert schema["paths"]["/payments"]["post"]["security"]


def test_auth_fails_closed_and_secret_files(monkeypatch, tmp_path):
    monkeypatch.setenv("API_AUTH_REQUIRED", "true")
    with pytest.raises(ValueError, match="requires API_TOKEN"):
        create_app(auth_token="")
    with pytest.raises(ValueError, match="at least 32"):
        create_app(auth_token="short")
    secret = tmp_path / "token"
    secret.write_text("a" * 64 + "\n")
    monkeypatch.setenv("API_TOKEN_FILE", str(secret))
    assert create_app().state.api_token == "a" * 64
    monkeypatch.setenv("API_TOKEN", "b" * 64)
    with pytest.raises(ValueError, match="Set only"):
        setting("API_TOKEN")
