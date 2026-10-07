import json
import logging
import time
import os
import secrets
from pathlib import Path
from typing import Literal
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import JSONResponse, Response
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
    CONTENT_TYPE_LATEST,
)
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("payments_demo")
logging.basicConfig(level=logging.INFO, format="%(message)s")


class PaymentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_id: str = Field(min_length=1, max_length=128)
    amount: int = Field(strict=True, gt=0, le=100_000_000)
    currency: Literal["USD", "EUR", "GBP", "INR"]
    outcome: Literal["success", "failure"] = "success"


class OrderInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: int = Field(strict=True, gt=0, le=100_000_000)
    currency: Literal["USD", "EUR", "GBP", "INR"]
    outcome: Literal["success", "failure"] = "success"


class OrderOutput(BaseModel):
    id: str
    amount: int
    currency: Literal["USD", "EUR", "GBP", "INR"]
    status: Literal["pending", "paid", "failed"]
    transaction_id: str | None = None


class PaymentOutput(BaseModel):
    transaction_id: str
    status: Literal["paid", "failed"]
    payload: PaymentInput


def setting(name: str, default: str = "") -> str:
    """Read one environment value or mounted file; never log secret contents."""
    filename = os.getenv(name + "_FILE")
    value = os.getenv(name)
    if filename and value:
        raise ValueError(f"Set only {name} or {name}_FILE")
    if filename:
        value = Path(filename).read_text(encoding="utf-8").strip()
        if not value:
            raise ValueError(f"{name}_FILE must not be empty")
    return value or default


def configure_auth(app: FastAPI, token: str | None = None):
    token = setting("API_TOKEN") if token is None else token
    required = os.getenv("API_AUTH_REQUIRED", "false").lower() == "true"
    if required and not token:
        raise ValueError("API_AUTH_REQUIRED requires API_TOKEN or API_TOKEN_FILE")
    if token and len(token) < 32:
        raise ValueError("API_TOKEN must contain at least 32 characters")
    app.state.api_token = token


bearer = HTTPBearer(auto_error=False, description="API token for this service")


async def require_api_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
):
    token = request.app.state.api_token
    if token and (
        credentials is None
        or not secrets.compare_digest(credentials.credentials.encode(), token.encode())
    ):
        raise HTTPException(
            401, "Valid bearer token required", headers={"WWW-Authenticate": "Bearer"}
        )


def instrument(app: FastAPI, service: str):
    registry = CollectorRegistry()
    count = Counter(
        "http_requests_total",
        "Requests",
        ["service", "method", "route", "status"],
        registry=registry,
    )
    latency = Histogram(
        "http_request_duration_seconds",
        "Latency",
        ["service", "method", "route"],
        buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
        registry=registry,
    )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        return JSONResponse(
            {"error": {"code": str(exc.status_code), "message": str(exc.detail)}},
            status_code=exc.status_code,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse(
            {
                "error": {
                    "code": "validation_error",
                    "message": "Invalid request",
                    "details": json.loads(json.dumps(exc.errors(), default=str)),
                }
            },
            status_code=422,
        )

    @app.middleware("http")
    async def observe(request: Request, call_next):
        start = time.monotonic()
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.error(
                json.dumps(
                    {
                        "event": "unhandled_error",
                        "service": service,
                        "error_type": type(exc).__name__,
                    }
                )
            )
            response = JSONResponse(
                {
                    "error": {
                        "code": "internal_error",
                        "message": "Internal server error",
                    }
                },
                status_code=500,
            )
        route = getattr(request.scope.get("route"), "path", "unmatched")
        if route != "/metrics":
            duration = time.monotonic() - start
            count.labels(
                service, request.method, route, str(response.status_code)
            ).inc()
            latency.labels(service, request.method, route).observe(duration)
            logger.info(
                json.dumps(
                    {
                        "event": "request",
                        "service": service,
                        "method": request.method,
                        "route": route,
                        "status": response.status_code,
                        "duration_seconds": duration,
                    }
                )
            )
        return response

    @app.get("/metrics", include_in_schema=False)
    async def metrics():
        return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

    @app.get("/health/live")
    async def live():
        return {"status": "alive"}
