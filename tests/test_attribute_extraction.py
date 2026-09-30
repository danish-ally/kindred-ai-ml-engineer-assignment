import httpx

from fastapi.testclient import TestClient

from app.llm_client import FakeLLMClient, OpenAIExtractionClient, TransientLLMError, get_extraction_llm
from app.main import app
from app.models import Club, ConversationMessage, Member, MemberAttribute
from app.services.extraction_service import extract_with_retry
from app.services.matching_service import build_member_profile_text

client = TestClient(app)


def test_openai_client_requests_and_parses_strict_structured_output():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = __import__("json").loads(request.content)
        assert request.url == "https://api.openai.com/v1/responses"
        assert payload["store"] is False
        assert payload["text"]["format"]["type"] == "json_schema"
        assert payload["text"]["format"]["strict"] is True
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": '{"attributes":[{"kind":"need","text":"investor introductions","confidence":0.95,"restricted":false}]}',
                            }
                        ],
                    }
                ]
            },
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    extraction_client = OpenAIExtractionClient(api_key="test-key", http_client=http_client)

    attributes = extraction_client.extract_attributes("I need investor introductions")

    assert attributes == [
        {"kind": "need", "text": "investor introductions", "confidence": 0.95, "restricted": False}
    ]


def seed_clubs_and_messages(db):
    db.add_all([Club(id="riverside", name="Riverside"), Club(id="oakhurst", name="Oakhurst")])
    admin = Member(
        club_id="riverside", name="Admin", email="admin@example.com", token="admin-token", role="admin"
    )
    member = Member(
        club_id="riverside", name="Member", email="member@example.com", token="member-token", role="member"
    )
    other_admin = Member(
        club_id="oakhurst", name="Other Admin", email="other@example.com", token="other-token", role="admin"
    )
    db.add_all([admin, member, other_admin])
    db.flush()
    message = ConversationMessage(
        member_id=member.id,
        club_id="riverside",
        body="I am looking for investor introductions and have been managing anxiety.",
    )
    db.add(message)
    db.commit()
    return member, message


def test_extract_attributes_happy_path_and_idempotency(db):
    member, message = seed_clubs_and_messages(db)
    fake = FakeLLMClient(
        [
            {"kind": "need", "text": "looking for investor introductions", "confidence": 0.94, "restricted": False},
            {"kind": "context", "text": "managing anxiety", "confidence": 0.98, "restricted": True},
        ]
    )
    app.dependency_overrides[get_extraction_llm] = lambda: fake
    try:
        first = client.post(
            "/clubs/riverside/extract-attributes",
            json={"message_ids": [message.id]},
            headers={"X-Member-Token": "admin-token"},
        )
        second = client.post(
            "/clubs/riverside/extract-attributes",
            json={"message_ids": [message.id]},
            headers={"X-Member-Token": "admin-token"},
        )
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == 200
    assert first.json()["results"] == [
        {"message_id": message.id, "status": "processed", "attribute_count": 2}
    ]
    assert second.json()["results"] == [
        {"message_id": message.id, "status": "already_processed", "attribute_count": 2}
    ]
    assert fake.calls == [message.body]
    attributes = db.query(MemberAttribute).filter(MemberAttribute.source_message_id == message.id).all()
    assert len(attributes) == 2
    assert {attribute.restricted for attribute in attributes} == {False, True}
    assert build_member_profile_text(member, db) == "looking for investor introductions"
    db.refresh(member)
    assert member.profile_embedding is not None


def test_extraction_requires_same_club_admin(db):
    _, message = seed_clubs_and_messages(db)
    fake = FakeLLMClient()
    app.dependency_overrides[get_extraction_llm] = lambda: fake
    try:
        member_response = client.post(
            "/clubs/riverside/extract-attributes",
            json={"message_ids": [message.id]},
            headers={"X-Member-Token": "member-token"},
        )
        other_club_response = client.post(
            "/clubs/riverside/extract-attributes",
            json={"message_ids": [message.id]},
            headers={"X-Member-Token": "other-token"},
        )
    finally:
        app.dependency_overrides.clear()

    assert member_response.status_code == 403
    assert other_club_response.status_code == 403
    assert fake.calls == []


def test_transient_failures_retry_with_exponential_backoff():
    class FlakyClient:
        def __init__(self):
            self.calls = 0

        def extract_attributes(self, message_text):
            self.calls += 1
            if self.calls < 3:
                raise TransientLLMError("retry me")
            return [{"kind": "interest", "text": "running", "confidence": 0.9, "restricted": False}]

    flaky = FlakyClient()
    delays = []
    result = extract_with_retry(
        flaky,
        "weekly running club",
        max_attempts=3,
        base_delay_seconds=1,
        sleep=delays.append,
    )

    assert result[0]["kind"] == "interest"
    assert flaky.calls == 3
    assert len(delays) == 2
    assert 1 <= delays[0] <= 2
    assert 2 <= delays[1] <= 3


def test_permanent_message_failure_does_not_stop_batch(db):
    member, failed_message = seed_clubs_and_messages(db)
    next_message = ConversationMessage(
        member_id=member.id,
        club_id="riverside",
        body="I want to join a running group.",
    )
    db.add(next_message)
    db.commit()

    class PerMessageClient:
        def extract_attributes(self, message_text):
            if "anxiety" in message_text:
                raise ValueError("permanent test failure")
            return [{"kind": "interest", "text": "running group", "confidence": 0.9, "restricted": False}]

    app.dependency_overrides[get_extraction_llm] = PerMessageClient
    try:
        response = client.post(
            "/clubs/riverside/extract-attributes",
            json={"message_ids": [failed_message.id, next_message.id]},
            headers={"X-Member-Token": "admin-token"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert [result["status"] for result in response.json()["results"]] == ["failed", "processed"]
    assert db.query(MemberAttribute).filter(MemberAttribute.source_message_id == failed_message.id).count() == 0
    assert db.query(MemberAttribute).filter(MemberAttribute.source_message_id == next_message.id).count() == 1
