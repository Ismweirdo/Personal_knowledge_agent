import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.infrastructure.models import (
    Base,
    DocumentChunk,
    KnowledgeBase,
    KnowledgeSource,
    SourceVersion,
    User,
)
from app.retrieval.service import RetrievalService


class UnexpectedEmbedding:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise AssertionError("profile questions must use the fast structured retrieval path")


@pytest.mark.asyncio
async def test_project_question_balances_resume_and_git_sources() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        owner = User(email="profile@example.com", password_hash="unused", role="ADMIN")
        session.add(owner)
        await session.flush()
        kb = KnowledgeBase(user_id=owner.id, name="Profile")
        session.add(kb)
        await session.flush()
        values = [
            ("FILE", "resume.pdf", "项目经历：实时通信与 AI 分身系统。"),
            ("GIT", "Personal agent", "# 项目资料卡\n项目名称：Personal agent"),
            ("GIT", "Chatroom", "# 项目资料卡\n项目名称：Chatroom"),
        ]
        for source_type, name, content in values:
            source = KnowledgeSource(
                user_id=owner.id,
                kb_id=kb.id,
                source_type=source_type,
                display_name=name,
                status="READY",
            )
            session.add(source)
            await session.flush()
            version = SourceVersion(
                source_id=source.id,
                user_id=owner.id,
                kb_id=kb.id,
                content_hash=name.ljust(64, "0")[:64],
                storage_key=f"uploads/{name}",
                mime_type="text/plain",
                size_bytes=len(content),
                status="READY",
            )
            session.add(version)
            await session.flush()
            source.active_version_id = version.id
            session.add(
                DocumentChunk(
                    source_version_id=version.id,
                    user_id=owner.id,
                    kb_id=kb.id,
                    content=content,
                    chunk_index=0,
                    token_count=10,
                    chunk_metadata={"source_type": source_type, "source_name": name},
                )
            )
        await session.commit()

        results = await RetrievalService(session, UnexpectedEmbedding()).search(
            owner.id, kb.id, "你做过哪些项目？", limit=3
        )

        assert len(results) == 3
        assert {item.metadata["source_name"] for item in results} == {
            "resume.pdf",
            "Personal agent",
            "Chatroom",
        }
    await engine.dispose()
