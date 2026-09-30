from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_member
from app.db import get_db
from app.models import Booking, Member, PaymentAttempt
from app.services.payment_mock import PaymentTimeoutError, payment_mock_client

router = APIRouter(prefix="/bookings", tags=["bookings"])


@router.post("/{booking_id}/confirm-payment")
def confirm_payment(
    booking_id: int,
    db: Session = Depends(get_db),
    member: Member = Depends(get_current_member),
):
    booking = (
        db.query(Booking)
        .filter(Booking.id == booking_id, Booking.member_id == member.id)
        .with_for_update()
        .first()
    )
    if not booking:
        raise HTTPException(status_code=404, detail="booking not found")
    if booking.status == "confirmed":
        raise HTTPException(status_code=409, detail="booking already paid")

    idempotency_key = f"booking-confirmation:{booking.id}"
    attempt = (
        db.query(PaymentAttempt)
        .filter(PaymentAttempt.idempotency_key == idempotency_key)
        .first()
    )
    if attempt is None:
        attempt = PaymentAttempt(
            booking_id=booking.id,
            idempotency_key=idempotency_key,
            amount_cents=booking.amount_cents,
            status="pending",
        )
        db.add(attempt)
        db.commit()
    elif attempt.amount_cents != booking.amount_cents:
        raise HTTPException(status_code=409, detail="payment attempt amount does not match booking")

    if attempt.status == "succeeded":
        booking.status = "confirmed"
        db.commit()
        return {"status": "succeeded", "attempt_id": attempt.id, "booking_status": booking.status}

    try:
        result = payment_mock_client.charge(booking.amount_cents, idempotency_key=idempotency_key)
    except PaymentTimeoutError:
        raise HTTPException(status_code=504, detail="payment provider timed out")

    attempt.status = result.status
    db.add(attempt)
    if result.status == "succeeded":
        booking.status = "confirmed"
    db.commit()

    return {"status": result.status, "attempt_id": attempt.id, "booking_status": booking.status}
