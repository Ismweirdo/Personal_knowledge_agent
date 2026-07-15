from fastapi import APIRouter
from sqlalchemy import select

from app.api.dependencies import Session
from app.infrastructure.errors import ApplicationError
from app.infrastructure.models import KnowledgeBase

router = APIRouter(tags=["agent"])


@router.get("/agent")
async def get_public_agent(session: Session) -> dict[str, str | None]:
    knowledge_base = await session.scalar(
        select(KnowledgeBase)
        .where(KnowledgeBase.is_published.is_(True))
        .order_by(KnowledgeBase.updated_at.desc(), KnowledgeBase.created_at.desc())
        .limit(1)
    )
    if knowledge_base is None:
        raise ApplicationError("AGENT_NOT_AVAILABLE", "Agent is not available", status_code=404)
    return {
        "knowledgeBaseId": knowledge_base.id,
        "name": knowledge_base.name,
        "description": knowledge_base.description,
    }
