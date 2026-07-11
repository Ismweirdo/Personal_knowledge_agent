from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse

from app.api.dependencies import CurrentUserId, Session
from app.api.schemas import ChatRequest, ConversationCreate, ConversationResponse
from app.conversation.service import RagConversationService
from app.infrastructure.embedding import EmbeddingClient, get_embedding_client
from app.infrastructure.llm import ChatModelClient, get_chat_model_client
from app.retrieval.service import RetrievalService

router = APIRouter(prefix="/conversations", tags=["conversations"])
Embedding = Annotated[EmbeddingClient, Depends(get_embedding_client)]
Chat = Annotated[ChatModelClient, Depends(get_chat_model_client)]


def build_service(session: Session, embedding: Embedding, chat: Chat) -> RagConversationService:
    return RagConversationService(session, RetrievalService(session, embedding), chat)


Service = Annotated[RagConversationService, Depends(build_service)]


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreate, user_id: CurrentUserId, service: Service
) -> object:
    return await service.create(user_id, payload.knowledge_base_id, payload.title)


@router.post("/{conversation_id}/messages:stream")
async def stream_message(
    conversation_id: str, payload: ChatRequest, user_id: CurrentUserId, service: Service
) -> StreamingResponse:
    return StreamingResponse(
        service.stream(user_id, conversation_id, payload.content),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
