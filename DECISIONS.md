# Decisions

## Architecture

FastAPI keeps the HTTP API small and typed; Redis provides shared state and atomic Lua execution. A relational database or message queue would add operational work without helping this single-sale correctness exercise. Microservices, a frontend, containers, and distributed locks were also rejected to keep the take-home project runnable and inspectable.

## Concurrency and idempotency

`POST /buy` runs one Lua script. Redis serializes script execution: the script checks the request-ID hash first, checks capacity, then writes the sold counter, ticket record, and request-ID mapping together. Thus separate buyers cannot claim one number or pass the capacity check together. A repeated request ID returns its original number before the sold-out check. `/status` reads sold and all ticket records in one script snapshot. Reset is atomic as well.

The separate `app.naive_main` app intentionally reads the sold count, waits briefly, then increments and writes state in separate commands. Run it with `uvicorn app.naive_main:app --port 8001`; point the same client at port 8001. This makes the race reproducible, not a production alternative.

## Testing

`pytest` covers normal purchase, exhaustion, repeated request IDs, reset, status, and 100 simultaneous unique buyers competing for 20 tickets. The load client also groups concurrent responses by request ID, checks ticket uniqueness across distinct requests, verifies issued ticket bounds, and compares status records and sold count with observed successful responses.

## Performance experiment

Measured locally with Redis and Uvicorn on Windows, using concurrency 100, 20 deliberate duplicate replays, and capacity 100. Values are recorded after implementation; they are indicative, not a service-level guarantee.

| Requests | Throughput | Median | P99 | Successful unique tickets | Invariants |
|---:|---:|---:|---:|---:|:---:|
| 100 | 454 req/s | 112 ms | 208 ms | 80 | PASS |
| 500 | 435 req/s | 165 ms | 782 ms | 100 | PASS |
| 1,000 | 407 req/s | 159 ms | 1,062 ms | 100 | PASS |
| 5,000 | 306 req/s | 192 ms | 2,291 ms | 100 | PASS |
| 10,000 | 326 req/s | 184 ms | 1,852 ms | 100 | PASS |

These runs used concurrency 100, capacity 100, and 20 duplicate replays. Successful HTTP responses include idempotent replays; “successful unique tickets” is the number actually issued and recorded by Redis. On the naive app, 5,000 requests at concurrency 200 produced 121 successful responses and issued 101 tickets, failing the no-overselling invariant. The unsafe read/sleep/increment can oversell; lower contention may not reproduce it on every run.

## Failure behavior

Stopped local Redis during a sale request: `POST /buy` returned HTTP 503 (`Ticket service temporarily unavailable`) in 2.44 seconds. No purchase is attempted from a local fallback. A slow Redis connection can occupy an API worker until the configured three-second socket timeout; a client timeout can be ambiguous if Redis committed just before the connection failed. Retrying the same request ID is safe while Redis state is retained. This outage check is not a Redis latency benchmark.

## With two more weeks

Add Redis persistence and tested replication/failover, run multiple seller instances against shared Redis, improve recovery and observability, and use distributed load generation for larger tests. None is implemented here.