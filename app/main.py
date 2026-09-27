from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from redis.exceptions import RedisError

from app.ticket_service import buy_ticket, get_status, reset_tickets


app = FastAPI(title="Ticket Stampede Seller")


class ResetRequest(BaseModel):
    ticket_count: int = Field(ge=0)


class BuyRequest(BaseModel):
    user_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)


def redis_unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail="Ticket service temporarily unavailable")


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
        ticket_number = buy_ticket(request.user_id, request.request_id)
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