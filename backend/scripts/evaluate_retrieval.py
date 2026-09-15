import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy import func, select

from app.evaluation.runner import evaluate_retrieval, load_cases
from app.infrastructure.config import get_settings
from app.infrastructure.database import SessionFactory
from app.infrastructure.embedding import EmbeddingClient
from app.infrastructure.models import DocumentChunk, KnowledgeBase, KnowledgeSource
from app.retrieval.service import RetrievalService


async def run(
    dataset: Path, user_id: str | None, kb_id: str | None, top_ks: list[int], published: bool
) -> None:
    settings = get_settings()
    embedding = EmbeddingClient.from_settings(settings)
    async with SessionFactory() as session:
        if published:
            knowledge_base = await session.scalar(
                select(KnowledgeBase).where(KnowledgeBase.is_published.is_(True))
            )
            if knowledge_base is None:
                raise ValueError("No published knowledge base is available")
            user_id, kb_id = knowledge_base.user_id, knowledge_base.id
        if not user_id or not kb_id:
            raise ValueError("Provide --published or both --user-id and --knowledge-base-id")
        active_sources = list(
            await session.scalars(
                select(KnowledgeSource).where(
                    KnowledgeSource.user_id == user_id,
                    KnowledgeSource.kb_id == kb_id,
                    KnowledgeSource.status == "READY",
                    KnowledgeSource.active_version_id.is_not(None),
                )
            )
        )
        active_versions = [source.active_version_id for source in active_sources]
        chunk_count = (
            await session.scalar(
                select(func.count(DocumentChunk.id)).where(
                    DocumentChunk.source_version_id.in_(active_versions)
                )
            )
            if active_versions
            else 0
        )
        retrieval = RetrievalService(session, embedding)
        cases = load_cases(dataset)
        labels = {name for case in cases for name in case.gold_source_names or []}
        absent = labels - {source.display_name for source in active_sources}
        if absent:
            raise ValueError(f"Gold sources are not active: {sorted(absent)}")
        reports = {}
        for top_k in top_ks:
            report = await evaluate_retrieval(
                cases,
                lambda question, top_k=top_k: retrieval.search(
                    user_id, kb_id, question, limit=top_k
                ),
            )
            reports[str(top_k)] = vars(report)
    print(
        json.dumps(
            {
                "dataset": str(dataset),
                "knowledge_base_id": kb_id,
                "embedding_model": settings.embedding_model,
                "active_source_count": len(active_sources),
                "active_chunk_count": chunk_count,
                "top_k_reports": reports,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate retrieval against a fixed JSONL set")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--published", action="store_true", help="Use the published knowledge base")
    parser.add_argument("--user-id", help="Administrator knowledge owner ID")
    parser.add_argument("--knowledge-base-id")
    parser.add_argument("--top-k", type=int, nargs="+", default=[1, 4, 10])
    args = parser.parse_args()
    asyncio.run(run(args.dataset, args.user_id, args.knowledge_base_id, args.top_k, args.published))


if __name__ == "__main__":
    main()
