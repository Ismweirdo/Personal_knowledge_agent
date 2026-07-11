import hashlib
import json
import logging
from time import monotonic

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from redis.asyncio import Redis
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.infrastructure.config import get_settings

logger = logging.getLogger("personal_agent.requests")
REQUESTS = Counter("http_requests_total", "HTTP requests", ["method", "path", "status"])
LATENCY = Histogram("http_request_duration_seconds", "HTTP request latency", ["method", "path"])


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "event": record.getMessage(),
            "requestId": getattr(record, "request_id", None),
            "method": getattr(record, "method", None),
            "path": getattr(record, "path", None),
            "status": getattr(record, "status", None),
            "durationMs": getattr(record, "duration_ms", None),
        }
        return json.dumps({key: value for key, value in payload.items() if value is not None})


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        started = monotonic()
        response = await call_next(request)
        path = request.scope.get("route").path if request.scope.get("route") else request.url.path
        elapsed = monotonic() - started
        REQUESTS.labels(request.method, path, str(response.status_code)).inc()
        LATENCY.labels(request.method, path).observe(elapsed)
        logger.info(
            "request_completed",
            extra={
                "request_id": getattr(request.state, "request_id", None),
                "method": request.method,
                "path": path,
                "status": response.status_code,
                "duration_ms": round(elapsed * 1000, 2),
            },
        )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        settings = get_settings()
        policy = self._policy(request)
        if not settings.rate_limit_enabled or policy is None:
            return await call_next(request)
        category, limit = policy
        identity = request.client.host if request.client else "unknown"
        authorization = request.headers.get("authorization")
        if authorization:
            identity = hashlib.sha256(authorization.encode()).hexdigest()[:24]
        redis = Redis(
            host=settings.redis_host, password=settings.redis_password, decode_responses=True
        )
        try:
            key = f"rate:{category}:{identity}"
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, 60)
            if count > limit:
                return JSONResponse(
                    status_code=429,
                    content={
                        "code": "RATE_LIMITED",
                        "message": "Too many requests",
                        "requestId": getattr(request.state, "request_id", None),
                        "details": None,
                    },
                    headers={"Retry-After": "60"},
                )
        finally:
            await redis.aclose()
        return await call_next(request)

    @staticmethod
    def _policy(request: Request) -> tuple[str, int] | None:
        path = request.url.path
        if path.endswith("/auth/login"):
            return "login", 10
        if "/documents" in path or "sources:" in path:
            return "ingestion", 10
        if path.endswith("messages:stream"):
            return "chat", 30
        return None


def metrics_response() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
