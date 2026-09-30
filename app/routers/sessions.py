from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_member, require_admin
from app.db import get_db
from app.models import ConversationSession, Member
from app.services.payment_mock import payment_mock_client
from app.services.session_flow import SimulatedCrash, advance_turn

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("/debug/payment-charge-log")
def payment_charge_log(_: Member = Depends(require_admin)):
    """Every charge attempted against the mock provider, in order — a
    stand-in for the provider's own ledger, useful for proving a bug caused
    two real-world charges."""
    return {"charges": payment_mock_client.charge_log}


@router.post("")
def create_session(member: Member = Depends(get_current_member), db: Session = Depends(get_db)):
    session = ConversationSession(member_id=member.id, club_id=member.club_id)
    db.add(session)
    db.commit()
    db.refresh(session)
    return {"session_id": session.id, "status": session.status}


@router.get("/{session_id}")
def get_session(session_id: int, member: Member = Depends(get_current_member), db: Session = Depends(get_db)):
    session = (
        db.query(ConversationSession)
        .filter(ConversationSession.id == session_id, ConversationSession.member_id == member.id)
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    return {
        "session_id": session.id,
        "status": session.status,
        "party_size": session.party_size,
        "awaiting_confirmation": session.awaiting_confirmation,
        "booking_id": session.booking_id,
    }


@router.post("/{session_id}/turn")
def turn(
    session_id: int,
    payload: dict,
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    session = (
        db.query(ConversationSession)
        .filter(ConversationSession.id == session_id, ConversationSession.member_id == member.id)
        .with_for_update()
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="session not found")

    intent = payload.get("intent")
    try:
        return advance_turn(session, intent, payload, db)
    except SimulatedCrash:
        raise HTTPException(status_code=500, detail="simulated crash after charge, before persistence")
