from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.infrastructure.config import Settings
from app.infrastructure.embedding import EmbeddingClient
from app.infrastructure.errors import ApplicationError


def test_embedding_client_requires_separate_configuration() -> None:
    settings = Settings(embedding_api_key=None, embedding_model=None, _env_file=None)

    with pytest.raises(ApplicationError) as exc_info:
        EmbeddingClient.from_settings(settings)

    assert exc_info.value.code == "EMBEDDING_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_embedding_response_is_ordered_by_index() -> None:
    create = AsyncMock(
        return_value=SimpleNamespace(
            data=[
                SimpleNamespace(index=1, embedding=[0.0, 1.0]),
                SimpleNamespace(index=0, embedding=[1.0, 0.0]),
            ]
        )
    )
    sdk = SimpleNamespace(embeddings=SimpleNamespace(create=create))
    client = EmbeddingClient(client=sdk, model="test-embedding", dimensions=2)

    result = await client.embed(["first", "second"])

    assert result == [[1.0, 0.0], [0.0, 1.0]]
    create.assert_awaited_once_with(model="test-embedding", input=["first", "second"], dimensions=2)
