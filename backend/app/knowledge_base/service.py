from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import KnowledgeBaseCreate, KnowledgeBaseUpdate
from app.infrastructure.errors import ApplicationError
from app.infrastructure.models import KnowledgeBase


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
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(knowledge_base, field, value)
        await self._commit_unique_name()
        await self.session.refresh(knowledge_base)
        return knowledge_base

    async def delete(self, user_id: str, knowledge_base_id: str) -> None:
        knowledge_base = await self.get(user_id, knowledge_base_id)
        await self.session.delete(knowledge_base)
        await self.session.commit()

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
