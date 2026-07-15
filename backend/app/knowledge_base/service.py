from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import KnowledgeBaseCreate, KnowledgeBaseUpdate
from app.infrastructure.errors import ApplicationError
from app.infrastructure.models import (
    DocumentChunk,
    IngestionTask,
    KnowledgeBase,
    KnowledgeEntity,
    KnowledgeEvidence,
    KnowledgeRelation,
    KnowledgeRevision,
    KnowledgeSource,
    LearningEvent,
    ReviewTask,
    SourceVersion,
)


class KnowledgeBaseService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self, user_id: str) -> list[KnowledgeBase]:
        result = await self.session.scalars(
            select(KnowledgeBase)
            .where(KnowledgeBase.user_id == user_id)
            .order_by(KnowledgeBase.created_at.desc())
        )
        return list(result)

    async def create(self, user_id: str, payload: KnowledgeBaseCreate) -> KnowledgeBase:
        if payload.is_published:
            await self._unpublish_others(user_id)
        knowledge_base = KnowledgeBase(user_id=user_id, **payload.model_dump())
        self.session.add(knowledge_base)
        await self._commit_unique_name()
        await self.session.refresh(knowledge_base)
        return knowledge_base

    async def get(self, user_id: str, knowledge_base_id: str) -> KnowledgeBase:
        knowledge_base = await self.session.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.id == knowledge_base_id,
                KnowledgeBase.user_id == user_id,
            )
        )
        if knowledge_base is None:
            raise ApplicationError(
                "KNOWLEDGE_BASE_NOT_FOUND", "Knowledge base not found", status_code=404
            )
        return knowledge_base

    async def update(
        self,
        user_id: str,
        knowledge_base_id: str,
        payload: KnowledgeBaseUpdate,
    ) -> KnowledgeBase:
        knowledge_base = await self.get(user_id, knowledge_base_id)
        values = payload.model_dump(exclude_unset=True)
        if values.get("is_published") is True:
            await self._unpublish_others(user_id, except_id=knowledge_base.id)
        for field, value in values.items():
            setattr(knowledge_base, field, value)
        await self._commit_unique_name()
        await self.session.refresh(knowledge_base)
        return knowledge_base

    async def delete(self, user_id: str, knowledge_base_id: str) -> None:
        knowledge_base = await self.get(user_id, knowledge_base_id)
        await self.session.delete(knowledge_base)
        await self.session.commit()

    async def clear_contents(self, user_id: str, knowledge_base_id: str) -> dict[str, int | str]:
        await self.get(user_id, knowledge_base_id)
        counts = {
            "sources": await self._count(KnowledgeSource, user_id, knowledge_base_id),
            "chunks": await self._count(DocumentChunk, user_id, knowledge_base_id),
            "entities": await self._count(KnowledgeEntity, user_id, knowledge_base_id),
            "relations": await self._count(KnowledgeRelation, user_id, knowledge_base_id),
        }
        await self.session.execute(
            delete(ReviewTask).where(
                ReviewTask.user_id == user_id,
                ReviewTask.entity_id.in_(
                    select(KnowledgeEntity.id).where(
                        KnowledgeEntity.user_id == user_id,
                        KnowledgeEntity.kb_id == knowledge_base_id,
                    )
                ),
            )
        )
        for model in (
            KnowledgeRevision,
            LearningEvent,
            KnowledgeEvidence,
            KnowledgeRelation,
            KnowledgeEntity,
        ):
            await self.session.execute(
                delete(model).where(model.user_id == user_id, model.kb_id == knowledge_base_id)
            )
        version_ids = select(SourceVersion.id).where(
            SourceVersion.user_id == user_id,
            SourceVersion.kb_id == knowledge_base_id,
        )
        await self.session.execute(
            delete(IngestionTask).where(
                IngestionTask.user_id == user_id,
                IngestionTask.source_version_id.in_(version_ids),
            )
        )
        await self.session.execute(
            delete(KnowledgeSource).where(
                KnowledgeSource.user_id == user_id,
                KnowledgeSource.kb_id == knowledge_base_id,
            )
        )
        await self.session.commit()
        return {"status": "CLEARED", **counts}

    async def _commit_unique_name(self) -> None:
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ApplicationError(
                "KNOWLEDGE_BASE_NAME_EXISTS",
                "Knowledge base name already exists",
                status_code=409,
            ) from exc

    async def _unpublish_others(self, user_id: str, except_id: str | None = None) -> None:
        conditions = [KnowledgeBase.user_id == user_id, KnowledgeBase.is_published.is_(True)]
        if except_id is not None:
            conditions.append(KnowledgeBase.id != except_id)
        await self.session.execute(
            update(KnowledgeBase).where(*conditions).values(is_published=False)
        )

    async def _count(self, model, user_id: str, knowledge_base_id: str) -> int:
        return int(
            await self.session.scalar(
                select(func.count(model.id)).where(
                    model.user_id == user_id,
                    model.kb_id == knowledge_base_id,
                )
            )
            or 0
        )
