import os

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from redis.asyncio import Redis
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.infrastructure.models import (
    DocumentChunk,
    KnowledgeBase,
    KnowledgeSource,
    SourceVersion,
    User,
)
from app.retrieval.service import RetrievalService

pytestmark = pytest.mark.integration
DATABASE_URL = os.getenv("TEST_DATABASE_URL")
REDIS_URL = os.getenv("TEST_REDIS_URL")
ALEMBIC_HEAD = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()


class FakeEmbedding:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        vector = [0.0] * 1536
        vector[0] = 1.0
        return [vector.copy() for _ in texts]


@pytest.mark.skipif(not DATABASE_URL or not REDIS_URL, reason="real dependencies not configured")
@pytest.mark.asyncio
async def test_pgvector_migrations_retrieval_and_redis() -> None:
    engine = create_async_engine(DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        extension = await session.scalar(
            text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        )
        migration = await session.scalar(text("SELECT version_num FROM alembic_version"))
        assert extension == "vector"
        assert migration == ALEMBIC_HEAD

        admin = User(email="integration@example.com", password_hash="unused", role="ADMIN")
        session.add(admin)
        await session.flush()
        kb = KnowledgeBase(user_id=admin.id, name="Integration", is_published=True)
        session.add(kb)
        await session.flush()
        source = KnowledgeSource(
            user_id=admin.id,
            kb_id=kb.id,
            source_type="FILE",
            display_name="integration.md",
            status="READY",
        )
        session.add(source)
        await session.flush()
        version = SourceVersion(
            source_id=source.id,
            user_id=admin.id,
            kb_id=kb.id,
            content_hash="f" * 64,
            storage_key="integration",
            mime_type="text/markdown",
            size_bytes=10,
            status="READY",
        )
        session.add(version)
        await session.flush()
        source.active_version_id = version.id
        near = [0.0] * 1536
        near[0] = 1.0
        far = [0.0] * 1536
        far[1] = 1.0
        session.add_all(
            [
                DocumentChunk(
                    source_version_id=version.id,
                    user_id=admin.id,
                    kb_id=kb.id,
                    content="relevant",
                    chunk_index=0,
                    token_count=1,
                    embedding=near,
                ),
                DocumentChunk(
                    source_version_id=version.id,
                    user_id=admin.id,
                    kb_id=kb.id,
                    content="unrelated",
                    chunk_index=1,
                    token_count=1,
                    embedding=far,
                ),
            ]
        )
        await session.commit()
        results = await RetrievalService(session, FakeEmbedding()).search(
            admin.id, kb.id, "query", limit=2
        )
        assert [result.content for result in results] == ["relevant", "unrelated"]
        assert results[0].score > results[1].score
        assert await session.scalar(select(func.count(DocumentChunk.id))) >= 2
    await engine.dispose()

    redis = Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        await redis.delete("integration:counter")
        assert await redis.incr("integration:counter") == 1
        assert await redis.incr("integration:counter") == 2
    finally:
        await redis.delete("integration:counter")
        await redis.aclose()
