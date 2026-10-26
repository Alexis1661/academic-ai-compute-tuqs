import pytest

from src.adapters.outbound.db import TokenLedgerDB, UserQuotaDB


def test_story_8_1_bdd_scenario_ingest_token_event(client, db_session, fake_clock, seed_sam_quota):
    """
    BDD Acceptance Scenario (Story 8.1):
    Given user "sam" has used 10,000 of their 100,000 daily token limit
    When a token event arrives for "sam" with 500 prompt and 250 completion tokens
    Then the system records the event in the ledger
    And Sam's total used tokens updates to 10,750
    And remaining balance is reported as 89,250
    And HTTP 201 Created is returned
    """
    payload = {
        "user_id": "sam",
        "subject_id": "CS-480",
        "prompt_tokens": 500,
        "completion_tokens": 250
    }

    response = client.post("/api/v1/tokens/events", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert data["user_id"] == "sam"
    assert data["prompt_tokens"] == 500
    assert data["completion_tokens"] == 250
    assert data["total_tokens"] == 750
    assert data["tokens_used"] == 10750
    assert data["token_limit"] == 100000
    assert data["remaining_balance"] == 89250
    assert data["subject_id"] == "CS-480"
    assert data["timestamp"] == "2026-10-25T12:00:00Z"
    assert response.headers["X-Quota-Remaining"] == "89250"
    assert response.headers["X-Quota-Reset"] == "2026-10-26T00:00:00Z"

    # Verify physical database persistence
    quota_db = db_session.query(UserQuotaDB).filter_by(user_id="sam", date=fake_clock.today_str()).one()
    assert quota_db.tokens_used == 10750

    ledger_db = db_session.query(TokenLedgerDB).filter_by(user_id="sam").one()
    assert ledger_db.id == data["id"]
    assert ledger_db.prompt_tokens == 500
    assert ledger_db.completion_tokens == 250
    assert ledger_db.total_tokens == 750
    assert ledger_db.subject_id == "CS-480"


def test_story_8_1_successive_token_events_accumulation(client, db_session, seed_sam_quota):
    """Consecutive events accumulate and each one appends its own ledger row."""
    res1 = client.post("/api/v1/tokens/events", json={
        "user_id": "sam",
        "subject_id": "CS-480",
        "prompt_tokens": 500,
        "completion_tokens": 250
    })
    assert res1.status_code == 201
    assert res1.json()["tokens_used"] == 10750

    res2 = client.post("/api/v1/tokens/events", json={
        "user_id": "sam",
        "subject_id": "CS-480",
        "prompt_tokens": 1200,
        "completion_tokens": 800
    })
    assert res2.status_code == 201
    assert res2.json()["tokens_used"] == 12750
    assert res2.json()["remaining_balance"] == 87250

    assert db_session.query(TokenLedgerDB).filter_by(user_id="sam").count() == 2


def test_story_8_1_first_event_provisions_daily_quota(client, db_session):
    """A user without a row today gets one with the default limit on the first event."""
    response = client.post("/api/v1/tokens/events", json={
        "user_id": "mateo",
        "subject_id": "CS-480",
        "prompt_tokens": 100,
        "completion_tokens": 50
    })
    assert response.status_code == 201
    data = response.json()
    assert data["tokens_used"] == 150
    assert data["token_limit"] == 100000
    assert data["subject_id"] == "CS-480"
    assert db_session.query(UserQuotaDB).filter_by(user_id="mateo").count() == 1


def test_story_8_1_invalid_negative_tokens_rejected(client, db_session):
    """Negative token counts fail schema validation with the ErrorBody envelope."""
    response = client.post("/api/v1/tokens/events", json={
        "user_id": "sam",
        "subject_id": "CS-480",
        "prompt_tokens": -10,
        "completion_tokens": 50
    })
    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "ERR_VALIDATION"
    assert body["details"]["errors"][0]["loc"] == ["body", "prompt_tokens"]
    assert db_session.query(TokenLedgerDB).count() == 0


def test_story_8_1_zero_tokens_event_rejected(client, db_session, seed_sam_quota):
    """0 prompt + 0 completion violates the domain rule (total > 0): 400, nothing recorded."""
    response = client.post("/api/v1/tokens/events", json={
        "user_id": "sam",
        "subject_id": "CS-480",
        "prompt_tokens": 0,
        "completion_tokens": 0
    })
    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "ERR_INVALID_TOKEN_COUNT"
    assert body["message"] == "Total tokens for an event must be strictly greater than zero"
    assert db_session.query(TokenLedgerDB).count() == 0
    assert db_session.query(UserQuotaDB).filter_by(user_id="sam").one().tokens_used == 10000


def test_story_8_1_oversized_token_count_rejected(client):
    """Values above the per-event bound are rejected (422), never overflowing the DB (500)."""
    response = client.post("/api/v1/tokens/events", json={
        "user_id": "sam",
        "subject_id": "CS-480",
        "prompt_tokens": 10**20,
        "completion_tokens": 1
    })
    assert response.status_code == 422
    assert response.json()["error_code"] == "ERR_VALIDATION"


def test_story_8_1_missing_subject_is_rejected(client, db_session):
    """Review decision 2026-10-26: subject_id is required; nothing is charged to a default subject."""
    response = client.post("/api/v1/tokens/events", json={
        "user_id": "sam",
        "prompt_tokens": 100,
        "completion_tokens": 50
    })
    assert response.status_code == 422
    assert response.json()["details"]["errors"][0]["loc"] == ["body", "subject_id"]
    assert db_session.query(TokenLedgerDB).count() == 0


@pytest.mark.parametrize("field,value", [
    ("prompt_tokens", "500"),
    ("prompt_tokens", 500.0),
    ("completion_tokens", True),
])
def test_story_8_1_token_counts_must_be_json_integers(client, field, value):
    """AC4: token counts are integers; strings, floats and booleans are not coerced."""
    payload = {"user_id": "sam", "subject_id": "CS-480", "prompt_tokens": 1, "completion_tokens": 1}
    payload[field] = value
    response = client.post("/api/v1/tokens/events", json=payload)
    assert response.status_code == 422
    assert response.json()["error_code"] == "ERR_VALIDATION"


@pytest.mark.parametrize("user_id", [" sam", "sam ", "s am"])
def test_story_8_1_user_id_with_whitespace_is_rejected(client, user_id):
    response = client.post("/api/v1/tokens/events", json={
        "user_id": user_id,
        "subject_id": "CS-480",
        "prompt_tokens": 1,
        "completion_tokens": 1
    })
    assert response.status_code == 422
