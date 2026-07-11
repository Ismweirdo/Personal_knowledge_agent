import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.infrastructure.health import HealthService
from app.infrastructure.observability import RateLimitMiddleware
from app.main import app


class FailingProbe:
    async def ping(self) -> bool:
        raise ConnectionError("dependency unavailable")


@pytest.mark.asyncio
async def test_health_service_reports_probe_failure_without_leaking_exception() -> None:
    checks = await HealthService(probes={"database": FailingProbe()}).check_dependencies()
    assert checks == {"database": "down"}


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/api/v1/auth/login", ("login", 10)),
        ("/api/v1/knowledge-bases/id/documents", ("ingestion", 10)),
        ("/api/v1/conversations/id/messages:stream", ("chat", 30)),
        ("/health", None),
    ],
)
def test_rate_limit_policy(path: str, expected: tuple[str, int] | None) -> None:
    request = Request({"type": "http", "method": "POST", "path": path, "headers": []})
    assert RateLimitMiddleware._policy(request) == expected


def test_metrics_endpoint_exposes_prometheus_format() -> None:
    response = TestClient(app).get("/metrics")
    assert response.status_code == 200
    assert "http_requests_total" in response.text
    assert response.headers["content-type"].startswith("text/plain")
