import argparse
import json
import statistics
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib import error, request


def post_reading(url: str, reading: dict) -> tuple[int, float]:
    body = json.dumps(reading).encode("utf-8")
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
        "--simulate-retries",
        type=float,
        default=0,
        metavar="PCT",
        help="Send this percentage of logical readings twice with the same natural key.",
    )
    parser.add_argument(
        "--allow-large-run",
        action="store_true",
        help="Allow more than 10,000 requests.",
    )
    args = parser.parse_args()

    if args.requests < 1 or args.concurrency < 1:
        parser.error("--requests and --concurrency must be positive")
    if not 0 <= args.simulate_retries <= 100:
        parser.error("--simulate-retries must be between 0 and 100")

    retry_count = round(args.requests * args.simulate_retries / 100)
    http_request_count = args.requests + retry_count
    if http_request_count > 10_000 and not args.allow_large_run:
        parser.error("more than 10,000 HTTP requests requires --allow-large-run")

    url = args.endpoint.rstrip("/")
    if not url.endswith("/readings"):
        url = f"{url}/readings"

    event_time = datetime.now(timezone.utc)
    readings = []
    for sequence in range(args.requests):
        reading = {
            "machine_id": f"load-test-{sequence % 10:02d}",
            "timestamp": (event_time + timedelta(microseconds=sequence)).isoformat(),
            "temperature_f": 80.0,
            "vibration_mm_s": 0.1,
            "pressure_psi": 55.0,
            "rpm": 1700,
        }
        readings.append(reading)
        if sequence < retry_count:
            readings.append(reading.copy())

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        results = list(executor.map(lambda reading: post_reading(url, reading), readings))
    elapsed = time.perf_counter() - started

    statuses = Counter(status for status, _ in results)
    latencies = [duration for _, duration in results]

    print(f"Target: {url}")
    print(
        f"Logical readings: {args.requests}; simulated retries: {retry_count}; "
        f"HTTP requests: {http_request_count}"
    )
    print(
        f"Completed in {elapsed:.2f}s "
        f"({http_request_count / elapsed:.2f} HTTP RPS)"
    )
    print(f"Statuses: {dict(sorted(statuses.items()))} (0 means client/network error)")
    print(
        "Latency: "
        f"mean={statistics.mean(latencies) * 1000:.1f}ms "
        f"p50={percentile(latencies, 0.50) * 1000:.1f}ms "
        f"p95={percentile(latencies, 0.95) * 1000:.1f}ms"
    )
    if retry_count:
        print(
            "Expected for natural keys accepted with 202: one DynamoDB item; "
            "duplicate natural keys are skipped by the writer."
        )


if __name__ == "__main__":
    main()
