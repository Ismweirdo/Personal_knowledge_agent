from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, RateLimitError
from openai.types.chat import ChatCompletionMessageParam

from app.infrastructure.config import Settings
from app.infrastructure.errors import ApplicationError


@dataclass(frozen=True)
class ChatModelClient:
    client: AsyncOpenAI
    model: str

    @classmethod
    def from_settings(cls, settings: Settings) -> "ChatModelClient":
        if not settings.llm_api_key:
            raise ApplicationError(
                "LLM_NOT_CONFIGURED",
                "LLM API key is not configured",
                status_code=503,
            )
        return cls(
            client=AsyncOpenAI(
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url,
                timeout=30.0,
                max_retries=2,
            ),
            model=settings.chat_model,
        )

    async def complete(self, messages: Sequence[ChatCompletionMessageParam]) -> str:
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=False,
            )
        except RateLimitError as exc:
            raise ApplicationError(
                "LLM_RATE_LIMITED",
                "LLM provider rate limit exceeded",
                status_code=429,
            ) from exc
        except (APIConnectionError, APITimeoutError) as exc:
            raise ApplicationError(
                "LLM_UNAVAILABLE",
                "LLM provider is temporarily unavailable",
                status_code=503,
            ) from exc

        return response.choices[0].message.content or ""

    async def stream(self, messages: Sequence[ChatCompletionMessageParam]) -> AsyncIterator[str]:
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True,
            )
            async for chunk in response:
                content = chunk.choices[0].delta.content
                if content:
                    yield content
        except RateLimitError as exc:
            raise ApplicationError(
                "LLM_RATE_LIMITED",
                "LLM provider rate limit exceeded",
                status_code=429,
            ) from exc
        except (APIConnectionError, APITimeoutError) as exc:
            raise ApplicationError(
                "LLM_UNAVAILABLE",
                "LLM provider is temporarily unavailable",
                status_code=503,
            ) from exc
