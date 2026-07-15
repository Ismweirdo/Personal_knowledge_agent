from __future__ import annotations

from pathlib import Path

from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.config import Settings
from app.infrastructure.errors import ApplicationError
from app.infrastructure.models import (
    DocumentChunk,
    IngestionTask,
    KnowledgeEntity,
    KnowledgeEvidence,
    KnowledgeRelation,
    KnowledgeSource,
    MessageCitation,
    ReviewTask,
    SourceVersion,
)
from app.knowledge_base.service import KnowledgeBaseService


class SourceManagementService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def list(self, user_id: str, kb_id: str) -> list[dict[str, object]]:
        await KnowledgeBaseService(self.session).get(user_id, kb_id)
        sources = list(
            await self.session.scalars(
                select(KnowledgeSource)
                .where(KnowledgeSource.user_id == user_id, KnowledgeSource.kb_id == kb_id)
                .order_by(KnowledgeSource.created_at.desc())
            )
        )
        result: list[dict[str, object]] = []
        for source in sources:
            latest = await self.session.scalar(
                select(SourceVersion)
                .where(SourceVersion.source_id == source.id)
                .order_by(SourceVersion.created_at.desc())
                .limit(1)
            )
            task = await self.session.scalar(
                select(IngestionTask)
                .where(IngestionTask.source_id == source.id)
                .order_by(IngestionTask.created_at.desc())
                .limit(1)
            )
            version_count = int(
                await self.session.scalar(
                    select(func.count(SourceVersion.id)).where(
                        SourceVersion.source_id == source.id
                    )
                )
                or 0
            )
            chunk_count = 0
            if latest is not None:
                chunk_count = int(
                    await self.session.scalar(
                        select(func.count(DocumentChunk.id)).where(
                            DocumentChunk.source_version_id == latest.id
                        )
                    )
                    or 0
                )
            result.append(
                {
                    "id": source.id,
                    "knowledge_base_id": source.kb_id,
                    "source_type": source.source_type,
                    "display_name": source.display_name,
                    "source_locator": source.source_locator,
                    "status": source.status,
                    "active_version_id": source.active_version_id,
                    "latest_version_id": latest.id if latest else None,
                    "latest_version_status": latest.status if latest else None,
                    "version_count": version_count,
                    "chunk_count": chunk_count,
                    "size_bytes": latest.size_bytes if latest else None,
                    "task_status": task.status if task else None,
                    "task_progress": task.progress if task else None,
                    "last_synced_at": latest.created_at if latest else None,
                    "created_at": source.created_at,
                }
            )
        return result

    async def get(self, user_id: str, kb_id: str, source_id: str) -> KnowledgeSource:
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
        return source

    async def delete(self, user_id: str, kb_id: str, source_id: str) -> dict[str, int | str]:
        await KnowledgeBaseService(self.session).get(user_id, kb_id)
        source = await self.get(user_id, kb_id, source_id)
        running = int(
            await self.session.scalar(
                select(func.count(IngestionTask.id)).where(
                    IngestionTask.source_id == source.id,
                    IngestionTask.status == "RUNNING",
                )
            )
            or 0
        )
        if running:
            raise ApplicationError(
                "SOURCE_TASK_RUNNING",
                "Source is currently being processed; delete it after the task finishes",
                status_code=409,
            )

        versions = list(
            await self.session.scalars(
                select(SourceVersion).where(SourceVersion.source_id == source.id)
            )
        )
        version_ids = [version.id for version in versions]
        storage_keys = [version.storage_key for version in versions]
        chunk_ids: list[str] = []
        if version_ids:
            chunk_ids = list(
                await self.session.scalars(
                    select(DocumentChunk.id).where(
                        DocumentChunk.source_version_id.in_(version_ids)
                    )
                )
            )
            evidence_filters = [KnowledgeEvidence.source_version_id.in_(version_ids)]
            if chunk_ids:
                evidence_filters.append(KnowledgeEvidence.chunk_id.in_(chunk_ids))
                await self.session.execute(
                    delete(MessageCitation).where(MessageCitation.chunk_id.in_(chunk_ids))
                )
            await self.session.execute(
                delete(KnowledgeEvidence).where(or_(*evidence_filters))
            )

        await self.session.execute(
            delete(IngestionTask).where(IngestionTask.source_id == source.id)
        )
        if version_ids:
            await self.session.execute(
                delete(DocumentChunk).where(DocumentChunk.source_version_id.in_(version_ids))
            )
            await self.session.execute(
                delete(SourceVersion).where(SourceVersion.id.in_(version_ids))
            )
        await self.session.delete(source)
        await self.session.flush()
        await self._delete_orphaned_graph(user_id, kb_id)
        await self.session.commit()
        removed_files = self._remove_storage_files(storage_keys)
        return {
            "status": "DELETED",
            "versions": len(version_ids),
            "chunks": len(chunk_ids),
            "files": removed_files,
        }

    async def _delete_orphaned_graph(self, user_id: str, kb_id: str) -> None:
        orphan_relation_ids = list(
            await self.session.scalars(
                select(KnowledgeRelation.id).where(
                    KnowledgeRelation.user_id == user_id,
                    KnowledgeRelation.kb_id == kb_id,
                    ~exists().where(KnowledgeEvidence.relation_id == KnowledgeRelation.id),
                )
            )
        )
        if orphan_relation_ids:
            await self.session.execute(
                delete(KnowledgeRelation).where(
                    KnowledgeRelation.id.in_(orphan_relation_ids)
                )
            )
            await self.session.flush()

        orphan_entity_ids = list(
            await self.session.scalars(
                select(KnowledgeEntity.id).where(
                    KnowledgeEntity.user_id == user_id,
                    KnowledgeEntity.kb_id == kb_id,
                    ~exists().where(KnowledgeEvidence.entity_id == KnowledgeEntity.id),
                    ~exists().where(
                        or_(
                            KnowledgeRelation.source_entity_id == KnowledgeEntity.id,
                            KnowledgeRelation.target_entity_id == KnowledgeEntity.id,
                        )
                    ),
                )
            )
        )
        if orphan_entity_ids:
            await self.session.execute(
                delete(ReviewTask).where(ReviewTask.entity_id.in_(orphan_entity_ids))
            )
            await self.session.execute(
                delete(KnowledgeEntity).where(KnowledgeEntity.id.in_(orphan_entity_ids))
            )

    def _remove_storage_files(self, storage_keys: list[str]) -> int:
        root = Path(self.settings.file_storage_path).resolve()
        removed = 0
        for storage_key in storage_keys:
            path = Path(storage_key).resolve()
            if root not in path.parents:
                continue
            if path.exists():
                path.unlink()
                removed += 1
        return removed
