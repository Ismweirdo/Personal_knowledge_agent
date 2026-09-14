"""Rebuild all PARSED source versions with the configured embedding provider."""

import asyncio

from sqlalchemy import select

from app.infrastructure.config import get_settings
from app.infrastructure.database import SessionFactory, engine
from app.infrastructure.embedding import EmbeddingClient
from app.infrastructure.models import SourceVersion
from app.ingestion.indexing import VectorIndexingService


async def run() -> None:
    settings = get_settings()
    embedding = EmbeddingClient.from_settings(settings)
    async with SessionFactory() as session:
        versions = list(
            await session.scalars(
                select(SourceVersion)
                .where(SourceVersion.status == "PARSED")
                .order_by(SourceVersion.created_at)
            )
        )
        indexed = 0
        for version in versions:
            indexed += await VectorIndexingService(session, embedding).index(
                version.user_id, version.source_id, version.id
            )
        print(f"reindexed_versions={len(versions)} reindexed_chunks={indexed}")
    if hasattr(embedding.client, "aclose"):
        await embedding.client.aclose()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
