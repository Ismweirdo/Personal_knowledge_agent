from dataclasses import dataclass

import httpx
from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, RateLimitError

from app.infrastructure.config import Settings
from app.infrastructure.errors import ApplicationError


@dataclass(frozen=True)
class EmbeddingClient:
    client: AsyncOpenAI | httpx.AsyncClient
    model: str
    dimensions: int
    provider: str = "openai"
    batch_size: int = 32

    @classmethod
    def from_settings(cls, settings: Settings) -> "EmbeddingClient":
        if settings.embedding_provider == "ollama":
            if not settings.embedding_model:
                raise ApplicationError(
                    "EMBEDDING_NOT_CONFIGURED",
                    "Embedding provider is not configured",
                    status_code=503,
                )
            return cls(
                client=httpx.AsyncClient(
                    base_url=settings.embedding_base_url or "http://localhost:11434", timeout=300.0
                ),
                model=settings.embedding_model,
                dimensions=settings.embedding_dimensions,
                provider="ollama",
                batch_size=4,
            )
        api_key = settings.embedding_api_key
        if not api_key or not settings.embedding_model:
            raise ApplicationError(
                "EMBEDDING_NOT_CONFIGURED",
                "Embedding provider is not configured",
                status_code=503,
            )
        return cls(
            client=AsyncOpenAI(
                api_key=api_key,
                base_url=settings.embedding_base_url,
                timeout=settings.embedding_request_timeout_seconds,
            ),
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            batch_size=settings.embedding_batch_size,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self.provider == "ollama":
            return await self._embed_ollama(texts)
        return await self._embed_openai(texts)

    async def _embed_openai(self, texts: list[str]) -> list[list[float]]:
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
        return self._validate_vectors([item.embedding for item in ordered], len(texts))

    async def _embed_ollama(self, texts: list[str]) -> list[list[float]]:
        assert isinstance(self.client, httpx.AsyncClient)
        try:
            response = await self.client.post(
                "/api/embed", json={"model": self.model, "input": texts, "truncate": False}
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ApplicationError(
                "EMBEDDING_UNAVAILABLE",
                "Local embedding service returned an error",
                status_code=503,
            ) from exc
        except httpx.HTTPError as exc:
            raise ApplicationError(
                "EMBEDDING_UNAVAILABLE", "Local embedding service is unavailable", status_code=503
            ) from exc
        embeddings = response.json().get("embeddings")
        if not isinstance(embeddings, list):
            raise ApplicationError(
                "EMBEDDING_INVALID_RESPONSE",
                "Local embedding service returned an invalid response",
                status_code=502,
            )
        return self._validate_vectors(embeddings, len(texts))

    def _validate_vectors(
        self, vectors: list[list[float]], expected_count: int
    ) -> list[list[float]]:
        if len(vectors) != expected_count:
            raise ApplicationError(
                "EMBEDDING_COUNT_MISMATCH",
                "Embedding provider returned an invalid result count",
                status_code=502,
            )
        if any(
            not isinstance(vector, list) or len(vector) != self.dimensions for vector in vectors
        ):
            raise ApplicationError(
                "EMBEDDING_DIMENSION_MISMATCH",
                "Embedding provider returned an invalid vector size",
                status_code=502,
            )
        return vectors


def get_embedding_client() -> EmbeddingClient:
    from app.infrastructure.config import get_settings

    return EmbeddingClient.from_settings(get_settings())
