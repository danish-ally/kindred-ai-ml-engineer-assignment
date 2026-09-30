from fastapi.testclient import TestClient

from app.main import app
from app.models import Club, Member, MemberAttribute

client = TestClient(app)


def test_generate_reason_includes_attributes(db):
    db.add(Club(id="riverside", name="Riverside"))
    m1 = Member(club_id="riverside", name="A", email="a@example.com", token="tok-a", role="member")
    m2 = Member(club_id="riverside", name="B", email="b@example.com", token="tok-b", role="member")
    db.add_all([m1, m2])
    db.commit()

    db.add(MemberAttribute(member_id=m1.id, club_id="riverside", kind="need", text="needs a CFO", confidence=0.9))
    db.add(MemberAttribute(member_id=m2.id, club_id="riverside", kind="offer", text="offers CFO services", confidence=0.9))
    db.commit()

    resp = client.get(
        f"/introductions/{m1.id}/{m2.id}",
        params={"reason": "business"},
        headers={"X-Member-Token": "tok-a"},
    )
    assert resp.status_code == 200
    assert "CFO" in resp.json()["reason_text"]
    assert len(resp.json()["source_attributes"]) == 2
    assert resp.json()["confidence_threshold"] == 0.75


def test_generate_reason_excludes_restricted_and_low_confidence_attributes(db):
    db.add(Club(id="riverside", name="Riverside"))
    m1 = Member(club_id="riverside", name="A", email="a@example.com", token="tok-a", role="member")
    m2 = Member(club_id="riverside", name="B", email="b@example.com", token="tok-b", role="member")
    db.add_all([m1, m2])
    db.flush()
    db.add_all(
        [
            MemberAttribute(member_id=m1.id, club_id="riverside", kind="context", text="private therapy history", confidence=0.99, restricted=True),
            MemberAttribute(member_id=m1.id, club_id="riverside", kind="need", text="possibly needs a CFO", confidence=0.79, restricted=False),
            MemberAttribute(member_id=m2.id, club_id="riverside", kind="offer", text="offers CFO services", confidence=0.95, restricted=False),
        ]
    )
    db.commit()

    response = client.get(
        f"/introductions/{m1.id}/{m2.id}",
        params={"reason": "business", "confidence_threshold": 0.8},
        headers={"X-Member-Token": "tok-a"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "offers CFO services" in payload["reason_text"]
    assert "private therapy history" not in payload["reason_text"]
    assert "possibly needs a CFO" not in payload["reason_text"]
    assert [source["text"] for source in payload["source_attributes"]] == ["offers CFO services"]
    assert payload["confidence_threshold"] == 0.8


def test_generate_reason_returns_insufficient_basis_when_nothing_qualifies(db):
    db.add(Club(id="riverside", name="Riverside"))
    m1 = Member(club_id="riverside", name="A", email="a@example.com", token="tok-a", role="member")
    m2 = Member(club_id="riverside", name="B", email="b@example.com", token="tok-b", role="member")
    db.add_all([m1, m2])
    db.flush()
    db.add(MemberAttribute(member_id=m1.id, club_id="riverside", kind="context", text="restricted diagnosis", confidence=1.0, restricted=True))
    db.commit()

    response = client.get(
        f"/introductions/{m1.id}/{m2.id}",
        params={"reason": "business"},
        headers={"X-Member-Token": "tok-a"},
    )

    assert response.status_code == 200
    assert response.json()["reason_text"] == "insufficient basis for an introduction"
    assert response.json()["source_attributes"] == []


def test_generate_reason_rejects_cross_club_member_ids(db):
    db.add_all([Club(id="riverside", name="Riverside"), Club(id="oakhurst", name="Oakhurst")])
    m1 = Member(club_id="riverside", name="A", email="a@example.com", token="tok-a", role="member")
    m2 = Member(club_id="oakhurst", name="B", email="b@example.com", token="tok-b", role="member")
    db.add_all([m1, m2])
    db.commit()

    response = client.get(
        f"/introductions/{m1.id}/{m2.id}",
        params={"reason": "business"},
        headers={"X-Member-Token": "tok-a"},
    )

    assert response.status_code == 404
