from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app import ticket_service
from app.main import app


@pytest.fixture
def client():
    ticket_service.reset_tickets(0)
    with TestClient(app) as test_client:
        yield test_client
    ticket_service.reset_tickets(0)


def test_normal_purchase_and_status(client):
    client.post("/reset", json={"ticket_count": 2}).raise_for_status()

    response = client.post("/buy", json={"user_id": "user1", "request_id": "request1"})

    assert response.status_code == 200
    assert response.json() == {"ticket_number": 1}
    assert client.get("/status").json() == {
        "sold": 1,
        "tickets": [{"ticket_number": 1, "user_id": "user1"}],
    }


def test_sold_out(client):
    client.post("/reset", json={"ticket_count": 1})
    client.post("/buy", json={"user_id": "user1", "request_id": "request1"})

    response = client.post("/buy", json={"user_id": "user2", "request_id": "request2"})

    assert response.status_code == 409
    assert response.json()["detail"] == {"error": "sold_out"}


def test_duplicate_request_id_returns_same_ticket(client):
    client.post("/reset", json={"ticket_count": 2})
    payload = {"user_id": "user1", "request_id": "same-request"}

    first = client.post("/buy", json=payload)
    client.post("/buy", json={"user_id": "user2", "request_id": "another-request"})
    duplicate = client.post("/buy", json=payload)

    assert first.status_code == duplicate.status_code == 200
    assert first.json() == duplicate.json() == {"ticket_number": 1}
    assert client.get("/status").json()["sold"] == 2


def test_concurrent_purchases_never_exceed_capacity(client):
    ticket_count = 20
    request_count = 100
    client.post("/reset", json={"ticket_count": ticket_count})

    def purchase(index):
        return client.post(
            "/buy",
            json={"user_id": f"user-{index}", "request_id": f"request-{index}"},
        )

    with ThreadPoolExecutor(max_workers=request_count) as executor:
        responses = list(executor.map(purchase, range(request_count)))

    assert sum(response.status_code == 200 for response in responses) == ticket_count
    assert sum(response.status_code == 409 for response in responses) == request_count - ticket_count
    sold_status = client.get("/status").json()
    ticket_numbers = [ticket["ticket_number"] for ticket in sold_status["tickets"]]
    assert sold_status["sold"] == len(ticket_numbers) == ticket_count
    assert sorted(ticket_numbers) == list(range(1, ticket_count + 1))


def test_reset_clears_tickets_and_request_ids(client):
    client.post("/reset", json={"ticket_count": 2})
    client.post("/buy", json={"user_id": "user1", "request_id": "reused-request"})
    client.post("/reset", json={"ticket_count": 1})

    status = client.get("/status").json()
    response = client.post(
        "/buy", json={"user_id": "user2", "request_id": "reused-request"}
    )

    assert status == {"sold": 0, "tickets": []}
    assert response.status_code == 200
    assert response.json() == {"ticket_number": 1}