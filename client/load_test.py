import argparse
import asyncio
import math
import statistics
import time
from collections import defaultdict

import httpx


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load-test a Ticket Stampede seller")
    parser.add_argument("--requests", type=int, default=5000)
    parser.add_argument("--concurrency", type=int, default=100)
    parser.add_argument("--duplicates", type=int, default=20)
    parser.add_argument("--tickets", type=int, default=100)
    parser.add_argument("--url", default="http://localhost:8000")
    args = parser.parse_args()
    if args.requests < 1 or args.concurrency < 1 or args.tickets < 0:
        parser.error("requests and concurrency must be positive; tickets cannot be negative")
    if args.duplicates < 0 or args.duplicates * 2 > args.requests:
        parser.error("duplicates must be between 0 and requests // 2")
    return args


async def run_load_test(args: argparse.Namespace) -> dict:
    base_url = args.url.rstrip("/")
    async with httpx.AsyncClient(
        base_url=base_url,
        timeout=30,
        limits=httpx.Limits(
            max_connections=args.concurrency,
            max_keepalive_connections=args.concurrency,
        ),
    ) as client:
        reset_response = await client.post("/reset", json={"ticket_count": args.tickets})
        reset_response.raise_for_status()

        request_ids = [f"request-{index}" for index in range(args.requests)]
        for duplicate_index in range(args.duplicates):
            request_ids[-args.duplicates + duplicate_index] = f"request-{duplicate_index}"
        semaphore = asyncio.Semaphore(args.concurrency)

        async def send_buy(index: int) -> dict:
            payload = {"user_id": f"user-{index}", "request_id": request_ids[index]}
            async with semaphore:
                started = time.perf_counter()
                try:
                    response = await client.post("/buy", json=payload)
                    elapsed_ms = (time.perf_counter() - started) * 1000
                    try:
                        body = response.json()
                    except ValueError:
                        body = {}
                    return {
                        "request_id": payload["request_id"],
                        "status_code": response.status_code,
                        "body": body,
                        "latency_ms": elapsed_ms,
                    }
                except httpx.HTTPError as error:
                    return {
                        "request_id": payload["request_id"],
                        "status_code": 0,
                        "body": {"error": str(error)},
                        "latency_ms": (time.perf_counter() - started) * 1000,
                    }

        started = time.perf_counter()
        responses = await asyncio.gather(*(send_buy(index) for index in range(args.requests)))
        elapsed_seconds = time.perf_counter() - started
        status_response = await client.get("/status")
        status_response.raise_for_status()
        sale_status = status_response.json()

    groups = defaultdict(list)
    for response in responses:
        groups[response["request_id"]].append(response)

    idempotency_ok = all(
        len({(response["status_code"], response["body"].get("ticket_number")) for response in group}) == 1
        for group in groups.values()
    )
    successful = [response for response in responses if response["status_code"] == 200]
    sold_out = sum(response["status_code"] == 409 for response in responses)
    request_tickets = {}
    for request_id, group in groups.items():
        numbers = {
            response["body"].get("ticket_number")
            for response in group
            if response["status_code"] == 200
        }
        if numbers:
            request_tickets[request_id] = numbers.pop()

    issued_tickets = sale_status.get("tickets", [])
    status_numbers = [ticket.get("ticket_number") for ticket in issued_tickets]
    status_number_set = set(status_numbers)
    ticket_limit_ok = (
        0 <= sale_status.get("sold", -1) <= args.tickets
        and len(status_numbers) <= args.tickets
        and all(isinstance(number, int) and 1 <= number <= args.tickets for number in status_numbers)
        and len(request_tickets) <= args.tickets
    )
    no_duplicate_tickets = (
        len(status_numbers) == len(status_number_set)
        and len(request_tickets.values()) == len(set(request_tickets.values()))
    )
    status_consistent = (
        sale_status.get("sold") == len(issued_tickets)
        and status_number_set == set(range(1, sale_status.get("sold", 0) + 1))
        and set(request_tickets.values()) == status_number_set
    )
    unexpected = len(responses) - len(successful) - sold_out
    checks = {
        "No overselling": ticket_limit_ok,
        "No duplicate tickets": no_duplicate_tickets,
        "Request idempotency": idempotency_ok,
        "Status consistency": status_consistent,
    }

    latencies = sorted(response["latency_ms"] for response in responses)
    p99 = latencies[max(0, math.ceil(len(latencies) * 0.99) - 1)]
    report = {
        "total": len(responses),
        "concurrency": args.concurrency,
        "successful": len(successful),
        "issued": sale_status.get("sold", 0),
        "sold_out": sold_out,
        "duplicates": args.duplicates,
        "requests_per_second": len(responses) / elapsed_seconds if elapsed_seconds else 0,
        "median_ms": statistics.median(latencies),
        "p99_ms": p99,
        "checks": checks,
        "unexpected": unexpected,
        "passed": all(checks.values()) and unexpected == 0,
    }
    return report


def main() -> None:
    args = parse_args()
    report = asyncio.run(run_load_test(args))
    print("========== LOAD TEST ==========")
    print(f"Total requests:        {report['total']}")
    print(f"Concurrency:           {report['concurrency']}")
    print(f"Successful responses:  {report['successful']}")
    print(f"Unique tickets issued: {report['issued']}")
    print(f"Sold-out responses:    {report['sold_out']}")
    print(f"Duplicate requests:    {report['duplicates']}")
    print(f"Unexpected responses:  {report['unexpected']}")
    print(f"Requests/sec:           {report['requests_per_second']:.1f}")
    print(f"Median latency:         {report['median_ms']:.2f} ms")
    print(f"P99 latency:            {report['p99_ms']:.2f} ms")
    print("\n========== INVARIANTS ==========")
    for name, passed in report["checks"].items():
        print(f"{name + ':':<24}{'PASS' if passed else 'FAIL'}")
    print("\n========== RESULT ==========")
    print("PASS" if report["passed"] else "FAIL")
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()