from dataclasses import dataclass
from typing import Protocol


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
            checks[name] = "up" if await probe.ping() else "down"
        return checks


def get_health_service() -> HealthService:
    # Concrete database and Redis probes are wired when their clients are introduced.
    return HealthService()
