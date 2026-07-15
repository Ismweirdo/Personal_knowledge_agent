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

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, messages, **kwargs) -> str:
        self.calls += 1
        return (
            '{"entities":[{"name":"FastAPI","entity_type":"TECHNOLOGY",'
            '"confidence":0.95}],"relations":[]}'
        )


class InvalidGraphChat:
    model = "fake-deepseek"

    async def complete(self, messages, **kwargs) -> str:
        return "not json"


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


@pytest.mark.asyncio
async def test_graph_extraction_failure_does_not_block_indexing(tmp_path) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    settings = Settings(file_storage_path=str(tmp_path / "uploads"), _env_file=None)
    async with factory() as session:
        admin = User(email="graph-warning@example.com", password_hash="unused", role="ADMIN")
        session.add(admin)
        await session.flush()
        kb = KnowledgeBase(user_id=admin.id, name="Graph warning")
        session.add(kb)
        await session.commit()
        upload = UploadFile(
            BytesIO(b"FastAPI powers the personal knowledge agent."),
            filename="notes.md",
            headers=Headers({"content-type": "text/markdown"}),
        )
        response = await FileIngestionService(session, settings).upload(admin.id, kb.id, upload)

    worker = IngestionWorker(
        settings,
        session_factory=factory,
        embedding=FakeEmbedding(),
        chat=InvalidGraphChat(),
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
        assert task.error_code == "GRAPH_EXTRACTION_INVALID"
        assert source.active_version_id == version.id
        assert version.status == "READY"
        assert embedded == 1
        assert entities == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_graph_extraction_is_limited_per_task(tmp_path) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    settings = Settings(
        file_storage_path=str(tmp_path / "uploads"),
        graph_extraction_max_chunks_per_task=1,
        _env_file=None,
    )
    chat = FakeChat()
    async with factory() as session:
        admin = User(email="graph-limit@example.com", password_hash="unused", role="ADMIN")
        session.add(admin)
        await session.flush()
        kb = KnowledgeBase(user_id=admin.id, name="Graph limit")
        session.add(kb)
        await session.flush()
        source = KnowledgeSource(
            user_id=admin.id,
            kb_id=kb.id,
            source_type="GIT",
            display_name="repo",
            status="PARSED",
        )
        session.add(source)
        await session.flush()
        version = SourceVersion(
            source_id=source.id,
            user_id=admin.id,
            kb_id=kb.id,
            content_hash="hash",
            storage_key="repo.txt",
            mime_type="text/plain",
            size_bytes=10,
            status="PARSED",
        )
        session.add(version)
        await session.flush()
        session.add_all(
            DocumentChunk(
                source_version_id=version.id,
                user_id=admin.id,
                kb_id=kb.id,
                content=f"FastAPI chunk {index}",
                chunk_index=index,
                token_count=4,
                chunk_metadata={},
            )
            for index in range(3)
        )
        task = IngestionTask(
            user_id=admin.id,
            source_id=source.id,
            source_version_id=version.id,
        )
        session.add(task)
        await session.commit()
        task_id = task.id

    worker = IngestionWorker(
        settings,
        session_factory=factory,
        embedding=FakeEmbedding(),
        chat=chat,
    )
    assert await worker.run_once() is True

    async with factory() as session:
        task = await session.get(IngestionTask, task_id)
        assert task.status == "SUCCEEDED"
        assert task.progress == 100
        assert task.error_code == "GRAPH_EXTRACTION_PARTIAL"
        assert chat.calls == 1
    await engine.dispose()
