import hashlib
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import DocumentUploadResponse
from app.infrastructure.config import Settings
from app.infrastructure.errors import ApplicationError
from app.infrastructure.models import DocumentChunk, IngestionTask, KnowledgeSource, SourceVersion
from app.ingestion.parser import chunk_pages, parse_document
from app.ingestion.tasks import enqueue_task
from app.knowledge_base.service import KnowledgeBaseService


class FileIngestionService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def upload(
        self,
        user_id: str,
        knowledge_base_id: str,
        upload: UploadFile,
    ) -> DocumentUploadResponse:
        await KnowledgeBaseService(self.session).get(user_id, knowledge_base_id)
        filename = Path(upload.filename or "").name
        if not filename:
            raise ApplicationError("INVALID_FILENAME", "Filename is required", status_code=422)

        content = await upload.read(self.settings.max_upload_bytes + 1)
        if len(content) > self.settings.max_upload_bytes:
            raise ApplicationError(
                "DOCUMENT_TOO_LARGE", "Document exceeds size limit", status_code=413
            )
        content_hash = hashlib.sha256(content).hexdigest()
        source = await self._find_source(user_id, knowledge_base_id, filename)
        existing = await self._find_version(source, content_hash)
        if existing is not None:
            return await self._response(existing, unchanged=True)

        storage_path = self._storage_path(user_id, knowledge_base_id, filename)
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage_path.write_bytes(content)
        try:
            pages = parse_document(storage_path, filename)
            chunks = chunk_pages(pages)
            if source is None:
                source = KnowledgeSource(
                    user_id=user_id,
                    kb_id=knowledge_base_id,
                    source_type="FILE",
                    display_name=filename,
                    status="PROCESSING",
                )
                self.session.add(source)
                await self.session.flush()
            version = SourceVersion(
                source_id=source.id,
                user_id=user_id,
                kb_id=knowledge_base_id,
                content_hash=content_hash,
                storage_key=str(storage_path),
                mime_type=upload.content_type or "application/octet-stream",
                size_bytes=len(content),
                status="PARSED",
            )
            self.session.add(version)
            await self.session.flush()
            self.session.add_all(
                [
                    DocumentChunk(
                        source_version_id=version.id,
                        user_id=user_id,
                        kb_id=knowledge_base_id,
                        content=str(chunk["content"]),
                        chunk_index=index,
                        token_count=max(1, len(str(chunk["content"])) // 4),
                        chunk_metadata={
                            **{key: value for key, value in chunk.items() if key != "content"},
                            "source_type": "FILE",
                            "source_name": filename,
                        },
                    )
                    for index, chunk in enumerate(chunks)
                ]
            )
            source.status = "PARSED"
            task = await enqueue_task(self.session, user_id, source.id, version.id)
            await self.session.commit()
            return DocumentUploadResponse(
                source_id=source.id,
                version_id=version.id,
                status=version.status,
                content_hash=content_hash,
                chunk_count=len(chunks),
                task_id=task.id,
            )
        except Exception:
            await self.session.rollback()
            storage_path.unlink(missing_ok=True)
            raise

    async def _find_source(
        self, user_id: str, knowledge_base_id: str, filename: str
    ) -> KnowledgeSource | None:
        return await self.session.scalar(
            select(KnowledgeSource).where(
                KnowledgeSource.user_id == user_id,
                KnowledgeSource.kb_id == knowledge_base_id,
                KnowledgeSource.source_type == "FILE",
                KnowledgeSource.display_name == filename,
            )
        )

    async def _find_version(
        self, source: KnowledgeSource | None, content_hash: str
    ) -> SourceVersion | None:
        if source is None:
            return None
        return await self.session.scalar(
            select(SourceVersion).where(
                SourceVersion.source_id == source.id,
                SourceVersion.content_hash == content_hash,
                SourceVersion.status.in_(("PARSED", "INDEXING", "READY")),
            )
        )

    async def _response(self, version: SourceVersion, *, unchanged: bool) -> DocumentUploadResponse:
        chunk_count = await self.session.scalar(
            select(func.count(DocumentChunk.id)).where(
                DocumentChunk.source_version_id == version.id
            )
        )
        task_id = await self.session.scalar(
            select(IngestionTask.id).where(IngestionTask.source_version_id == version.id)
        )
        return DocumentUploadResponse(
            source_id=version.source_id,
            version_id=version.id,
            status=version.status,
            content_hash=version.content_hash,
            chunk_count=chunk_count or 0,
            unchanged=unchanged,
            task_id=task_id,
        )

    def _storage_path(self, user_id: str, knowledge_base_id: str, filename: str) -> Path:
        extension = Path(filename).suffix.lower()
        return (
            Path(self.settings.file_storage_path)
            / user_id
            / knowledge_base_id
            / f"{uuid4()}{extension}"
        )
