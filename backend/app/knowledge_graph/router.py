from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.dependencies import AdminUserId, Session
from app.api.schemas import KnowledgeReviewRequest
from app.infrastructure.llm import ChatModelClient, get_chat_model_client
from app.infrastructure.models import KnowledgeEntity, KnowledgeRelation
from app.knowledge_graph.extraction import GraphExtractionService
from app.knowledge_graph.review import KnowledgeReviewService
from app.learning.service import ReviewService

router = APIRouter(tags=["knowledge-graph"])
Chat = Annotated[ChatModelClient, Depends(get_chat_model_client)]


@router.post("/chunks/{chunk_id}/knowledge:extract")
async def extract_chunk(
    chunk_id: str, session: Session, user_id: AdminUserId, chat: Chat
) -> dict[str, int]:
    return await GraphExtractionService(session, chat).extract_chunk(user_id, chunk_id)


@router.get("/knowledge-bases/{kb_id}/knowledge-candidates")
async def list_candidates(
    kb_id: str, session: Session, user_id: AdminUserId
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


@router.get("/knowledge-bases/{kb_id}/graph")
async def get_graph(
    kb_id: str, session: Session, user_id: AdminUserId, limit: int = 80
) -> dict[str, list[dict[str, object]]]:
    entities = list(
        await session.scalars(
            select(KnowledgeEntity)
            .where(
                KnowledgeEntity.kb_id == kb_id,
                KnowledgeEntity.user_id == user_id,
                KnowledgeEntity.status.in_(("ACTIVE", "CANDIDATE")),
            )
            .order_by(KnowledgeEntity.status, KnowledgeEntity.confidence.desc())
            .limit(limit)
        )
    )
    entity_by_id = {item.id: item for item in entities}
    relations = list(
        await session.scalars(
            select(KnowledgeRelation)
            .where(
                KnowledgeRelation.kb_id == kb_id,
                KnowledgeRelation.user_id == user_id,
                KnowledgeRelation.status.in_(("ACTIVE", "CANDIDATE")),
                KnowledgeRelation.source_entity_id.in_(entity_by_id),
                KnowledgeRelation.target_entity_id.in_(entity_by_id),
            )
            .order_by(KnowledgeRelation.status, KnowledgeRelation.confidence.desc())
            .limit(limit * 2)
        )
    )
    return {
        "nodes": [
            {
                "id": item.id,
                "label": item.canonical_name,
                "type": item.entity_type,
                "status": item.status,
                "confidence": item.confidence,
            }
            for item in entities
        ],
        "edges": [
            {
                "id": item.id,
                "source": item.source_entity_id,
                "target": item.target_entity_id,
                "label": item.predicate,
                "status": item.status,
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
    user_id: AdminUserId,
) -> dict[str, str]:
    service = KnowledgeReviewService(session)
    accept = action == "accept"
    if candidate_type == "entities":
        result = await service.review_entity(
            user_id, candidate_id, accept=accept, reason=payload.reason
        )
        if accept:
            await ReviewService(session).ensure_task(user_id, result.id)
            await session.commit()
    else:
        result = await service.review_relation(
            user_id, candidate_id, accept=accept, reason=payload.reason
        )
    return {"id": result.id, "status": result.status}
