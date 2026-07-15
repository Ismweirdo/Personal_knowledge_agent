import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.config import Settings, get_settings
from app.infrastructure.database import SessionFactory
from app.infrastructure.embedding import EmbeddingClient
from app.infrastructure.errors import ApplicationError
from app.infrastructure.llm import ChatModelClient
from app.infrastructure.models import DocumentChunk, IngestionTask, SourceVersion
from app.ingestion.indexing import VectorIndexingService
from app.knowledge_graph.extraction import GraphExtractionService

logger = logging.getLogger(__name__)

TRANSIENT_CODES = {
    "EMBEDDING_RATE_LIMITED",
    "EMBEDDING_UNAVAILABLE",
    "LLM_RATE_LIMITED",
    "LLM_UNAVAILABLE",
}


async def enqueue_task(
    session: AsyncSession,
    user_id: str,
    source_id: str,
    source_version_id: str,
) -> IngestionTask:
    existing = await session.scalar(
        select(IngestionTask).where(
            IngestionTask.source_version_id == source_version_id,
            IngestionTask.status.in_(("PENDING", "RUNNING", "RETRY_WAIT", "SUCCEEDED")),
        )
    )
    if existing is not None:
        return existing
    task = IngestionTask(
        user_id=user_id,
        source_id=source_id,
        source_version_id=source_version_id,
    )
    session.add(task)
    await session.flush()
    return task


class IngestionWorker:
    def __init__(
        self,
        settings: Settings,
        *,
        session_factory: async_sessionmaker[AsyncSession] = SessionFactory,
        embedding: EmbeddingClient | None = None,
        chat: ChatModelClient | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.embedding = embedding or EmbeddingClient.from_settings(settings)
        self.chat = chat or ChatModelClient.from_settings(settings)

    async def run_forever(self) -> None:
        while True:
            processed = await self.run_once()
            if not processed:
                await asyncio.sleep(self.settings.background_worker_poll_seconds)

    async def run_once(self) -> bool:
        async with self.session_factory() as session:
            task = await self._claim(session)
            if task is None:
                return False
            task_id = task.id
            try:
                version = await session.get(SourceVersion, task.source_version_id)
                if version is None:
                    raise ApplicationError(
                        "SOURCE_VERSION_NOT_FOUND",
                        "Source version not found",
                        status_code=404,
                    )
                if version.status != "READY":
                    await VectorIndexingService(session, self.embedding).index(
                        task.user_id, task.source_id, task.source_version_id
                    )
                task.progress = 70
                await session.commit()
                graph_warning = await self._extract_graph_candidates(session, task)
                task = await session.get(IngestionTask, task_id)
                if task is None:
                    raise ApplicationError(
                        "INGESTION_TASK_NOT_FOUND",
                        "Ingestion task not found",
                        status_code=404,
                    )
                task.status = "SUCCEEDED"
                task.progress = 100
                task.finished_at = datetime.now(UTC)
                task.error_code = graph_warning
                task.error_message = (
                    "Vector indexing completed; graph extraction was skipped or partially failed"
                    if graph_warning
                    else None
                )
                await session.commit()
            except Exception as exc:
                await session.rollback()
                task = await session.get(IngestionTask, task_id)
                await self._fail(session, task, exc)
            return True

    async def _extract_graph_candidates(
        self, session: AsyncSession, task: IngestionTask
    ) -> str | None:
        task_id = task.id
        user_id = task.user_id
        source_version_id = task.source_version_id
        if not self.settings.graph_extraction_enabled:
            return "GRAPH_EXTRACTION_SKIPPED"
        max_chunks = self.settings.graph_extraction_max_chunks_per_task
        if max_chunks <= 0:
            return "GRAPH_EXTRACTION_SKIPPED"
        chunks = list(
            await session.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.source_version_id == source_version_id)
                .order_by(DocumentChunk.chunk_index)
                .limit(max_chunks + 1)
            )
        )
        if not chunks:
            return None
        selected_chunks = chunks[:max_chunks]
        total_selected = len(selected_chunks)
        extractor = GraphExtractionService(session, self.chat)
        warning: str | None = "GRAPH_EXTRACTION_PARTIAL" if len(chunks) > max_chunks else None
        for index, chunk in enumerate(selected_chunks, 1):
            chunk_id = chunk.id
            try:
                await extractor.extract_chunk(user_id, chunk_id)
            except Exception as exc:  # noqa: BLE001 - graph extraction must not block indexing
                await session.rollback()
                warning = (
                    exc.code
                    if isinstance(exc, ApplicationError)
                    else "GRAPH_EXTRACTION_FAILED"
                )
                logger.warning(
                    "graph_extraction_failed taskId=%s chunkId=%s errorCode=%s",
                    task_id,
                    chunk_id,
                    warning,
                )
                break
            task.progress = 70 + round(index / total_selected * 25)
            await session.commit()
        return warning

    async def _claim(self, session: AsyncSession) -> IngestionTask | None:
        now = datetime.now(UTC)
        stale_before = now - timedelta(seconds=self.settings.background_task_stale_seconds)
        task = await session.scalar(
            select(IngestionTask)
            .where(
                or_(
                    IngestionTask.status == "PENDING",
                    (IngestionTask.status == "RETRY_WAIT") & (IngestionTask.next_retry_at <= now),
                    (IngestionTask.status == "RUNNING")
                    & (IngestionTask.started_at <= stale_before),
                )
            )
            .order_by(IngestionTask.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if task is None:
            return None
        if task.status == "RUNNING":
            task.retry_count += 1
            task.error_code = "WORKER_LEASE_EXPIRED"
        task.status = "RUNNING"
        task.started_at = now
        await session.commit()
        return task

    async def _fail(self, session: AsyncSession, task: IngestionTask, exc: Exception) -> None:
        code = exc.code if isinstance(exc, ApplicationError) else "INGESTION_FAILED"
        task.retry_count += 1
        task.error_code = code
        task.error_message = str(exc)[:500]
        if code in TRANSIENT_CODES and task.retry_count <= task.max_retries:
            task.status = "RETRY_WAIT"
            task.next_retry_at = datetime.now(UTC) + timedelta(seconds=2**task.retry_count)
        else:
            task.status = "FAILED"
            task.finished_at = datetime.now(UTC)
        await session.commit()


def create_worker() -> IngestionWorker:
    return IngestionWorker(get_settings())
