from sqlalchemy.orm import Session as DbSession

from app.models import Booking, ConversationSession, PaymentAttempt
from app.services.knowledge_service import find_grounded_knowledge
from app.services.payment_mock import payment_mock_client


class SimulatedCrash(Exception):
    """Lets a caller reproduce a process crash between the charge succeeding
    and the session/booking being persisted — the same ambiguous-outcome
    scenario as a real payment-provider timeout, but deterministic to trigger."""


def advance_turn(session: ConversationSession, intent: str, payload: dict, db: DbSession) -> dict:
    if intent == "knowledge_question":
        match = find_grounded_knowledge(session.club_id, payload.get("question", ""), db)
        if match is None:
            session.status = "escalated"
            db.commit()
            return {"status": "escalate"}
        return {
            "status": "answered",
            "answer": match.chunk.body,
            "source": {
                "chunk_id": match.chunk.id,
                "title": match.chunk.title,
                "matched_terms": match.matched_terms,
                "score": round(match.score, 4),
            },
        }

    if intent == "refund_dispute":
        session.status = "escalated"
        db.commit()
        return {"status": "escalated"}

    if intent == "book":
        party_size = payload.get("party_size")
        if party_size is not None:
            session.party_size = party_size
        if session.party_size is not None:
            session.awaiting_confirmation = True
        db.commit()
        return {
            "status": "awaiting_confirmation" if session.awaiting_confirmation else "need_party_size",
            "party_size": session.party_size,
        }

    if intent == "affirm" and session.status == "confirmed":
        return {"status": "confirmed", "booking_id": session.booking_id}

    if intent == "affirm" and session.awaiting_confirmation:
        idempotency_key = f"session-confirmation:{session.id}"
        attempt = (
            db.query(PaymentAttempt)
            .filter(PaymentAttempt.idempotency_key == idempotency_key)
            .first()
        )

        if attempt is None:
            amount_cents = payload.get("amount_cents", 0)
            booking = Booking(
                member_id=session.member_id,
                club_id=session.club_id,
                description="Session-confirmed booking",
                amount_cents=amount_cents,
                status="pending",
            )
            db.add(booking)
            db.flush()
            attempt = PaymentAttempt(
                booking_id=booking.id,
                idempotency_key=idempotency_key,
                amount_cents=amount_cents,
                status="pending",
            )
            db.add(attempt)
            db.commit()
        else:
            booking = db.get(Booking, attempt.booking_id)
            amount_cents = attempt.amount_cents

        if attempt.status == "succeeded":
            session.booking_id = booking.id
            session.status = "confirmed"
            session.awaiting_confirmation = False
            db.commit()
            return {"status": "confirmed", "booking_id": booking.id}

        result = payment_mock_client.charge(amount_cents, idempotency_key=idempotency_key)

        if payload.get("simulate_crash"):
            raise SimulatedCrash("process died after the charge, before the session/booking were saved")

        attempt.status = result.status
        booking.status = "confirmed" if result.status == "succeeded" else "pending"
        db.add(attempt)
        db.add(booking)
        session.booking_id = booking.id
        if result.status == "succeeded":
            session.status = "confirmed"
            session.awaiting_confirmation = False
        db.commit()
        return {"status": session.status, "booking_id": booking.id}

    return {"status": session.status}
