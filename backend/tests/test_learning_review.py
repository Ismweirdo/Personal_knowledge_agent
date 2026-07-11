from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.infrastructure.models import Base, KnowledgeBase, KnowledgeEntity, LearningEvent, User
from app.learning.service import ReviewService


@pytest.mark.asyncio
async def test_review_schedule_and_learning_events() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        admin = User(email="admin@example.com", password_hash="unused", role="ADMIN")
        session.add(admin)
        await session.flush()
        kb = KnowledgeBase(user_id=admin.id, name="Learning")
        session.add(kb)
        await session.flush()
        entity = KnowledgeEntity(
            user_id=admin.id,
            kb_id=kb.id,
            canonical_name="FastAPI",
            normalized_name="fastapi",
            entity_type="TECHNOLOGY",
            status="ACTIVE",
            confidence=1.0,
        )
        session.add(entity)
        await session.commit()
        service = ReviewService(session)

        initial = await service.ensure_task(admin.id, entity.id)
        await session.commit()
        assert initial.due_at <= datetime.now(UTC)

        first = await service.grade(admin.id, entity.id, 5)
        assert first.repetitions == 1
        assert first.interval_days == 1
        second = await service.grade(admin.id, entity.id, 4)
        assert second.repetitions == 2
        assert second.interval_days == 6
        failed = await service.grade(admin.id, entity.id, 1)
        assert failed.repetitions == 0
        assert failed.interval_days == 1
        assert 0 <= failed.mastery <= 1
        assert await session.scalar(select(func.count(LearningEvent.id))) == 3

    await engine.dispose()
