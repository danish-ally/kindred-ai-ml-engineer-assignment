from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.db import get_db
from app.llm_client import LLMClient, get_extraction_llm
from app.models import Member
from app.schemas import ExtractAttributesIn
from app.services.extraction_service import extract_message_batch

router = APIRouter(prefix="/clubs", tags=["attributes"])


@router.post("/{club_id}/extract-attributes")
def extract_attributes(
    club_id: str,
    payload: ExtractAttributesIn,
    admin: Member = Depends(require_admin),
    db: Session = Depends(get_db),
    llm: LLMClient = Depends(get_extraction_llm),
):
    if admin.club_id != club_id:
        raise HTTPException(status_code=403, detail="admin cannot extract another club's messages")

    results = extract_message_batch(club_id=club_id, message_ids=payload.message_ids, db=db, llm=llm)
    return {
        "club_id": club_id,
        "results": results,
        "processed": sum(result["status"] == "processed" for result in results),
        "failed": sum(result["status"] == "failed" for result in results),
    }
