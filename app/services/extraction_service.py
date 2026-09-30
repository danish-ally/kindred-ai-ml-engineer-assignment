import random
import time
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.config import settings
from app.embeddings import embedding_client
from app.llm_client import ExtractedAttribute, LLMClient, TransientLLMError
from app.models import ConversationMessage, Member, MemberAttribute
from app.services.matching_service import build_member_profile_text


def extract_with_retry(
    llm: LLMClient,
    message_text: str,
    *,
    max_attempts: int = settings.llm_max_attempts,
    base_delay_seconds: float = settings.llm_retry_base_seconds,
    sleep: Callable[[float], None] = time.sleep,
) -> list[ExtractedAttribute]:
    for attempt_number in range(1, max_attempts + 1):
        try:
            return llm.extract_attributes(message_text)
        except TransientLLMError:
            if attempt_number == max_attempts:
                raise
            exponential_delay = base_delay_seconds * (2 ** (attempt_number - 1))
            sleep(exponential_delay + random.uniform(0, base_delay_seconds))
    raise AssertionError("retry loop exhausted unexpectedly")


def extract_message_batch(
    *,
    club_id: str,
    message_ids: list[int],
    db: Session,
    llm: LLMClient,
) -> list[dict]:
    results: list[dict] = []
    for message_id in message_ids:
        try:
            message = (
                db.query(ConversationMessage)
                .filter(ConversationMessage.id == message_id, ConversationMessage.club_id == club_id)
                .with_for_update()
                .first()
            )
            if message is None:
                db.rollback()
                results.append({"message_id": message_id, "status": "not_found", "attribute_count": 0})
                continue

            existing_count = (
                db.query(MemberAttribute)
                .filter(MemberAttribute.source_message_id == message.id)
                .count()
            )
            if existing_count:
                db.commit()
                results.append(
                    {"message_id": message_id, "status": "already_processed", "attribute_count": existing_count}
                )
                continue

            extracted = extract_with_retry(llm, message.body)
            for attribute in extracted:
                db.add(
                    MemberAttribute(
                        member_id=message.member_id,
                        club_id=message.club_id,
                        kind=attribute["kind"],
                        text=attribute["text"],
                        confidence=attribute["confidence"],
                        restricted=attribute["restricted"],
                        source_message_id=message.id,
                    )
                )
            db.flush()
            member = db.get(Member, message.member_id)
            member.profile_embedding = embedding_client.embed(build_member_profile_text(member, db))
            db.add(member)
            db.commit()
            results.append({"message_id": message_id, "status": "processed", "attribute_count": len(extracted)})
        except Exception as exc:
            db.rollback()
            results.append(
                {
                    "message_id": message_id,
                    "status": "failed",
                    "attribute_count": 0,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    return results
