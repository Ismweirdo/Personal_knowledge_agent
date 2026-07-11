from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.infrastructure.config import Settings
from app.infrastructure.errors import ApplicationError
from app.infrastructure.llm import ChatModelClient


def test_client_requires_api_key() -> None:
    settings = Settings(llm_api_key=None, _env_file=None)

    with pytest.raises(ApplicationError, match="LLM API key is not configured") as exc_info:
        ChatModelClient.from_settings(settings)

    assert exc_info.value.code == "LLM_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_complete_uses_configured_model() -> None:
    create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="test response"))]
        )
    )
    sdk_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    client = ChatModelClient(client=sdk_client, model="deepseek-chat")
    messages = [{"role": "user", "content": "hello"}]

    result = await client.complete(messages)

    assert result == "test response"
    create.assert_awaited_once_with(model="deepseek-chat", messages=messages, stream=False)
