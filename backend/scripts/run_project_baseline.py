"""Build an isolated public-project corpus and measure retrieval quality.

This script is intentionally for an empty, disposable evaluation database.  It
imports only the repository's Git snapshot, calls the configured embedding
provider, and prints Recall@K plus answerable/unanswerable retrieval metrics.
"""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from app.connectors.git import snapshot_repository
from app.evaluation.runner import evaluate_retrieval, load_cases
from app.infrastructure.config import get_settings
from app.infrastructure.database import SessionFactory, engine
from app.infrastructure.embedding import EmbeddingClient
from app.infrastructure.models import (
    DocumentChunk,
    KnowledgeBase,
    KnowledgeSource,
    SourceVersion,
    User,
)
from app.ingestion.indexing import VectorIndexingService
from app.ingestion.parser import ParsedPage, chunk_pages
from app.retrieval.service import RetrievalService


async def run(
    repository: Path, dataset: Path, top_ks: list[int], output: Path | None = None
) -> None:
    snapshot = snapshot_repository(str(repository), str(repository))
    chunks = chunk_pages([ParsedPage(snapshot.text)])
    settings = get_settings()
    async with SessionFactory() as session:
        suffix = uuid4().hex
        owner = User(
            email=f"evaluation-{suffix}@example.invalid", password_hash="unused", role="ADMIN"
        )
        session.add(owner)
        await session.flush()
        knowledge_base = KnowledgeBase(
            user_id=owner.id,
            name=f"project-baseline-{suffix[:8]}",
            is_published=True,
            embedding_model=settings.embedding_model,
        )
        session.add(knowledge_base)
        await session.flush()
        source = KnowledgeSource(
            user_id=owner.id,
            kb_id=knowledge_base.id,
            source_type="GIT",
            display_name="项目1公开文档",
            source_locator=snapshot.locator,
            status="PROCESSING",
        )
        session.add(source)
        await session.flush()
        version = SourceVersion(
            source_id=source.id,
            user_id=owner.id,
            kb_id=knowledge_base.id,
            content_hash=hashlib.sha256(snapshot.text.encode()).hexdigest(),
            storage_key="evaluation/project-baseline",
            mime_type="text/markdown",
            size_bytes=len(snapshot.text.encode()),
            revision=snapshot.revision,
            status="PARSED",
        )
        session.add(version)
        await session.flush()
        session.add_all(
            [
                DocumentChunk(
                    source_version_id=version.id,
                    user_id=owner.id,
                    kb_id=knowledge_base.id,
                    content=str(chunk["content"]),
                    chunk_index=index,
                    token_count=max(1, len(str(chunk["content"])) // 4),
                    chunk_metadata={key: value for key, value in chunk.items() if key != "content"},
                )
                for index, chunk in enumerate(chunks)
            ]
        )
        await session.commit()
        indexed = await VectorIndexingService(
            session, EmbeddingClient.from_settings(settings)
        ).index(owner.id, source.id, version.id)
        retrieval = RetrievalService(session, EmbeddingClient.from_settings(settings))
        cases = load_cases(dataset)
        reports = {}
        for top_k in top_ks:
            reports[str(top_k)] = vars(
                await evaluate_retrieval(
                    cases,
                    lambda question, top_k=top_k: retrieval.search(
                        owner.id, knowledge_base.id, question, limit=top_k
                    ),
                )
            )
        report = {
            "dataset": str(dataset),
            "files": snapshot.files,
            "chunks": indexed,
            "top_k_reports": reports,
        }
        rendered = json.dumps(report, ensure_ascii=False, indent=2)
        if output:
            await asyncio.to_thread(output.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(output.write_text, rendered + "\n", encoding="utf-8")
        print(rendered)
    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the public project-1 Git snapshot")
    parser.add_argument("--repository", type=Path, default=Path(".."))
    parser.add_argument(
        "--dataset", type=Path, default=Path("evaluation/datasets/project_baseline.jsonl")
    )
    parser.add_argument("--top-k", type=int, nargs="+", default=[1, 4, 10])
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    args = parser.parse_args()
    asyncio.run(run(args.repository.resolve(), args.dataset, args.top_k, args.output))


if __name__ == "__main__":
    main()
