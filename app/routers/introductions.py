from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import get_current_member
from app.config import settings
from app.db import get_db
from app.models import Member, MemberAttribute

router = APIRouter(prefix="/introductions", tags=["introductions"])


@router.get("/{member_a_id}/{member_b_id}")
def generate_reason(
    member_a_id: int,
    member_b_id: int,
    reason: str,
    confidence_threshold: float | None = Query(default=None, ge=0, le=1),
    db: Session = Depends(get_db),
    member: Member = Depends(get_current_member),
):
    threshold = settings.introduction_confidence_threshold if confidence_threshold is None else confidence_threshold
    members = (
        db.query(Member)
        .filter(Member.id.in_([member_a_id, member_b_id]), Member.club_id == member.club_id)
        .all()
    )
    members_by_id = {candidate.id: candidate for candidate in members}
    if member_a_id not in members_by_id or member_b_id not in members_by_id:
        raise HTTPException(status_code=404, detail="members not found")

    def qualifying_attributes(member_id: int) -> list[MemberAttribute]:
        return (
            db.query(MemberAttribute)
            .filter(
                MemberAttribute.member_id == member_id,
                MemberAttribute.club_id == member.club_id,
                MemberAttribute.restricted.is_(False),
                MemberAttribute.confidence >= threshold,
            )
            .order_by(MemberAttribute.confidence.desc(), MemberAttribute.id)
            .all()
        )

    attrs_a = qualifying_attributes(member_a_id)
    attrs_b = qualifying_attributes(member_b_id)
    source_attributes = [
        {
            "attribute_id": attribute.id,
            "member_id": attribute.member_id,
            "kind": attribute.kind,
            "text": attribute.text,
            "confidence": attribute.confidence,
        }
        for attribute in attrs_a + attrs_b
    ]

    if not source_attributes:
        return {
            "reason_text": "insufficient basis for an introduction",
            "source_attributes": [],
            "confidence_threshold": threshold,
        }

    grounded_parts = []
    if attrs_a:
        grounded_parts.append(f"{members_by_id[member_a_id].name}: " + "; ".join(a.text for a in attrs_a))
    if attrs_b:
        grounded_parts.append(f"{members_by_id[member_b_id].name}: " + "; ".join(a.text for a in attrs_b))
    return {
        "reason_text": f"Grounded {reason} introduction — " + " | ".join(grounded_parts),
        "source_attributes": source_attributes,
        "confidence_threshold": threshold,
    }
