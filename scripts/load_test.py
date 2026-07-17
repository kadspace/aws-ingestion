import argparse
import json
import statistics
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from urllib import error, request


def post_reading(url: str, sequence: int) -> tuple[int, float]:
    body = json.dumps(
        {
            "machine_id": f"load-test-{sequence % 10:02d}",
            "temperature_f": 80.0,
            "vibration_mm_s": 0.1,
            "pressure_psi": 55.0,
            "rpm": 1700,
        }
    ).encode("utf-8")
    api_request = request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    started = time.perf_counter()
    try:
        with request.urlopen(api_request, timeout=15) as response:
            status = response.status
    except error.HTTPError as http_error:
        status = http_error.code
    except Exception:
        status = 0

    return status, time.perf_counter() - started


def percentile(values: list[float], percent: float) -> float:
    ordered = sorted(values)
    index = round((len(ordered) - 1) * percent)
    return ordered[index]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send a bounded concurrent load test to POST /readings."
    )
    parser.add_argument("endpoint", help="API Gateway base URL or /readings URL")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument(
        "--allow-large-run",
        action="store_true",
        help="Allow more than 10,000 requests.",
    )
    args = parser.parse_args()

    if args.requests < 1 or args.concurrency < 1:
        parser.error("--requests and --concurrency must be positive")
    if args.requests > 10_000 and not args.allow_large_run:
        parser.error("more than 10,000 requests requires --allow-large-run")

    url = args.endpoint.rstrip("/")
    if not url.endswith("/readings"):
        url = f"{url}/readings"

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        results = list(
            executor.map(
                lambda sequence: post_reading(url, sequence),
                range(args.requests),
            )
        )
    elapsed = time.perf_counter() - started

    statuses = Counter(status for status, _ in results)
    latencies = [duration for _, duration in results]

    print(f"Target: {url}")
    print(f"Requests: {args.requests} in {elapsed:.2f}s ({args.requests / elapsed:.2f} RPS)")
    print(f"Statuses: {dict(sorted(statuses.items()))} (0 means client/network error)")
    print(
        "Latency: "
        f"mean={statistics.mean(latencies) * 1000:.1f}ms "
        f"p50={percentile(latencies, 0.50) * 1000:.1f}ms "
        f"p95={percentile(latencies, 0.95) * 1000:.1f}ms"
    )


if __name__ == "__main__":
    main()
