from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.embedding import EmbeddingClient
from app.infrastructure.models import DocumentChunk, KnowledgeSource, SourceVersion


@dataclass(frozen=True)
class RetrievalResult:
    chunk_id: str
    content: str
    score: float
    metadata: dict[str, object] | None


class RetrievalService:
    def __init__(self, session: AsyncSession, embedding_client: EmbeddingClient) -> None:
        self.session = session
        self.embedding_client = embedding_client

    async def search(
        self,
        user_id: str,
        knowledge_base_id: str,
        query: str,
        *,
        limit: int = 10,
    ) -> list[RetrievalResult]:
        query_vector = (await self.embedding_client.embed([query]))[0]
        distance = DocumentChunk.embedding.cosine_distance(query_vector)
        rows = await self.session.execute(
            select(DocumentChunk, distance.label("distance"))
            .join(SourceVersion, SourceVersion.id == DocumentChunk.source_version_id)
            .join(
                KnowledgeSource,
                (KnowledgeSource.id == SourceVersion.source_id)
                & (KnowledgeSource.active_version_id == SourceVersion.id),
            )
            .where(
                DocumentChunk.user_id == user_id,
                DocumentChunk.kb_id == knowledge_base_id,
                DocumentChunk.embedding.is_not(None),
                SourceVersion.status == "READY",
                KnowledgeSource.status == "READY",
            )
            .order_by(distance)
            .limit(limit)
        )
        return [
            RetrievalResult(
                chunk_id=chunk.id,
                content=chunk.content,
                score=max(0.0, 1.0 - float(value)),
                metadata=chunk.chunk_metadata,
            )
            for chunk, value in rows
        ]
