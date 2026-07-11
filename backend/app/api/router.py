from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.auth import router as auth_router
from app.infrastructure.health import HealthService, get_health_service
from app.knowledge_base.router import router as knowledge_base_router

router = APIRouter(prefix="/api/v1")
router.include_router(auth_router)
router.include_router(knowledge_base_router)
operations_router = APIRouter(tags=["operations"])


@operations_router.get("/health")
@operations_router.get("/health/live", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok"}


@operations_router.get("/health/ready")
async def readiness(
    health_service: Annotated[HealthService, Depends(get_health_service)],
) -> dict[str, object]:
    checks = await health_service.check_dependencies()
    return {"status": "ready", "checks": checks}


api_router = APIRouter()
api_router.include_router(operations_router)
api_router.include_router(router)
