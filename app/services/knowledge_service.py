import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import KnowledgeChunk


STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "at",
    "can",
    "do",
    "does",
    "for",
    "how",
    "i",
    "in",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "the",
    "to",
    "what",
    "when",
    "where",
    "you",
}


@dataclass(frozen=True)
class GroundedKnowledgeMatch:
    chunk: KnowledgeChunk
    matched_terms: list[str]
    score: float


def _terms(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if token not in STOP_WORDS and len(token) > 1
    }


def find_grounded_knowledge(club_id: str, question: str, db: Session) -> GroundedKnowledgeMatch | None:
    question_terms = _terms(question)
    if not question_terms:
        return None

    best_match = None
    for chunk in db.query(KnowledgeChunk).filter(KnowledgeChunk.club_id == club_id).all():
        matched_terms = sorted(question_terms & _terms(f"{chunk.title} {chunk.body}"))
        if not matched_terms:
            continue
        score = len(matched_terms) / len(question_terms)
        candidate = GroundedKnowledgeMatch(chunk=chunk, matched_terms=matched_terms, score=score)
        if best_match is None or (candidate.score, -candidate.chunk.id) > (best_match.score, -best_match.chunk.id):
            best_match = candidate
    return best_match
