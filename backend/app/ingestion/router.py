from typing import Annotated

from fastapi import APIRouter, Depends, File, Response, UploadFile, status

from app.api.dependencies import AdminUserId, Session, SettingsDependency
from app.api.schemas import (
    BatchDocumentItemResponse,
    BatchDocumentUploadResponse,
    DocumentUploadResponse,
    GitSourceRequest,
    KnowledgeSourceResponse,
    WebSourceRequest,
)
from app.infrastructure.embedding import EmbeddingClient, get_embedding_client
from app.infrastructure.errors import ApplicationError
from app.ingestion.indexing import VectorIndexingService
from app.ingestion.service import FileIngestionService
from app.ingestion.source_service import SourceManagementService
from app.ingestion.sync import SourceSyncService

router = APIRouter(tags=["documents"])
EmbeddingDependency = Annotated[EmbeddingClient, Depends(get_embedding_client)]
MAX_BATCH_FILES = 20


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


@router.post(
    "/knowledge-bases/{knowledge_base_id}/documents:batch",
    response_model=BatchDocumentUploadResponse,
)
async def upload_documents(
    knowledge_base_id: str,
    files: Annotated[list[UploadFile], File()],
    session: Session,
    settings: SettingsDependency,
    user_id: AdminUserId,
) -> BatchDocumentUploadResponse:
    if not files or len(files) > MAX_BATCH_FILES:
        raise ApplicationError(
            "INVALID_BATCH_SIZE",
            f"Upload between 1 and {MAX_BATCH_FILES} files at a time",
            status_code=422,
        )
    service = FileIngestionService(session, settings)
    items: list[BatchDocumentItemResponse] = []
    for upload in files:
        filename = upload.filename or "未命名文件"
        try:
            result = await service.upload(user_id, knowledge_base_id, upload)
            items.append(
                BatchDocumentItemResponse(filename=filename, success=True, result=result)
            )
        except ApplicationError as exc:
            items.append(
                BatchDocumentItemResponse(
                    filename=filename,
                    success=False,
                    error_code=exc.code,
                    message=exc.message,
                )
            )
        finally:
            await upload.close()
    succeeded = sum(item.success for item in items)
    return BatchDocumentUploadResponse(
        total=len(items),
        succeeded=succeeded,
        failed=len(items) - succeeded,
        items=items,
    )


@router.get(
    "/knowledge-bases/{knowledge_base_id}/sources",
    response_model=list[KnowledgeSourceResponse],
)
async def list_sources(
    knowledge_base_id: str,
    session: Session,
    settings: SettingsDependency,
    user_id: AdminUserId,
) -> list[dict[str, object]]:
    return await SourceManagementService(session, settings).list(user_id, knowledge_base_id)


@router.delete(
    "/knowledge-bases/{knowledge_base_id}/sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_source(
    knowledge_base_id: str,
    source_id: str,
    session: Session,
    settings: SettingsDependency,
    user_id: AdminUserId,
) -> Response:
    await SourceManagementService(session, settings).delete(
        user_id, knowledge_base_id, source_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/knowledge-bases/{knowledge_base_id}/sources/{source_id}:sync",
    response_model=DocumentUploadResponse,
)
async def resync_source(
    knowledge_base_id: str,
    source_id: str,
    session: Session,
    settings: SettingsDependency,
    user_id: AdminUserId,
) -> DocumentUploadResponse:
    return await SourceSyncService(session, settings).sync_existing(
        user_id, knowledge_base_id, source_id
    )


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
