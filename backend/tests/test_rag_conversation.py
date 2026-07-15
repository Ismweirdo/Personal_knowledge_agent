from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.conversation.service import NO_EVIDENCE_ANSWER, RagConversationService
from app.infrastructure.models import Base, Conversation, KnowledgeBase, Message, User
from app.retrieval.service import RetrievalResult


class FakeRetrieval:
    async def search(self, user_id: str, kb_id: str, query: str, *, limit: int):
        return [
            RetrievalResult(
                chunk_id="evidence-chunk",
                content="Verified project evidence",
                score=0.9,
                metadata={"source_name": "Resume"},
            )
        ]


class EmptyRetrieval:
    async def search(self, user_id: str, kb_id: str, query: str, *, limit: int):
        return []


class FakeChat:
    model = "fake-chat"

    async def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        yield "hello "
        yield "world"


class FailingChat:
    model = "failing-chat"

    async def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        yield "partial"
        raise RuntimeError("upstream disconnected")


class UnexpectedChat:
    model = "unexpected-chat"

    async def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        raise AssertionError("chat model must not be called without evidence")
        yield "unreachable"


class InternalPreambleChat:
    model = "preamble-chat"

    async def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        assert "Context:" not in messages[-1]["content"]
        yield "根据"
        yield " Context，"
        yield "雷明康做过两个项目。"


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as value:
        yield value
    await engine.dispose()


async def seed_conversation(session) -> tuple[str, str]:
    admin = User(email="admin@example.com", password_hash="unused", role="ADMIN")
    visitor = User(email="rag@example.com", password_hash="unused", role="USER")
    session.add_all([admin, visitor])
    await session.flush()
    kb = KnowledgeBase(user_id=admin.id, name="RAG", is_published=True)
    session.add(kb)
    await session.flush()
    conversation = Conversation(user_id=visitor.id, kb_id=kb.id, title="Test")
    session.add(conversation)
    await session.commit()
    return visitor.id, conversation.id


@pytest.mark.asyncio
async def test_successful_stream_persists_completed_answer(session) -> None:
    user_id, conversation_id = await seed_conversation(session)
    service = RagConversationService(session, FakeRetrieval(), FakeChat())

    events = [event async for event in service.stream(user_id, conversation_id, "question")]
    assistant = await session.scalar(
        select(Message).where(
            Message.conversation_id == conversation_id, Message.role == "assistant"
        )
    )

    assert [event.splitlines()[0] for event in events] == [
        "event: metadata",
        "event: citation",
        "event: delta",
        "event: delta",
        "event: done",
    ]
    assert assistant is not None
    assert assistant.status == "COMPLETED"
    assert assistant.content == "hello world"


@pytest.mark.asyncio
async def test_failed_stream_persists_partial_answer_and_failed_status(session) -> None:
    user_id, conversation_id = await seed_conversation(session)
    service = RagConversationService(session, FakeRetrieval(), FailingChat())

    events = [event async for event in service.stream(user_id, conversation_id, "question")]
    assistant = await session.scalar(
        select(Message).where(
            Message.conversation_id == conversation_id, Message.role == "assistant"
        )
    )

    assert events[-1].startswith("event: error")
    assert "upstream disconnected" not in events[-1]
    assert assistant is not None
    assert assistant.status == "FAILED"
    assert assistant.content == "partial"


@pytest.mark.asyncio
async def test_empty_retrieval_returns_deterministic_answer_without_model(session) -> None:
    user_id, conversation_id = await seed_conversation(session)
    service = RagConversationService(session, EmptyRetrieval(), UnexpectedChat())

    events = [event async for event in service.stream(user_id, conversation_id, "unknown")]
    assistant = await session.scalar(
        select(Message).where(
            Message.conversation_id == conversation_id, Message.role == "assistant"
        )
    )

    assert [event.splitlines()[0] for event in events] == [
        "event: metadata",
        "event: citation",
        "event: delta",
        "event: done",
    ]
    assert NO_EVIDENCE_ANSWER in events[2]
    assert assistant is not None
    assert assistant.status == "COMPLETED"
    assert assistant.content == NO_EVIDENCE_ANSWER


@pytest.mark.asyncio
async def test_stream_removes_internal_retrieval_preamble(session) -> None:
    user_id, conversation_id = await seed_conversation(session)
    service = RagConversationService(session, FakeRetrieval(), InternalPreambleChat())

    events = [event async for event in service.stream(user_id, conversation_id, "做过哪些项目？")]
    assistant = await session.scalar(
        select(Message).where(
            Message.conversation_id == conversation_id, Message.role == "assistant"
        )
    )

    deltas = [event for event in events if event.startswith("event: delta")]
    assert len(deltas) == 1
    assert "Context" not in deltas[0]
    assert assistant is not None
    assert assistant.content == "雷明康做过两个项目。"
