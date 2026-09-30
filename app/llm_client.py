"""LLM clients for structured member-attribute extraction."""

import json
from collections.abc import Mapping
from typing import Protocol, TypedDict

import httpx

from app.config import settings


class ExtractedAttribute(TypedDict):
    kind: str  # need | offer | context | interest
    text: str
    confidence: float
    restricted: bool


class LLMClient(Protocol):
    def extract_attributes(self, message_text: str) -> list[ExtractedAttribute]:
        """Extract structured attributes from one raw member message."""
        ...


class LLMError(Exception):
    """A permanent provider or response error that should not be retried."""


class TransientLLMError(LLMError):
    """A retryable provider error such as a timeout, rate limit, or 5xx."""


EXTRACTION_INSTRUCTIONS = """You extract durable member attributes from one private-club message.
Return zero or more concise attributes. Use kind=need for something the member wants, offer for
expertise/resources they can provide, context for relevant background or circumstances, and
interest for activities or topics they want to participate in. Mark restricted=true for any health,
clinical, or psychometric information, including diagnoses, symptoms, therapy, mental health, and
psychological traits. Preserve important terms from the message in text. Do not infer facts that are
not stated; use an empty attributes array when there is no durable attribute.

Examples: seeking investor introductions is a need; having led fundraising and being willing to help
is an offer; therapy or an anxiety diagnosis is restricted context; seeking a recurring sports group
is an interest.
"""


EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "attributes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["need", "offer", "context", "interest"]},
                    "text": {"type": "string"},
                    "confidence": {"type": "number"},
                    "restricted": {"type": "boolean"},
                },
                "required": ["kind", "text", "confidence", "restricted"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["attributes"],
    "additionalProperties": False,
}


class OpenAIExtractionClient:
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        timeout_seconds: float = 30.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for attribute extraction")
        self.api_key = api_key
        self.model = model
        self.http_client = http_client or httpx.Client(timeout=timeout_seconds)

    def extract_attributes(self, message_text: str) -> list[ExtractedAttribute]:
        try:
            response = self.http_client.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "instructions": EXTRACTION_INSTRUCTIONS,
                    "input": message_text,
                    "store": False,
                    "temperature": 0,
                    "text": {
                        "format": {
                            "type": "json_schema",
                            "name": "member_attributes",
                            "strict": True,
                            "schema": EXTRACTION_SCHEMA,
                        }
                    },
                },
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise TransientLLMError(f"OpenAI transport failure: {type(exc).__name__}") from exc

        if response.status_code == 429 or response.status_code >= 500:
            raise TransientLLMError(f"OpenAI transient HTTP status {response.status_code}")
        if response.is_error:
            raise LLMError(f"OpenAI HTTP status {response.status_code}: {response.text[:300]}")

        try:
            payload = response.json()
            output_text = _response_output_text(payload)
            parsed = json.loads(output_text)
            return [_validate_attribute(item) for item in parsed["attributes"]]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise LLMError("OpenAI returned an invalid structured extraction response") from exc


def _response_output_text(payload: Mapping) -> str:
    for output_item in payload.get("output", []):
        if output_item.get("type") != "message":
            continue
        for content_item in output_item.get("content", []):
            if content_item.get("type") == "output_text":
                return content_item["text"]
    raise KeyError("output_text")


def _validate_attribute(item: Mapping) -> ExtractedAttribute:
    kind = item["kind"]
    text = item["text"].strip()
    confidence = float(item["confidence"])
    restricted = item["restricted"]
    if kind not in {"need", "offer", "context", "interest"}:
        raise ValueError("invalid attribute kind")
    if not text or not 0 <= confidence <= 1 or not isinstance(restricted, bool):
        raise ValueError("invalid attribute fields")
    return {"kind": kind, "text": text, "confidence": confidence, "restricted": restricted}


def get_extraction_llm() -> LLMClient:
    return OpenAIExtractionClient(
        api_key=settings.openai_api_key or "",
        model=settings.openai_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )


class FakeLLMClient:
    """Trivial test double — does not call any real API."""

    def __init__(self, canned_response: list[ExtractedAttribute] | None = None) -> None:
        self.canned_response = canned_response or []
        self.calls: list[str] = []

    def extract_attributes(self, message_text: str) -> list[ExtractedAttribute]:
        self.calls.append(message_text)
        return self.canned_response
