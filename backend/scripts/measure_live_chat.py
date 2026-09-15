"""Measure real public-site SSE answers and cited-source recall without printing secrets.

LIVE_EVAL_VISITOR_KEY is required. Optional LIVE_EVAL_ADMIN_USERNAME and
LIVE_EVAL_ADMIN_PASSWORD enable a read-only corpus count. Only conversations
created by this script are removed after their result has been saved.
"""

import argparse
import asyncio
import json
import os
import statistics
from pathlib import Path
from time import monotonic

import httpx

from app.conversation.service import NO_EVIDENCE_ANSWER
from app.evaluation.runner import EvaluationCase, load_cases


def percentile(values: list[float], rank: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * rank + 0.5)))
    return round(ordered[index], 2)


def latency_summary(values: list[float]) -> dict[str, float | int | None]:
    return {
        "samples": len(values),
        "p50_ms": round(statistics.median(values), 2) if values else None,
        "p95_ms": percentile(values, 0.95),
        "p99_ms": percentile(values, 0.99),
    }


async def visitor_session(client: httpx.AsyncClient, kb_id: str, title: str) -> tuple[str, str]:
    access_key = os.environ.get("LIVE_EVAL_VISITOR_KEY")
    if not access_key:
        raise ValueError("LIVE_EVAL_VISITOR_KEY is required")
    response = await client.post("/api/v1/auth/access", json={"access_key": access_key})
    response.raise_for_status()
    token = response.json()["access_token"]
    response = await client.post(
        "/api/v1/conversations",
        headers={"Authorization": f"Bearer {token}"},
        json={"knowledge_base_id": kb_id, "title": title},
    )
    response.raise_for_status()
    return token, response.json()["id"]


async def send_chat(
    client: httpx.AsyncClient, token: str, conversation_id: str, case: EvaluationCase
) -> dict[str, object]:
    headers = {"Authorization": f"Bearer {token}"}
    started = monotonic()
    first_delta: float | None = None
    finished: float | None = None
    event_name = ""
    data_lines: list[str] = []
    citations: list[dict[str, object]] = []
    answer: list[str] = []
    error_code: str | None = None
    url = f"/api/v1/conversations/{conversation_id}/messages:stream"
    async with client.stream(
        "POST", url, headers=headers, json={"content": case.question}
    ) as response:
        if response.status_code != 200:
            return {
                "id": case.id,
                "status_code": response.status_code,
                "error_code": "HTTP_ERROR",
                "ttft_ms": None,
                "total_ms": None,
                "citations": [],
                "answer": "",
            }
        async for line in response.aiter_lines():
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())
            elif not line and event_name:
                payload = json.loads("\n".join(data_lines)) if data_lines else None
                if event_name == "citation" and isinstance(payload, list):
                    citations = payload
                elif event_name == "delta" and isinstance(payload, dict):
                    delta = str(payload.get("text") or "")
                    if delta:
                        if first_delta is None:
                            first_delta = monotonic()
                        answer.append(delta)
                elif event_name == "done":
                    finished = monotonic()
                elif event_name == "error":
                    error_code = str(
                        payload.get("code") if isinstance(payload, dict) else "SSE_ERROR"
                    )
                event_name = ""
                data_lines = []
    source_names = [
        str(citation.get("metadata", {}).get("source_name", ""))
        for citation in citations
        if isinstance(citation, dict) and isinstance(citation.get("metadata"), dict)
    ]
    gold = set(case.gold_source_names or [])
    text = "".join(answer)
    return {
        "id": case.id,
        "status_code": 200,
        "error_code": error_code if error_code or finished is None else None,
        "ttft_ms": round((first_delta - started) * 1000, 2) if first_delta else None,
        "total_ms": round((finished - started) * 1000, 2) if finished else None,
        "citations": source_names,
        "gold_source_recall_at_4": len(gold & set(source_names)) / len(gold) if gold else None,
        "answer_term_coverage": all(
            term.casefold() in text.casefold() for term in case.expected_terms
        )
        if case.answerable
        else None,
        "exact_no_evidence_refusal": text == NO_EVIDENCE_ANSWER and not citations
        if not case.answerable
        else None,
        "answer": text,
    }


async def remove_conversation(client: httpx.AsyncClient, token: str, conversation_id: str) -> None:
    response = await client.delete(
        f"/api/v1/conversations/{conversation_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()


async def run(args: argparse.Namespace) -> None:
    cases = load_cases(args.dataset)
    timeout = httpx.Timeout(180, connect=20)
    async with httpx.AsyncClient(base_url=args.base_url, timeout=timeout) as client:
        health = await client.get("/health")
        ready = await client.get("/health/ready")
        agent = await client.get("/api/v1/agent")
        agent.raise_for_status()
        kb_id = agent.json()["knowledgeBaseId"]
        if not kb_id:
            raise ValueError("Public knowledge base is not published")

        corpus: dict[str, object] | None = None
        username = os.environ.get("LIVE_EVAL_ADMIN_USERNAME")
        password = os.environ.get("LIVE_EVAL_ADMIN_PASSWORD")
        if username and password:
            login = await client.post(
                "/api/v1/auth/admin/login", json={"username": username, "password": password}
            )
            login.raise_for_status()
            sources = await client.get(
                f"/api/v1/knowledge-bases/{kb_id}/sources",
                headers={"Authorization": f"Bearer {login.json()['access_token']}"},
            )
            sources.raise_for_status()
            items = sources.json()
            corpus = {
                "sources": len(items),
                "ready_sources": sum(item["status"] == "READY" for item in items),
                "chunks": sum(item["chunk_count"] or 0 for item in items),
                "source_types": sorted({item["source_type"] for item in items}),
            }

        baseline_token, baseline_conversation = await visitor_session(
            client, kb_id, "evaluation labeled questions"
        )
        try:
            baseline = [
                await send_chat(client, baseline_token, baseline_conversation, case)
                for case in cases
            ]
        finally:
            await remove_conversation(client, baseline_token, baseline_conversation)

        benchmark_case = EvaluationCase(
            id="benchmark-profile",
            question=args.benchmark_question,
            answerable=True,
            expected_terms=[],
        )
        benchmark_token, benchmark_conversation = await visitor_session(
            client, kb_id, "evaluation sequential latency"
        )
        try:
            sequential = [
                await send_chat(client, benchmark_token, benchmark_conversation, benchmark_case)
                for _ in range(args.benchmark_requests)
            ]
        finally:
            await remove_conversation(client, benchmark_token, benchmark_conversation)

        concurrent_token, concurrent_conversation = await visitor_session(
            client, kb_id, "evaluation concurrent latency"
        )
        semaphore = asyncio.Semaphore(args.concurrency)
        try:

            async def request() -> dict[str, object]:
                async with semaphore:
                    return await send_chat(
                        client, concurrent_token, concurrent_conversation, benchmark_case
                    )

            started = monotonic()
            concurrent = await asyncio.gather(*(request() for _ in range(args.concurrent_requests)))
            elapsed = monotonic() - started
        finally:
            await remove_conversation(client, concurrent_token, concurrent_conversation)

    def success(item: dict[str, object]) -> bool:
        return item["error_code"] is None and item["total_ms"] is not None

    gold_recalls = [
        float(item["gold_source_recall_at_4"])
        for item in baseline
        if item.get("gold_source_recall_at_4") is not None
    ]
    answerable = [item for item in baseline if item.get("answer_term_coverage") is not None]
    unknown = [item for item in baseline if item.get("exact_no_evidence_refusal") is not None]
    report = {
        "site": args.base_url,
        "health_status": health.status_code,
        "ready_status": ready.status_code,
        "ready_checks": ready.json().get("checks"),
        "corpus": corpus,
        "labeled_cases": len(cases),
        "baseline": {
            "successes": sum(success(item) for item in baseline),
            "gold_source_recall_at_4": round(statistics.mean(gold_recalls), 4)
            if gold_recalls
            else None,
            "answer_term_coverage": round(
                sum(bool(item["answer_term_coverage"]) for item in answerable) / len(answerable), 4
            )
            if answerable
            else None,
            "exact_no_evidence_refusal_rate": round(
                sum(bool(item["exact_no_evidence_refusal"]) for item in unknown) / len(unknown), 4
            )
            if unknown
            else None,
            "ttft": latency_summary([float(item["ttft_ms"]) for item in baseline if success(item)]),
            "total": latency_summary(
                [float(item["total_ms"]) for item in baseline if success(item)]
            ),
        },
        "sequential": {
            "requests": len(sequential),
            "successes": sum(success(item) for item in sequential),
            "ttft": latency_summary(
                [float(item["ttft_ms"]) for item in sequential if success(item)]
            ),
            "total": latency_summary(
                [float(item["total_ms"]) for item in sequential if success(item)]
            ),
        },
        "concurrent": {
            "requests": len(concurrent),
            "concurrency": args.concurrency,
            "successes": sum(success(item) for item in concurrent),
            "throughput_rps": round(len(concurrent) / elapsed, 3),
            "total": latency_summary(
                [float(item["total_ms"]) for item in concurrent if success(item)]
            ),
        },
        "case_results": baseline,
        "sequential_results": sequential,
        "concurrent_results": concurrent,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {key: value for key, value in report.items() if not key.endswith("results")},
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure public-site SSE responses")
    parser.add_argument("--base-url", default="https://laylight.asia")
    parser.add_argument(
        "--dataset", type=Path, default=Path("evaluation/datasets/public_source_gold.jsonl")
    )
    parser.add_argument("--benchmark-question", default="你做过哪些项目？")
    parser.add_argument("--benchmark-requests", type=int, default=10)
    parser.add_argument("--concurrent-requests", type=int, default=6)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
