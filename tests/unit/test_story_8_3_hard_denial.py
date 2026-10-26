import pytest

from src.adapters.outbound.db import UserQuotaDB


def test_story_8_3_bdd_scenario_hard_denial_when_exhausted(client, seed_sam_exhausted_quota):
    """
    BDD Acceptance Scenario (Story 8.3):
    Given user "sam" has consumed 100,000 of 100,000 daily tokens
    When a service checks allowance for Sam requesting 500 tokens
    Then the quota service returns "allowed: false"
    And specifies reason "Daily token quota exhausted; resets at 00:00 UTC"
    """
    response = client.post(
        "/api/v1/tokens/check-allowance", json={"user_id": "sam", "requested_tokens": 500}
    )
    assert response.status_code == 200

    data = response.json()
    assert data["allowed"] is False
    assert data["reason"] == "Daily token quota exhausted; resets at 00:00 UTC"
    assert data["reason_code"] == "DAILY_QUOTA_EXCEEDED"
    assert data["requested_tokens"] == 500
    assert data["remaining_balance"] == 0
    assert data["tokens_used"] == 100000
    assert data["token_limit"] == 100000
    assert data["resets_at"] == "2026-10-26T00:00:00Z"


def test_story_8_3_allowed_when_within_budget(client, seed_sam_quota):
    """Requests well within the ceiling return allowed=True with no reason."""
    response = client.post(
        "/api/v1/tokens/check-allowance", json={"user_id": "sam", "requested_tokens": 5000}
    )
    assert response.status_code == 200

    data = response.json()
    assert data["allowed"] is True
    assert data["reason"] is None
    assert data["reason_code"] is None
    assert data["remaining_balance"] == 90000
    assert data["tokens_used"] == 10000
    assert data["token_limit"] == 100000


def test_story_8_3_boundary_condition_exact_ceiling_allowed(client, seed_quota):
    """99,500 + 500 = 100,000 lands exactly on the ceiling and must be ALLOWED."""
    seed_quota("sam", tokens_used=99500)

    response = client.post(
        "/api/v1/tokens/check-allowance", json={"user_id": "sam", "requested_tokens": 500}
    )
    assert response.status_code == 200
    assert response.json()["allowed"] is True
    assert response.json()["remaining_balance"] == 500


def test_story_8_3_boundary_condition_one_token_over_denied(client, seed_quota):
    """99,501 + 500 = 100,001 exceeds the ceiling by one token: zero tolerance, DENIED."""
    seed_quota("sam", tokens_used=99501)

    response = client.post(
        "/api/v1/tokens/check-allowance", json={"user_id": "sam", "requested_tokens": 500}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["allowed"] is False
    assert data["reason_code"] == "DAILY_QUOTA_EXCEEDED"
    assert data["reason"] == "Daily token quota exhausted; resets at 00:00 UTC"


@pytest.mark.parametrize("requested", [0, -100])
def test_story_8_3_invalid_zero_or_negative_request(client, requested):
    """Zero or negative requested tokens fail validation with the ErrorBody envelope."""
    response = client.post(
        "/api/v1/tokens/check-allowance", json={"user_id": "sam", "requested_tokens": requested}
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "ERR_VALIDATION"


def test_story_8_3_new_day_resets_allowance(client, seed_sam_exhausted_quota, fake_clock):
    """After 00:00 UTC the exhausted quota no longer applies (new period key, AD-5)."""
    fake_clock.advance(hours=12)  # 2026-10-26T00:00:00Z

    response = client.post(
        "/api/v1/tokens/check-allowance", json={"user_id": "sam", "requested_tokens": 500}
    )
    data = response.json()
    assert data["allowed"] is True
    assert data["tokens_used"] == 0
    assert data["resets_at"] == "2026-10-27T00:00:00Z"


def test_story_8_3_allowance_check_is_read_only(client, db_session):
    """Checking allowance never provisions or mutates quota rows."""
    client.post("/api/v1/tokens/check-allowance", json={"user_id": "lucas", "requested_tokens": 10})
    assert db_session.query(UserQuotaDB).count() == 0
