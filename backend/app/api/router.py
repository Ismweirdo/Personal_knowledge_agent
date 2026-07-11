from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse

from app.api.auth import router as auth_router
from app.conversation.router import router as conversation_router
from app.infrastructure.health import HealthService, get_health_service
from app.infrastructure.observability import metrics_response
from app.ingestion.router import router as ingestion_router
from app.ingestion.task_router import router as task_router
from app.knowledge_base.public_router import router as public_agent_router
from app.knowledge_base.router import router as knowledge_base_router
from app.knowledge_graph.router import router as knowledge_graph_router
from app.learning.router import router as learning_router

router = APIRouter(prefix="/api/v1")
router.include_router(auth_router)
router.include_router(knowledge_base_router)
router.include_router(public_agent_router)
router.include_router(ingestion_router)
router.include_router(task_router)
router.include_router(conversation_router)
router.include_router(knowledge_graph_router)
router.include_router(learning_router)
operations_router = APIRouter(tags=["operations"])


@operations_router.get("/health")
@operations_router.get("/health/live", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok"}


@operations_router.get("/health/ready")
async def readiness(
    health_service: Annotated[HealthService, Depends(get_health_service)],
) -> Response:
    checks = await health_service.check_dependencies()
    if any(value != "up" for value in checks.values()):
        return JSONResponse(
            content={"status": "not_ready", "checks": checks},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return JSONResponse(content={"status": "ready", "checks": checks})


@operations_router.get("/metrics", include_in_schema=False)
async def metrics():
    return metrics_response()


api_router = APIRouter()
api_router.include_router(operations_router)
api_router.include_router(router)
