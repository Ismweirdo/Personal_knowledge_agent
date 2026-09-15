"""Index six labeled public documents in an isolated database and evaluate source Recall@K.

Use an empty evaluation database. The script creates evaluation users and sources and
does not delete existing data; it must never target a production knowledge database.
"""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from uuid import uuid4

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

PUBLIC_FILES = (
    "docs/项目1技术文档.md",
    "docs/项目1设计文档.md",
    "docs/上线运行手册.md",
    "docs/持续学习与知识图谱设计.md",
    "docs/开发文档.md",
    "docs/管理员使用说明.md",
)


async def run(repository: Path, dataset: Path, top_ks: list[int], output: Path | None) -> None:
    settings = get_settings()
    cases = load_cases(dataset)
    expected_sources = {name for case in cases for name in case.gold_source_names or []}
    source_files = [repository / relative for relative in PUBLIC_FILES]
    missing = [str(path) for path in source_files if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Public source files are missing: {missing}")
    unknown_labels = expected_sources - {path.name for path in source_files}
    if unknown_labels:
        raise ValueError(f"Gold sources are not in the public corpus: {sorted(unknown_labels)}")

    async with SessionFactory() as session:
        suffix = uuid4().hex
        owner = User(
            email=f"source-recall-{suffix}@example.invalid", password_hash="unused", role="ADMIN"
        )
        session.add(owner)
        await session.flush()
        knowledge_base = KnowledgeBase(
            user_id=owner.id,
            name=f"public-source-recall-{suffix[:8]}",
            is_published=True,
            embedding_model=settings.embedding_model,
        )
        session.add(knowledge_base)
        await session.flush()

        source_versions: list[tuple[str, str]] = []
        for relative, path in zip(PUBLIC_FILES, source_files, strict=True):
            content = path.read_text(encoding="utf-8")
            chunks = chunk_pages([ParsedPage(content)])
            source = KnowledgeSource(
                user_id=owner.id,
                kb_id=knowledge_base.id,
                source_type="FILE",
                display_name=path.name,
                source_locator=relative,
                status="PROCESSING",
            )
            session.add(source)
            await session.flush()
            version = SourceVersion(
                source_id=source.id,
                user_id=owner.id,
                kb_id=knowledge_base.id,
                content_hash=hashlib.sha256(content.encode()).hexdigest(),
                storage_key=f"evaluation/public-source-recall/{relative}",
                mime_type="text/markdown",
                size_bytes=len(content.encode()),
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
                        chunk_metadata={
                            key: value for key, value in chunk.items() if key != "content"
                        },
                    )
                    for index, chunk in enumerate(chunks)
                ]
            )
            source_versions.append((source.id, version.id))
        await session.commit()

        indexing = VectorIndexingService(session, EmbeddingClient.from_settings(settings))
        indexed = 0
        for source_id, version_id in source_versions:
            indexed += await indexing.index(owner.id, source_id, version_id)

        retrieval = RetrievalService(session, EmbeddingClient.from_settings(settings))
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
            "corpus": list(PUBLIC_FILES),
            "source_count": len(source_files),
            "chunk_count": indexed,
            "dataset": str(dataset),
            "embedding_model": settings.embedding_model,
            "top_k_reports": reports,
        }
        rendered = json.dumps(report, ensure_ascii=False, indent=2)
        if output:
            await asyncio.to_thread(output.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(output.write_text, rendered + "\n", encoding="utf-8")
        print(rendered)
    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate gold-source Recall@K")
    parser.add_argument("--repository", type=Path, default=Path(".."))
    parser.add_argument(
        "--dataset", type=Path, default=Path("evaluation/datasets/public_source_gold.jsonl")
    )
    parser.add_argument("--top-k", type=int, nargs="+", default=[1, 4, 10])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    asyncio.run(run(args.repository.resolve(), args.dataset, args.top_k, args.output))


if __name__ == "__main__":
    main()
