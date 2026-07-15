import hashlib
from pathlib import Path
from uuid import uuid4

import anyio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import DocumentUploadResponse
from app.connectors.git import snapshot_repository
from app.connectors.web import fetch_web, validate_public_url
from app.infrastructure.config import Settings
from app.infrastructure.errors import ApplicationError
from app.infrastructure.models import DocumentChunk, IngestionTask, KnowledgeSource, SourceVersion
from app.ingestion.parser import ParsedPage, chunk_pages
from app.ingestion.tasks import enqueue_task
from app.knowledge_base.service import KnowledgeBaseService

GIT_IMPORT_VERSION = "profile-clean-v2"


class SourceSyncService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def sync_web(self, user_id: str, kb_id: str, url: str) -> DocumentUploadResponse:
        await KnowledgeBaseService(self.session).get(user_id, kb_id)
        locator = validate_public_url(url)
        source = await self._source(user_id, kb_id, "WEB", locator)
        latest = await self._latest(source)
        snapshot = await fetch_web(
            locator,
            etag=latest.etag if latest else None,
            last_modified=latest.last_modified if latest else None,
        )
        if snapshot is None and latest is not None:
            return await self._response(latest, unchanged=True)
        assert snapshot is not None
        return await self._persist(
            user_id,
            kb_id,
            source,
            "WEB",
            locator,
            snapshot.url,
            snapshot.text,
            etag=snapshot.etag,
            last_modified=snapshot.last_modified,
        )

    async def sync_git(
        self, user_id: str, kb_id: str, repository_path: str
    ) -> DocumentUploadResponse:
        await KnowledgeBaseService(self.session).get(user_id, kb_id)
        source_locator = repository_path.strip()
        snapshot = await anyio.to_thread.run_sync(
            snapshot_repository, source_locator, self.settings.git_import_root
        )
        path = snapshot.locator
        source = await self._source(user_id, kb_id, "GIT", path)
        latest = await self._latest(source)
        revision = f"{snapshot.revision}:{GIT_IMPORT_VERSION}"
        if latest is not None and latest.revision == revision:
            return await self._response(latest, unchanged=True)
        return await self._persist(
            user_id,
            kb_id,
            source,
            "GIT",
            path,
            snapshot.display_name,
            snapshot.text,
            revision=revision,
        )

    async def sync_existing(
        self, user_id: str, kb_id: str, source_id: str
    ) -> DocumentUploadResponse:
        await KnowledgeBaseService(self.session).get(user_id, kb_id)
        source = await self.session.scalar(
            select(KnowledgeSource).where(
                KnowledgeSource.id == source_id,
                KnowledgeSource.user_id == user_id,
                KnowledgeSource.kb_id == kb_id,
            )
        )
        if source is None:
            raise ApplicationError(
                "SOURCE_NOT_FOUND", "Knowledge source not found", status_code=404
            )
        if not source.source_locator:
            raise ApplicationError(
                "SOURCE_LOCATOR_MISSING", "Source has no sync locator", status_code=409
            )
        if source.source_type == "WEB":
            return await self.sync_web(user_id, kb_id, source.source_locator)
        if source.source_type == "GIT":
            return await self.sync_git(user_id, kb_id, source.source_locator)
        raise ApplicationError(
            "SOURCE_NOT_SYNCABLE",
            "Uploaded files cannot be synchronized; upload a new version instead",
            status_code=422,
        )

    async def _persist(
        self,
        user_id: str,
        kb_id: str,
        source: KnowledgeSource | None,
        source_type: str,
        locator: str,
        display_name: str,
        text: str,
        **metadata: str | None,
    ) -> DocumentUploadResponse:
        content_hash = hashlib.sha256(text.encode()).hexdigest()
        if source is not None:
            existing = await self.session.scalar(
                select(SourceVersion).where(
                    SourceVersion.source_id == source.id,
                    SourceVersion.content_hash == content_hash,
                )
            )
            if existing is not None:
                return await self._response(existing, unchanged=True)
        if source is None:
            source = KnowledgeSource(
                user_id=user_id,
                kb_id=kb_id,
                source_type=source_type,
                display_name=display_name,
                source_locator=locator,
                status="PROCESSING",
            )
            self.session.add(source)
            await self.session.flush()
        storage = Path(self.settings.file_storage_path) / user_id / kb_id / f"{uuid4()}.txt"
        storage.parent.mkdir(parents=True, exist_ok=True)
        storage.write_text(text, encoding="utf-8")
        chunks = chunk_pages([ParsedPage(text)])
        try:
            version = SourceVersion(
                source_id=source.id,
                user_id=user_id,
                kb_id=kb_id,
                content_hash=content_hash,
                storage_key=str(storage),
                mime_type="text/plain",
                size_bytes=len(text.encode()),
                status="PARSED",
                **metadata,
            )
            self.session.add(version)
            await self.session.flush()
            self.session.add_all(
                DocumentChunk(
                    source_version_id=version.id,
                    user_id=user_id,
                    kb_id=kb_id,
                    content=str(chunk["content"]),
                    chunk_index=index,
                    token_count=max(1, len(str(chunk["content"])) // 4),
                    chunk_metadata={
                        **{key: value for key, value in chunk.items() if key != "content"},
                        "source_type": source_type,
                        "source_name": display_name,
                        "source_locator": locator,
                    },
                )
                for index, chunk in enumerate(chunks)
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
            storage.unlink(missing_ok=True)
            raise

    async def _source(
        self, user_id: str, kb_id: str, source_type: str, locator: str
    ) -> KnowledgeSource | None:
        return await self.session.scalar(
            select(KnowledgeSource).where(
                KnowledgeSource.user_id == user_id,
                KnowledgeSource.kb_id == kb_id,
                KnowledgeSource.source_type == source_type,
                KnowledgeSource.source_locator == locator,
            )
        )

    async def _latest(self, source: KnowledgeSource | None) -> SourceVersion | None:
        if source is None:
            return None
        return await self.session.scalar(
            select(SourceVersion)
            .where(SourceVersion.source_id == source.id)
            .order_by(SourceVersion.created_at.desc())
        )

    async def _response(self, version: SourceVersion, *, unchanged: bool) -> DocumentUploadResponse:
        count = await self.session.scalar(
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
            chunk_count=count or 0,
            unchanged=unchanged,
            task_id=task_id,
        )
