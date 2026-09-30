from fastapi.testclient import TestClient

from app.main import app
from app.models import Booking, Club, Member, PaymentAttempt
from app.services.payment_mock import payment_mock_client

client = TestClient(app)


def test_confirm_payment_succeeds(db):
    payment_mock_client.reset()
    db.add(Club(id="riverside", name="Riverside"))
    m = Member(club_id="riverside", name="A", email="a@example.com", token="tok-a", role="member")
    db.add(m)
    db.commit()

    booking = Booking(member_id=m.id, club_id="riverside", description="Dinner", amount_cents=5000, status="pending")
    db.add(booking)
    db.commit()

    resp = client.post(
        f"/bookings/{booking.id}/confirm-payment",
        json={"amount_cents": 1},
        headers={"X-Member-Token": "tok-a"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "succeeded"
    assert payment_mock_client.charge_log == [5000]
    db.refresh(booking)
    assert booking.status == "confirmed"
    attempt = db.query(PaymentAttempt).one()
    assert attempt.amount_cents == 5000
    assert attempt.idempotency_key == f"booking-confirmation:{booking.id}"


def test_confirm_payment_rejects_already_paid_booking_without_recharging(db):
    payment_mock_client.reset()
    db.add(Club(id="riverside", name="Riverside"))
    member = Member(club_id="riverside", name="A", email="a@example.com", token="tok-a", role="member")
    db.add(member)
    db.flush()
    booking = Booking(
        member_id=member.id,
        club_id="riverside",
        description="Dinner",
        amount_cents=8000,
        status="pending",
    )
    db.add(booking)
    db.commit()

    first = client.post(
        f"/bookings/{booking.id}/confirm-payment",
        headers={"X-Member-Token": "tok-a"},
    )
    second = client.post(
        f"/bookings/{booking.id}/confirm-payment",
        headers={"X-Member-Token": "tok-a"},
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json() == {"detail": "booking already paid"}
    assert payment_mock_client.charge_log == [8000]
    assert db.query(PaymentAttempt).count() == 1
