from pathlib import Path

import pytest

from app.evaluation.runner import evaluate_retrieval, load_cases, report_json
from app.retrieval.service import RetrievalResult


def result(content: str) -> RetrievalResult:
    return RetrievalResult(chunk_id="test", content=content, score=1.0, metadata=None)


@pytest.mark.asyncio
async def test_retrieval_evaluation_metrics() -> None:
    cases = load_cases(Path("evaluation/datasets/project_baseline.jsonl"))

    async def search(question: str) -> list[RetrievalResult]:
        if "天气" in question or "股票" in question:
            return []
        content = (
            "FastAPI 模块化单体 PostgreSQL pgvector DeepSeek SSE 证据 Chunk "
            "管理员 普通用户 ETag Last-Modified commit SHA SM-2 禁止"
        )
        return [result(content)]

    report = await evaluate_retrieval(cases, search)

    assert report.cases == 12
    assert report.recall_at_k == 1.0
    assert report.answerable_hit_rate == 1.0
    assert report.unanswerable_recall == 1.0
    assert '"recall_at_k": 1.0' in report_json(report)
