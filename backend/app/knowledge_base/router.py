from fastapi import APIRouter, Response, status

from app.api.dependencies import AdminUserId, Session
from app.api.schemas import KnowledgeBaseCreate, KnowledgeBaseResponse, KnowledgeBaseUpdate
from app.knowledge_base.service import KnowledgeBaseService

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


@router.get("", response_model=list[KnowledgeBaseResponse])
async def list_knowledge_bases(session: Session, user_id: AdminUserId) -> list[object]:
    return await KnowledgeBaseService(session).list(user_id)


@router.post("", response_model=KnowledgeBaseResponse, status_code=status.HTTP_201_CREATED)
async def create_knowledge_base(
    payload: KnowledgeBaseCreate,
    session: Session,
    user_id: AdminUserId,
) -> object:
    return await KnowledgeBaseService(session).create(user_id, payload)


@router.patch("/{knowledge_base_id}", response_model=KnowledgeBaseResponse)
async def update_knowledge_base(
    knowledge_base_id: str,
    payload: KnowledgeBaseUpdate,
    session: Session,
    user_id: AdminUserId,
) -> object:
    return await KnowledgeBaseService(session).update(user_id, knowledge_base_id, payload)


@router.delete("/{knowledge_base_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge_base(
    knowledge_base_id: str,
    session: Session,
    user_id: AdminUserId,
) -> Response:
    await KnowledgeBaseService(session).delete(user_id, knowledge_base_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
