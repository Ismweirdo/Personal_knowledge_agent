from io import BytesIO

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.datastructures import Headers, UploadFile

from app.infrastructure.config import Settings
from app.infrastructure.models import (
    Base,
    DocumentChunk,
    IngestionTask,
    KnowledgeBase,
    KnowledgeEntity,
    KnowledgeSource,
    SourceVersion,
    User,
)
from app.ingestion.service import FileIngestionService
from app.ingestion.tasks import IngestionWorker


class FakeEmbedding:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        vector = [0.0] * 1536
        vector[0] = 1.0
        return [vector.copy() for _ in texts]


class FakeChat:
    model = "fake-deepseek"

    async def complete(self, messages, **kwargs) -> str:
        return (
            '{"entities":[{"name":"FastAPI","entity_type":"TECHNOLOGY",'
            '"confidence":0.95}],"relations":[]}'
        )


@pytest.mark.asyncio
async def test_upload_task_runs_embedding_and_graph_pipeline(tmp_path) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    settings = Settings(file_storage_path=str(tmp_path / "uploads"), _env_file=None)
    async with factory() as session:
        admin = User(email="worker@example.com", password_hash="unused", role="ADMIN")
        session.add(admin)
        await session.flush()
        kb = KnowledgeBase(user_id=admin.id, name="Worker")
        session.add(kb)
        await session.commit()
        upload = UploadFile(
            BytesIO(b"FastAPI powers the personal knowledge agent."),
            filename="notes.md",
            headers=Headers({"content-type": "text/markdown"}),
        )
        response = await FileIngestionService(session, settings).upload(admin.id, kb.id, upload)
        assert response.task_id is not None
        assert response.status == "PARSED"

    worker = IngestionWorker(
        settings,
        session_factory=factory,
        embedding=FakeEmbedding(),
        chat=FakeChat(),
    )
    assert await worker.run_once() is True

    async with factory() as session:
        task = await session.get(IngestionTask, response.task_id)
        source = await session.get(KnowledgeSource, response.source_id)
        version = await session.get(SourceVersion, response.version_id)
        embedded = await session.scalar(
            select(func.count(DocumentChunk.id)).where(DocumentChunk.embedding.is_not(None))
        )
        entities = await session.scalar(select(func.count(KnowledgeEntity.id)))
        assert task.status == "SUCCEEDED"
        assert task.progress == 100
        assert source.active_version_id == version.id
        assert version.status == "READY"
        assert embedded == 1
        assert entities == 1
    await engine.dispose()
