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
from app.infrastructure.models import DocumentChunk, KnowledgeSource, SourceVersion
from app.ingestion.parser import ParsedPage, chunk_pages
from app.knowledge_base.service import KnowledgeBaseService


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
        path = await anyio.to_thread.run_sync(lambda: str(Path(repository_path).resolve()))
        source = await self._source(user_id, kb_id, "GIT", path)
        snapshot = await anyio.to_thread.run_sync(
            snapshot_repository, path, self.settings.git_import_root
        )
        latest = await self._latest(source)
        if latest is not None and latest.revision == snapshot.revision:
            return await self._response(latest, unchanged=True)
        return await self._persist(
            user_id,
            kb_id,
            source,
            "GIT",
            path,
            Path(path).name,
            snapshot.text,
            revision=snapshot.revision,
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
                    chunk_metadata={key: value for key, value in chunk.items() if key != "content"},
                )
                for index, chunk in enumerate(chunks)
            )
            source.status = "PARSED"
            await self.session.commit()
            return DocumentUploadResponse(
                source_id=source.id,
                version_id=version.id,
                status=version.status,
                content_hash=content_hash,
                chunk_count=len(chunks),
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
        return DocumentUploadResponse(
            source_id=version.source_id,
            version_id=version.id,
            status=version.status,
            content_hash=version.content_hash,
            chunk_count=count or 0,
            unchanged=unchanged,
        )
