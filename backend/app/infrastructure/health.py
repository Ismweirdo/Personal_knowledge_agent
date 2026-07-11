from dataclasses import dataclass
from typing import Protocol

from redis.asyncio import Redis
from sqlalchemy import text

from app.infrastructure.config import get_settings
from app.infrastructure.database import engine


class DependencyProbe(Protocol):
    async def ping(self) -> bool: ...


@dataclass
class HealthService:
    probes: dict[str, DependencyProbe] | None = None

    async def check_dependencies(self) -> dict[str, str]:
        if not self.probes:
            return {}

        checks: dict[str, str] = {}
        for name, probe in self.probes.items():
            try:
                checks[name] = "up" if await probe.ping() else "down"
            except Exception:
                checks[name] = "down"
        return checks


class DatabaseProbe:
    async def ping(self) -> bool:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True


class RedisProbe:
    async def ping(self) -> bool:
        settings = get_settings()
        redis = Redis(host=settings.redis_host, password=settings.redis_password)
        try:
            return bool(await redis.ping())
        finally:
            await redis.aclose()


def get_health_service() -> HealthService:
    if get_settings().app_env.lower() != "production":
        return HealthService()
    return HealthService(probes={"database": DatabaseProbe(), "redis": RedisProbe()})
