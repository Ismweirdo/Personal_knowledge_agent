from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile, status

from app.api.dependencies import AdminUserId, Session, SettingsDependency
from app.api.schemas import DocumentUploadResponse, GitSourceRequest, WebSourceRequest
from app.infrastructure.embedding import EmbeddingClient, get_embedding_client
from app.ingestion.indexing import VectorIndexingService
from app.ingestion.service import FileIngestionService
from app.ingestion.sync import SourceSyncService

router = APIRouter(tags=["documents"])
EmbeddingDependency = Annotated[EmbeddingClient, Depends(get_embedding_client)]


@router.post(
    "/knowledge-bases/{knowledge_base_id}/documents",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    knowledge_base_id: str,
    file: Annotated[UploadFile, File()],
    session: Session,
    settings: SettingsDependency,
    user_id: AdminUserId,
) -> DocumentUploadResponse:
    return await FileIngestionService(session, settings).upload(user_id, knowledge_base_id, file)


@router.post("/sources/{source_id}/index")
async def index_source(
    source_id: str,
    session: Session,
    user_id: AdminUserId,
    embedding_client: EmbeddingDependency,
) -> dict[str, int | str]:
    count = await VectorIndexingService(session, embedding_client).index(user_id, source_id)
    return {"sourceId": source_id, "indexedChunks": count, "status": "READY"}


@router.post(
    "/knowledge-bases/{knowledge_base_id}/sources:web", response_model=DocumentUploadResponse
)
async def sync_web_source(
    knowledge_base_id: str,
    payload: WebSourceRequest,
    session: Session,
    settings: SettingsDependency,
    user_id: AdminUserId,
) -> DocumentUploadResponse:
    return await SourceSyncService(session, settings).sync_web(
        user_id, knowledge_base_id, payload.url
    )


@router.post(
    "/knowledge-bases/{knowledge_base_id}/sources:git", response_model=DocumentUploadResponse
)
async def sync_git_source(
    knowledge_base_id: str,
    payload: GitSourceRequest,
    session: Session,
    settings: SettingsDependency,
    user_id: AdminUserId,
) -> DocumentUploadResponse:
    return await SourceSyncService(session, settings).sync_git(
        user_id, knowledge_base_id, payload.repository_path
    )
