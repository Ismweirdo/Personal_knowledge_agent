from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import StreamingResponse

from app.api.dependencies import AdminUserId, CurrentUserId, Session
from app.api.schemas import (
    ChatRequest,
    ConversationCreate,
    ConversationResponse,
    MessageResponse,
    VisitorFeedbackCreate,
    VisitorFeedbackResponse,
)
from app.conversation.service import RagConversationService
from app.infrastructure.embedding import EmbeddingClient, get_embedding_client
from app.infrastructure.llm import ChatModelClient, get_chat_model_client
from app.retrieval.service import RetrievalService

router = APIRouter(prefix="/conversations", tags=["conversations"])
Embedding = Annotated[EmbeddingClient, Depends(get_embedding_client)]
Chat = Annotated[ChatModelClient, Depends(get_chat_model_client)]


def build_service(session: Session, embedding: Embedding, chat: Chat) -> RagConversationService:
    return RagConversationService(session, RetrievalService(session, embedding), chat)


def build_metadata_service(session: Session) -> RagConversationService:
    return RagConversationService(session)


Service = Annotated[RagConversationService, Depends(build_metadata_service)]
StreamService = Annotated[RagConversationService, Depends(build_service)]


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreate, user_id: CurrentUserId, service: Service
) -> object:
    return await service.create(user_id, payload.knowledge_base_id, payload.title)


@router.get("", response_model=list[ConversationResponse])
async def list_conversations(user_id: CurrentUserId, service: Service) -> list[object]:
    return await service.list_conversations(user_id)


@router.post(
    "/feedback",
    response_model=VisitorFeedbackResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_feedback(
    payload: VisitorFeedbackCreate, user_id: CurrentUserId, service: Service
) -> object:
    return await service.feedback(
        user_id, payload.conversation_id, payload.position, payload.comment
    )


@router.get("/feedback", response_model=list[VisitorFeedbackResponse])
async def list_feedback(_: AdminUserId, service: Service) -> list[object]:
    return await service.list_feedback()


@router.get("/{conversation_id}/messages", response_model=list[MessageResponse])
async def list_messages(
    conversation_id: str, user_id: CurrentUserId, service: Service
) -> list[object]:
    return await service.list_messages(user_id, conversation_id)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: str, user_id: CurrentUserId, service: Service
) -> Response:
    await service.delete(user_id, conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{conversation_id}/messages:stream")
async def stream_message(
    conversation_id: str, payload: ChatRequest, user_id: CurrentUserId, service: StreamService
) -> StreamingResponse:
    return StreamingResponse(
        service.stream(user_id, conversation_id, payload.content),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
