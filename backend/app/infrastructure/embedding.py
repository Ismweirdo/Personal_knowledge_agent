from dataclasses import dataclass

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, RateLimitError

from app.infrastructure.config import Settings
from app.infrastructure.errors import ApplicationError


@dataclass(frozen=True)
class EmbeddingClient:
    client: AsyncOpenAI
    model: str
    dimensions: int

    @classmethod
    def from_settings(cls, settings: Settings) -> "EmbeddingClient":
        api_key = settings.embedding_api_key
        if not api_key or not settings.embedding_model:
            raise ApplicationError(
                "EMBEDDING_NOT_CONFIGURED",
                "Embedding provider is not configured",
                status_code=503,
            )
        return cls(
            client=AsyncOpenAI(api_key=api_key, base_url=settings.embedding_base_url, timeout=30.0),
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            response = await self.client.embeddings.create(
                model=self.model,
                input=texts,
                dimensions=self.dimensions,
            )
        except RateLimitError as exc:
            raise ApplicationError(
                "EMBEDDING_RATE_LIMITED", "Embedding provider rate limit exceeded", status_code=429
            ) from exc
        except (APIConnectionError, APITimeoutError) as exc:
            raise ApplicationError(
                "EMBEDDING_UNAVAILABLE",
                "Embedding provider is temporarily unavailable",
                status_code=503,
            ) from exc
        ordered = sorted(response.data, key=lambda item: item.index)
        return [item.embedding for item in ordered]


def get_embedding_client() -> EmbeddingClient:
    from app.infrastructure.config import get_settings

    return EmbeddingClient.from_settings(get_settings())
