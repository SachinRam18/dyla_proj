from fastapi import FastAPI, HTTPException
from redis.exceptions import RedisError

from app.main import BuyRequest, ResetRequest, redis_unavailable
from app.ticket_service import buy_ticket_naive, get_status, reset_tickets


app = FastAPI(title="Ticket Stampede Naive Seller")


@app.post("/reset")
def reset(request: ResetRequest) -> dict:
    try:
        reset_tickets(request.ticket_count)
    except RedisError as error:
        raise redis_unavailable() from error
    return {"message": "Sale reset", "ticket_count": request.ticket_count}


@app.post("/buy")
def buy(request: BuyRequest):
    try:
        ticket_number = buy_ticket_naive(request.user_id, request.request_id)
    except RedisError as error:
        raise redis_unavailable() from error
    if ticket_number is None:
        raise HTTPException(status_code=409, detail={"error": "sold_out"})
    return {"ticket_number": ticket_number}


@app.get("/status")
def status() -> dict:
    try:
        return get_status()
    except RedisError as error:
        raise redis_unavailable() from error