import json
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from app.retrieval.service import RetrievalResult


@dataclass(frozen=True)
class EvaluationCase:
    id: str
    question: str
    answerable: bool
    expected_terms: list[str]
    gold_source_names: list[str] | None = None


@dataclass(frozen=True)
class EvaluationReport:
    cases: int
    answerable_cases: int
    unanswerable_cases: int
    gold_labeled_cases: int
    recall_at_k: float | None
    answerable_hit_rate: float
    unanswerable_empty_rate: float
    overall_case_success_rate: float


def load_cases(path: Path) -> list[EvaluationCase]:
    return [
        EvaluationCase(**json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


async def evaluate_retrieval(
    cases: list[EvaluationCase],
    search: Callable[[str], Awaitable[list[RetrievalResult]]],
) -> EvaluationReport:
    answerable_total = answerable_hits = unanswerable_total = unanswerable_hits = 0
    gold_recalls: list[float] = []
    for case in cases:
        results = await search(case.question)
        combined = " ".join(result.content.casefold() for result in results)
        if case.answerable:
            answerable_total += 1
            if all(term.casefold() in combined for term in case.expected_terms):
                answerable_hits += 1
            if case.gold_source_names:
                gold = set(case.gold_source_names)
                retrieved = {
                    result.metadata.get("source_name")
                    for result in results
                    if result.metadata and isinstance(result.metadata.get("source_name"), str)
                }
                gold_recalls.append(len(gold & retrieved) / len(gold))
        else:
            unanswerable_total += 1
            if not results:
                unanswerable_hits += 1
    answerable_rate = answerable_hits / answerable_total if answerable_total else 0.0
    unanswerable_rate = unanswerable_hits / unanswerable_total if unanswerable_total else 0.0
    total_hits = answerable_hits + unanswerable_hits
    return EvaluationReport(
        cases=len(cases),
        answerable_cases=answerable_total,
        unanswerable_cases=unanswerable_total,
        gold_labeled_cases=len(gold_recalls),
        recall_at_k=sum(gold_recalls) / len(gold_recalls) if gold_recalls else None,
        answerable_hit_rate=answerable_rate,
        unanswerable_empty_rate=unanswerable_rate,
        overall_case_success_rate=total_hits / len(cases) if cases else 0.0,
    )


def report_json(report: EvaluationReport) -> str:
    return json.dumps(asdict(report), ensure_ascii=False, indent=2)
