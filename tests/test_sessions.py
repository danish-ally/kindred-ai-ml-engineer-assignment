from fastapi.testclient import TestClient

from app.main import app
from app.models import Booking, Club, Member, PaymentAttempt
from app.services.payment_mock import payment_mock_client

client = TestClient(app)


def test_session_books_end_to_end(db):
    db.add(Club(id="riverside", name="Riverside"))
    m = Member(club_id="riverside", name="A", email="a@example.com", token="tok-a", role="member")
    db.add(m)
    db.commit()

    resp = client.post("/sessions", headers={"X-Member-Token": "tok-a"})
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    resp = client.post(
        f"/sessions/{session_id}/turn",
        json={"intent": "book", "party_size": 2},
        headers={"X-Member-Token": "tok-a"},
    )
    assert resp.json()["status"] == "awaiting_confirmation"

    resp = client.post(
        f"/sessions/{session_id}/turn",
        json={"intent": "affirm", "amount_cents": 4000},
        headers={"X-Member-Token": "tok-a"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "confirmed"


def test_refund_dispute_escalates(db):
    db.add(Club(id="riverside", name="Riverside"))
    m = Member(club_id="riverside", name="A", email="a@example.com", token="tok-a", role="member")
    db.add(m)
    db.commit()

    session_id = client.post("/sessions", headers={"X-Member-Token": "tok-a"}).json()["session_id"]

    resp = client.post(
        f"/sessions/{session_id}/turn",
        json={"intent": "refund_dispute"},
        headers={"X-Member-Token": "tok-a"},
    )
    assert resp.json()["status"] == "escalated"


def test_session_confirmation_is_idempotent_after_crash(db):
    payment_mock_client.reset()
    db.add(Club(id="riverside", name="Riverside"))
    member = Member(club_id="riverside", name="A", email="a@example.com", token="tok-a", role="member")
    db.add(member)
    db.commit()

    session_id = client.post("/sessions", headers={"X-Member-Token": "tok-a"}).json()["session_id"]
    client.post(
        f"/sessions/{session_id}/turn",
        json={"intent": "book", "party_size": 2},
        headers={"X-Member-Token": "tok-a"},
    )

    crashed = client.post(
        f"/sessions/{session_id}/turn",
        json={"intent": "affirm", "amount_cents": 5000, "simulate_crash": True},
        headers={"X-Member-Token": "tok-a"},
    )
    assert crashed.status_code == 500

    retried = client.post(
        f"/sessions/{session_id}/turn",
        json={"intent": "affirm", "amount_cents": 7000},
        headers={"X-Member-Token": "tok-a"},
    )
    repeated = client.post(
        f"/sessions/{session_id}/turn",
        json={"intent": "affirm", "amount_cents": 9000},
        headers={"X-Member-Token": "tok-a"},
    )

    assert retried.status_code == 200
    assert repeated.json() == retried.json()
    assert payment_mock_client.charge_log == [5000]
    assert db.query(Booking).count() == 1
    assert db.query(PaymentAttempt).count() == 1
    booking = db.query(Booking).one()
    attempt = db.query(PaymentAttempt).one()
    assert booking.amount_cents == 5000
    assert booking.status == "confirmed"
    assert attempt.amount_cents == 5000
    assert attempt.status == "succeeded"
    assert attempt.idempotency_key == f"session-confirmation:{session_id}"
