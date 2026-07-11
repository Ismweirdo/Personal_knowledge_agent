import argparse
import asyncio
import statistics
from time import monotonic

import httpx


async def run(base_url: str, requests: int, concurrency: int) -> None:
    semaphore = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    failures = 0

    async with httpx.AsyncClient(base_url=base_url, timeout=15) as client:

        async def request() -> None:
            nonlocal failures
            async with semaphore:
                started = monotonic()
                try:
                    response = await client.get("/health")
                    if response.status_code != 200:
                        failures += 1
                except httpx.HTTPError:
                    failures += 1
                finally:
                    latencies.append((monotonic() - started) * 1000)

        started = monotonic()
        await asyncio.gather(*(request() for _ in range(requests)))
        elapsed = monotonic() - started

    ordered = sorted(latencies)

    def percentile(value: float) -> float:
        return ordered[min(len(ordered) - 1, int(len(ordered) * value))]

    print(f"requests={requests} concurrency={concurrency} failures={failures}")
    print(f"throughput_rps={requests / elapsed:.2f}")
    print(f"latency_ms_p50={statistics.median(ordered):.2f}")
    print(f"latency_ms_p95={percentile(0.95):.2f} latency_ms_p99={percentile(0.99):.2f}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=20)
    args = parser.parse_args()
    asyncio.run(run(args.base_url, args.requests, args.concurrency))


if __name__ == "__main__":
    main()
