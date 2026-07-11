from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.infrastructure.errors import ApplicationError
from app.main import create_app


def test_application_error_uses_stable_error_contract() -> None:
    app = create_app()
    test_router = APIRouter()

    @test_router.get("/test-error")
    async def raise_application_error() -> None:
        raise ApplicationError(
            "KNOWLEDGE_BASE_NOT_FOUND",
            "Knowledge base not found",
            status_code=404,
        )

    app.include_router(test_router)
    response = TestClient(app).get("/test-error", headers={"X-Request-ID": "error-test"})

    assert response.status_code == 404
    assert response.json() == {
        "code": "KNOWLEDGE_BASE_NOT_FOUND",
        "message": "Knowledge base not found",
        "requestId": "error-test",
        "details": None,
    }
