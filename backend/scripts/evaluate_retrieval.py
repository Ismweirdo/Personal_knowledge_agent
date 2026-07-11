import argparse
import asyncio
from pathlib import Path

from app.evaluation.runner import evaluate_retrieval, load_cases, report_json
from app.infrastructure.config import get_settings
from app.infrastructure.database import SessionFactory
from app.infrastructure.embedding import EmbeddingClient
from app.retrieval.service import RetrievalService


async def run(dataset: Path, user_id: str, kb_id: str, top_k: int) -> None:
    settings = get_settings()
    embedding = EmbeddingClient.from_settings(settings)
    async with SessionFactory() as session:
        retrieval = RetrievalService(session, embedding)

        async def search(question: str):
            return await retrieval.search(user_id, kb_id, question, limit=top_k)

        report = await evaluate_retrieval(load_cases(dataset), search)
    print(report_json(report))


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate retrieval against a fixed JSONL set")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--user-id", required=True, help="Administrator knowledge owner ID")
    parser.add_argument("--knowledge-base-id", required=True)
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()
    asyncio.run(run(args.dataset, args.user_id, args.knowledge_base_id, args.top_k))


if __name__ == "__main__":
    main()
