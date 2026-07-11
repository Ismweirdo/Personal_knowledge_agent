from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.errors import ApplicationError
from app.infrastructure.models import KnowledgeEntity, LearningEvent, ReviewTask


class ReviewService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def ensure_task(self, user_id: str, entity_id: str) -> ReviewTask:
        await self._entity(user_id, entity_id)
        task = await self.session.scalar(
            select(ReviewTask).where(
                ReviewTask.user_id == user_id,
                ReviewTask.entity_id == entity_id,
            )
        )
        if task is None:
            task = ReviewTask(user_id=user_id, entity_id=entity_id, due_at=datetime.now(UTC))
            self.session.add(task)
            await self.session.flush()
        return task

    async def grade(self, user_id: str, entity_id: str, grade: int) -> ReviewTask:
        entity = await self._entity(user_id, entity_id)
        if entity.status != "ACTIVE":
            raise ApplicationError(
                "KNOWLEDGE_NOT_ACTIVE", "Only active knowledge can be reviewed", status_code=409
            )
        task = await self.ensure_task(user_id, entity_id)
        if grade < 3:
            task.repetitions = 0
            task.interval_days = 1
        else:
            task.repetitions += 1
            if task.repetitions == 1:
                task.interval_days = 1
            elif task.repetitions == 2:
                task.interval_days = 6
            else:
                task.interval_days = max(1, round(task.interval_days * task.ease_factor))
        task.ease_factor = max(
            1.3,
            task.ease_factor + (0.1 - (5 - grade) * (0.08 + (5 - grade) * 0.02)),
        )
        task.mastery = round((task.mastery * 0.7) + (grade / 5 * 0.3), 4)
        task.due_at = datetime.now(UTC) + timedelta(days=task.interval_days)
        task.status = "PENDING"
        self.session.add(
            LearningEvent(
                user_id=user_id,
                kb_id=entity.kb_id,
                event_type="REVIEW_COMPLETED",
                topic_entity_id=entity.id,
                event_metadata={
                    "grade": grade,
                    "intervalDays": task.interval_days,
                    "mastery": task.mastery,
                },
            )
        )
        await self.session.commit()
        return task

    async def due(
        self, user_id: str, *, include_future: bool = False
    ) -> list[tuple[ReviewTask, str]]:
        query = (
            select(ReviewTask, KnowledgeEntity.canonical_name)
            .join(KnowledgeEntity, KnowledgeEntity.id == ReviewTask.entity_id)
            .where(ReviewTask.user_id == user_id, KnowledgeEntity.status == "ACTIVE")
            .order_by(ReviewTask.due_at)
        )
        if not include_future:
            query = query.where(ReviewTask.due_at <= datetime.now(UTC))
        return list((await self.session.execute(query)).tuples())

    async def _entity(self, user_id: str, entity_id: str) -> KnowledgeEntity:
        entity = await self.session.scalar(
            select(KnowledgeEntity).where(
                KnowledgeEntity.id == entity_id,
                KnowledgeEntity.user_id == user_id,
            )
        )
        if entity is None:
            raise ApplicationError(
                "KNOWLEDGE_ENTITY_NOT_FOUND", "Knowledge entity not found", status_code=404
            )
        return entity
