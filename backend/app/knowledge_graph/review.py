from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.errors import ApplicationError
from app.infrastructure.models import KnowledgeEntity, KnowledgeRelation, KnowledgeRevision


class KnowledgeReviewService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def review_entity(
        self, user_id: str, entity_id: str, *, accept: bool, reason: str | None = None
    ) -> KnowledgeEntity:
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
        if entity.status != "CANDIDATE":
            raise ApplicationError(
                "KNOWLEDGE_ALREADY_REVIEWED",
                "Knowledge candidate was already reviewed",
                status_code=409,
            )
        before = {"status": entity.status}
        entity.status = "ACTIVE" if accept else "REJECTED"
        self.session.add(
            KnowledgeRevision(
                user_id=user_id,
                kb_id=entity.kb_id,
                target_type="ENTITY",
                target_id=entity.id,
                action="ACCEPT" if accept else "REJECT",
                before_value=before,
                after_value={"status": entity.status},
                reason=reason,
            )
        )
        await self.session.commit()
        return entity

    async def review_relation(
        self, user_id: str, relation_id: str, *, accept: bool, reason: str | None = None
    ) -> KnowledgeRelation:
        relation = await self.session.scalar(
            select(KnowledgeRelation).where(
                KnowledgeRelation.id == relation_id, KnowledgeRelation.user_id == user_id
            )
        )
        if relation is None:
            raise ApplicationError(
                "KNOWLEDGE_RELATION_NOT_FOUND", "Knowledge relation not found", status_code=404
            )
        if relation.status != "CANDIDATE":
            raise ApplicationError(
                "KNOWLEDGE_ALREADY_REVIEWED",
                "Knowledge candidate was already reviewed",
                status_code=409,
            )
        before = {"status": relation.status}
        relation.status = "ACTIVE" if accept else "REJECTED"
        self.session.add(
            KnowledgeRevision(
                user_id=user_id,
                kb_id=relation.kb_id,
                target_type="RELATION",
                target_id=relation.id,
                action="ACCEPT" if accept else "REJECT",
                before_value=before,
                after_value={"status": relation.status},
                reason=reason,
            )
        )
        await self.session.commit()
        return relation
