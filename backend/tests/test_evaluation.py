from pathlib import Path

import pytest

from app.evaluation.runner import EvaluationCase, evaluate_retrieval, load_cases, report_json
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
    assert report.answerable_cases == 10
    assert report.unanswerable_cases == 2
    assert report.gold_labeled_cases == 0
    assert report.recall_at_k is None
    assert report.answerable_hit_rate == 1.0
    assert report.unanswerable_empty_rate == 1.0
    assert report.overall_case_success_rate == 1.0
    assert '"recall_at_k": null' in report_json(report)


@pytest.mark.asyncio
async def test_document_recall_uses_gold_sources_not_all_cases() -> None:
    cases = [
        EvaluationCase("a", "a", True, ["A"], ["doc-a", "doc-b"]),
        EvaluationCase("b", "b", True, ["B"], ["doc-c"]),
        EvaluationCase("unknown", "unknown", False, []),
    ]

    async def search(question: str) -> list[RetrievalResult]:
        if question == "a":
            return [RetrievalResult("a", "A", 1.0, {"source_name": "doc-a"})]
        if question == "b":
            return [RetrievalResult("b", "B", 1.0, {"source_name": "doc-c"})]
        return [RetrievalResult("x", "unrelated", 1.0, {"source_name": "doc-x"})]

    report = await evaluate_retrieval(cases, search)

    assert report.gold_labeled_cases == 2
    assert report.recall_at_k == 0.75
    assert report.answerable_hit_rate == 1.0
    assert report.unanswerable_empty_rate == 0.0
    assert report.overall_case_success_rate == 2 / 3
