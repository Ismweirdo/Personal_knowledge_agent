import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.infrastructure.errors import ApplicationError
from app.infrastructure.models import (
    Base,
    DocumentChunk,
    KnowledgeBase,
    KnowledgeEntity,
    KnowledgeEvidence,
    KnowledgeRelation,
    KnowledgeRevision,
    KnowledgeSource,
    SourceVersion,
    User,
)
from app.knowledge_graph.extraction import GraphExtractionService, parse_extraction
from app.knowledge_graph.review import KnowledgeReviewService


def test_parse_structured_graph_candidates() -> None:
    result = parse_extraction(
        '{"entities":[{"name":"FastAPI","entity_type":"TECHNOLOGY","confidence":0.95}],'
        '"relations":[]}'
    )
    assert result.entities[0].name == "FastAPI"
    assert result.entities[0].confidence == 0.95


def test_parse_markdown_fenced_graph_candidates() -> None:
    result = parse_extraction('```json\n{"entities":[],"relations":[]}\n```')
    assert result.entities == []


def test_parse_deepseek_field_aliases() -> None:
    result = parse_extraction(
        '{"entities":[{"name":"FastAPI","type":"TECH","confidence":0.9}],'
        '"relations":[{"from":"FastAPI","type":"USES","to":"Python",'
        '"confidence":0.8}]}'
    )
    assert result.entities[0].entity_type == "TECH"
    assert result.relations[0].predicate == "USES"


@pytest.mark.parametrize(
    "payload",
    ["not-json", '{"entities":[{"name":"","entity_type":"TECH","confidence":2}]}'],
)
def test_invalid_graph_candidates_are_rejected(payload: str) -> None:
    with pytest.raises(ApplicationError) as exc_info:
        parse_extraction(payload)
    assert exc_info.value.code == "GRAPH_EXTRACTION_INVALID"


class FakeChat:
    model = "fake-deepseek"

    async def complete(self, messages, **kwargs) -> str:
        return (
            '{"entities":['
            '{"name":"FastAPI","entity_type":"technology","confidence":0.9},'
            '{"name":"Python","entity_type":"technology","confidence":0.9}],'
            '"relations":[{"source":"FastAPI","predicate":"USES",'
            '"target":"Python","confidence":0.8}]}'
        )


@pytest.mark.asyncio
async def test_extraction_is_idempotent_and_evidence_backed() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        user = User(email="graph@example.com", password_hash="unused")
        session.add(user)
        await session.flush()
        kb = KnowledgeBase(user_id=user.id, name="Graph")
        session.add(kb)
        await session.flush()
        source = KnowledgeSource(
            user_id=user.id, kb_id=kb.id, source_type="FILE", display_name="notes.md"
        )
        session.add(source)
        await session.flush()
        version = SourceVersion(
            source_id=source.id,
            user_id=user.id,
            kb_id=kb.id,
            content_hash="a" * 64,
            storage_key="test",
            mime_type="text/markdown",
            size_bytes=10,
            status="READY",
        )
        session.add(version)
        await session.flush()
        chunk = DocumentChunk(
            source_version_id=version.id,
            user_id=user.id,
            kb_id=kb.id,
            content="FastAPI uses Python",
            chunk_index=0,
            token_count=4,
        )
        session.add(chunk)
        await session.commit()
        service = GraphExtractionService(session, FakeChat())

        await service.extract_chunk(user.id, chunk.id)
        await service.extract_chunk(user.id, chunk.id)

        assert await session.scalar(select(func.count(KnowledgeEntity.id))) == 2
        assert await session.scalar(select(func.count(KnowledgeRelation.id))) == 1
        assert await session.scalar(select(func.count(KnowledgeEvidence.id))) == 3
        relation = await session.scalar(select(KnowledgeRelation))
        await KnowledgeReviewService(session).review_relation(user.id, relation.id, accept=True)
        assert relation.status == "ACTIVE"
        assert await session.scalar(select(func.count(KnowledgeRevision.id))) == 1
    await engine.dispose()
