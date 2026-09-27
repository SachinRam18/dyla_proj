import json
import time

from app.redis_client import redis_client


CAPACITY_KEY = "ticket_stampede:capacity"
SOLD_KEY = "ticket_stampede:sold"
TICKETS_KEY = "ticket_stampede:tickets"
REQUESTS_KEY = "ticket_stampede:requests"

RESET_SCRIPT = """
redis.call('DEL', KEYS[1], KEYS[2], KEYS[3], KEYS[4])
redis.call('SET', KEYS[1], ARGV[1])
redis.call('SET', KEYS[2], 0)
return 1
"""

BUY_SCRIPT = """
local existing = redis.call('HGET', KEYS[4], ARGV[1])
if existing then
    return {1, existing}
end

local sold = tonumber(redis.call('GET', KEYS[2]) or '0')
local capacity = tonumber(redis.call('GET', KEYS[1]) or '0')
if sold >= capacity then
    return {0, ''}
end

local ticket_number = sold + 1
local ticket = cjson.encode({ticket_number = ticket_number, user_id = ARGV[2]})
redis.call('SET', KEYS[2], ticket_number)
redis.call('HSET', KEYS[3], ticket_number, ticket)
redis.call('HSET', KEYS[4], ARGV[1], ticket_number)
return {1, ticket_number}
"""

STATUS_SCRIPT = """
return {redis.call('GET', KEYS[1]) or '0', redis.call('HGETALL', KEYS[2])}
"""


def reset_tickets(ticket_count: int) -> None:
    # Redis runs the reset as one operation, so buyers cannot observe partial state.
    redis_client.eval(
        RESET_SCRIPT,
        4,
        CAPACITY_KEY,
        SOLD_KEY,
        TICKETS_KEY,
        REQUESTS_KEY,
        ticket_count,
    )


def buy_ticket(user_id: str, request_id: str) -> int | None:
    # Lua executes atomically: each buyer sees the previous complete sale state.
    result = redis_client.eval(
        BUY_SCRIPT,
        4,
        CAPACITY_KEY,
        SOLD_KEY,
        TICKETS_KEY,
        REQUESTS_KEY,
        request_id,
        user_id,
    )
    if int(result[0]) == 0:
        return None
    return int(result[1])


def get_status() -> dict:
    result = redis_client.eval(STATUS_SCRIPT, 2, SOLD_KEY, TICKETS_KEY)
    sold = int(result[0])
    ticket_values = result[1]
    tickets = [
        json.loads(ticket_values[index + 1])
        for index in range(0, len(ticket_values), 2)
    ]
    tickets.sort(key=lambda ticket: ticket["ticket_number"])
    return {"sold": sold, "tickets": tickets}


def buy_ticket_naive(user_id: str, request_id: str) -> int | None:
    existing = redis_client.hget(REQUESTS_KEY, request_id)
    if existing is not None:
        return int(existing)

    sold = int(redis_client.get(SOLD_KEY) or 0)
    capacity = int(redis_client.get(CAPACITY_KEY) or 0)
    if sold >= capacity:
        return None

    # Widen the race between the unprotected capacity check and increment.
    time.sleep(0.01)
    ticket_number = redis_client.incr(SOLD_KEY)
    redis_client.hset(
        TICKETS_KEY,
        ticket_number,
        json.dumps({"ticket_number": ticket_number, "user_id": user_id}),
    )
    redis_client.hset(REQUESTS_KEY, request_id, ticket_number)
    return ticket_number