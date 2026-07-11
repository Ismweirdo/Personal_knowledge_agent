from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile, status

from app.api.dependencies import CurrentUserId, Session, SettingsDependency
from app.api.schemas import DocumentUploadResponse
from app.infrastructure.embedding import EmbeddingClient, get_embedding_client
from app.ingestion.indexing import VectorIndexingService
from app.ingestion.service import FileIngestionService

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
    user_id: CurrentUserId,
) -> DocumentUploadResponse:
    return await FileIngestionService(session, settings).upload(user_id, knowledge_base_id, file)


@router.post("/sources/{source_id}/index")
async def index_source(
    source_id: str,
    session: Session,
    user_id: CurrentUserId,
    embedding_client: EmbeddingDependency,
) -> dict[str, int | str]:
    count = await VectorIndexingService(session, embedding_client).index(user_id, source_id)
    return {"sourceId": source_id, "indexedChunks": count, "status": "READY"}
