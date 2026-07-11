from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.dependencies import CurrentUserId, Session
from app.api.schemas import KnowledgeReviewRequest
from app.infrastructure.llm import ChatModelClient, get_chat_model_client
from app.infrastructure.models import KnowledgeEntity, KnowledgeRelation
from app.knowledge_graph.extraction import GraphExtractionService
from app.knowledge_graph.review import KnowledgeReviewService

router = APIRouter(tags=["knowledge-graph"])
Chat = Annotated[ChatModelClient, Depends(get_chat_model_client)]


@router.post("/chunks/{chunk_id}/knowledge:extract")
async def extract_chunk(
    chunk_id: str, session: Session, user_id: CurrentUserId, chat: Chat
) -> dict[str, int]:
    return await GraphExtractionService(session, chat).extract_chunk(user_id, chunk_id)


@router.get("/knowledge-bases/{kb_id}/knowledge-candidates")
async def list_candidates(
    kb_id: str, session: Session, user_id: CurrentUserId
) -> dict[str, list[dict[str, object]]]:
    entities = list(
        await session.scalars(
            select(KnowledgeEntity).where(
                KnowledgeEntity.kb_id == kb_id,
                KnowledgeEntity.user_id == user_id,
                KnowledgeEntity.status == "CANDIDATE",
            )
        )
    )
    relations = list(
        await session.scalars(
            select(KnowledgeRelation).where(
                KnowledgeRelation.kb_id == kb_id,
                KnowledgeRelation.user_id == user_id,
                KnowledgeRelation.status == "CANDIDATE",
            )
        )
    )
    return {
        "entities": [
            {
                "id": item.id,
                "name": item.canonical_name,
                "type": item.entity_type,
                "confidence": item.confidence,
            }
            for item in entities
        ],
        "relations": [
            {
                "id": item.id,
                "sourceEntityId": item.source_entity_id,
                "predicate": item.predicate,
                "targetEntityId": item.target_entity_id,
                "confidence": item.confidence,
            }
            for item in relations
        ],
    }


@router.post("/knowledge-candidates/{candidate_type}/{candidate_id}:{action}")
async def review_candidate(
    candidate_type: Literal["entities", "relations"],
    candidate_id: str,
    action: Literal["accept", "reject"],
    payload: KnowledgeReviewRequest,
    session: Session,
    user_id: CurrentUserId,
) -> dict[str, str]:
    service = KnowledgeReviewService(session)
    accept = action == "accept"
    if candidate_type == "entities":
        result = await service.review_entity(
            user_id, candidate_id, accept=accept, reason=payload.reason
        )
    else:
        result = await service.review_relation(
            user_id, candidate_id, accept=accept, reason=payload.reason
        )
    return {"id": result.id, "status": result.status}
