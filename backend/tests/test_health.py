from fastapi.testclient import TestClient

from app.main import app


def test_health() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"]


def test_health_preserves_caller_request_id() -> None:
    response = TestClient(app).get("/health", headers={"X-Request-ID": "test-request"})

    assert response.headers["X-Request-ID"] == "test-request"


def test_readiness() -> None:
    response = TestClient(app).get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {}}


def test_openapi_uses_versioned_business_api_prefix() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]

    assert "/api/v1" not in paths
    assert "/health" in paths
    assert "/api/v1/chunks/{chunk_id}/knowledge:extract" in paths
    assert "/api/v1/knowledge-bases/{kb_id}/knowledge-candidates" in paths
    assert "/api/v1/knowledge-candidates/{candidate_type}/{candidate_id}:{action}" in paths
