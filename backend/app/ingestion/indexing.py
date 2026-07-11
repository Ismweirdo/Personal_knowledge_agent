from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.embedding import EmbeddingClient
from app.infrastructure.errors import ApplicationError
from app.infrastructure.models import DocumentChunk, KnowledgeSource, SourceVersion


class VectorIndexingService:
    def __init__(self, session: AsyncSession, embedding_client: EmbeddingClient) -> None:
        self.session = session
        self.embedding_client = embedding_client

    async def index(
        self, user_id: str, source_id: str, source_version_id: str | None = None
    ) -> int:
        source = await self.session.scalar(
            select(KnowledgeSource).where(
                KnowledgeSource.id == source_id,
                KnowledgeSource.user_id == user_id,
            )
        )
        if source is None:
            raise ApplicationError(
                "SOURCE_NOT_FOUND", "Knowledge source not found", status_code=404
            )
        version = await self.session.scalar(
            select(SourceVersion)
            .where(
                SourceVersion.source_id == source.id,
                SourceVersion.user_id == user_id,
                SourceVersion.status.in_(("PARSED", "INDEXING")),
                *(
                    (SourceVersion.id == source_version_id,)
                    if source_version_id is not None
                    else ()
                ),
            )
            .order_by(SourceVersion.created_at.desc())
        )
        if version is None:
            raise ApplicationError(
                "SOURCE_NOT_INDEXABLE", "Source has no parsed version", status_code=409
            )
        chunks = list(
            await self.session.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.source_version_id == version.id)
                .order_by(DocumentChunk.chunk_index)
            )
        )
        version.status = "INDEXING"
        await self.session.flush()
        try:
            for start in range(0, len(chunks), 32):
                batch = chunks[start : start + 32]
                vectors = await self.embedding_client.embed([chunk.content for chunk in batch])
                if len(vectors) != len(batch):
                    raise ApplicationError(
                        "EMBEDDING_COUNT_MISMATCH",
                        "Embedding provider returned an invalid result count",
                        status_code=502,
                    )
                for chunk, vector in zip(batch, vectors, strict=True):
                    chunk.embedding = vector
            version.status = "READY"
            source.active_version_id = version.id
            source.status = "READY"
            await self.session.commit()
            return len(chunks)
        except Exception:
            await self.session.rollback()
            raise
