# Ticket Stampede

A small FastAPI ticket seller and an asynchronous `httpx` load client. Redis atomically allocates tickets, enforces request idempotency, and provides consistent sale status.

## Architecture

```text
Load Client
     |
     v
 FastAPI Seller
     |
     v
   Redis
```

Redis is the shared source of truth. A Lua script performs each allocation as one atomic operation, avoiding overselling and repeated ticket assignment without a separate lock service.

## Setup

Install Python dependencies, then start Redis in one terminal and the seller in another:

```powershell
pip install -r requirements.txt
redis-server
uvicorn app.main:app --reload
```

The API uses `redis://localhost:6379/0` by default. Set `REDIS_URL` to use another Redis instance or database.

## Tests

With Redis running:

```powershell
pytest
```

## Load test

```powershell
python client/load_test.py --requests 5000 --concurrency 100 --duplicates 20 --url http://localhost:8000
```

The client resets the sale to 100 tickets by default. Use `--tickets` to change capacity. It reports latency and throughput, then checks overselling, duplicate tickets, idempotency, and status consistency.

## Results

Recorded local benchmark results and the naive-versus-atomic comparison are in [DECISIONS.md](DECISIONS.md). At 5,000 requests / concurrency 200, the naive seller failed the no-overselling check. Measurements depend on machine and Redis version; successful response totals include idempotent replays.

## Limitations

This is a single Redis-backed seller, not a highly available deployment. Redis persistence, replication/failover, authentication, request throttling, and recovery from a client timeout after a committed purchase are not configured. A Redis connection failure returns HTTP 503; it does not fall back to another store. Reset deletes only this application's four Redis keys and is intended for a controlled test sale, not a live event.