from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.infrastructure.config import get_settings
from app.infrastructure.errors import install_exception_handlers
from app.infrastructure.middleware import RequestContextMiddleware
from app.infrastructure.observability import (
    ObservabilityMiddleware,
    RateLimitMiddleware,
    configure_logging,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    get_settings()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(ObservabilityMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.include_router(api_router)
    install_exception_handlers(app)

    return app


app = create_app()
