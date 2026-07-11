from typing import Annotated

from fastapi import APIRouter, File, UploadFile, status

from app.api.dependencies import CurrentUserId, Session, SettingsDependency
from app.api.schemas import DocumentUploadResponse
from app.ingestion.service import FileIngestionService

router = APIRouter(tags=["documents"])


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
