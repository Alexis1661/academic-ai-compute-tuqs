import pytest

from src.adapters.outbound.db import UserQuotaDB


def test_story_8_2_bdd_scenario_soft_warning_at_82_percent(client, seed_quota):
    """
    BDD Acceptance Scenario (Story 8.2):
    Given user "sam" has a daily limit of 100,000 tokens
    When Sam's total consumption reaches 82,000 tokens
    Then the quota service returns warning status "QUOTA_WARNING_80_PERCENT"
    And indicates 18,000 tokens remain before hard denial
    And sets response header X-Quota-Warning: 80 (PRD FR-11)
    """
    seed_quota("sam", tokens_used=82000)

    response = client.get("/api/v1/tokens/balance/sam")
    assert response.status_code == 200

    data = response.json()
    assert data["user_id"] == "sam"
    assert data["date"] == "2026-10-25"
    assert data["tokens_used"] == 82000
    assert data["token_limit"] == 100000
    assert data["remaining_balance"] == 18000
    assert data["percentage_used"] == 82.0

    warning = data["warning"]
    assert warning["warning"] is True
    assert warning["threshold"] == "80%"
    assert warning["status"] == "QUOTA_WARNING_80_PERCENT"
    assert warning["remaining_tokens_before_denial"] == 18000
    assert "Warning: 82000 of 100000" in warning["message"]

    assert response.headers["X-Quota-Warning"] == "80"
    assert response.headers["X-Quota-Remaining"] == "18000"


def test_story_8_2_crossing_80_percent_during_ingestion(client, seed_quota):
    """An event moving usage from 79,000 to 82,000 returns the warning in body and header."""
    seed_quota("sam", tokens_used=79000)

    response = client.post("/api/v1/tokens/events", json={
        "user_id": "sam",
        "subject_id": "CS-480",
        "prompt_tokens": 2000,
        "completion_tokens": 1000
    })
    assert response.status_code == 201

    data = response.json()
    assert data["tokens_used"] == 82000
    assert data["remaining_balance"] == 18000
    assert data["warning"]["warning"] is True
    assert data["warning"]["status"] == "QUOTA_WARNING_80_PERCENT"
    assert data["warning"]["remaining_tokens_before_denial"] == 18000
    assert response.headers["X-Quota-Warning"] == "80"


def test_story_8_2_below_80_percent_no_warning(client, seed_quota):
    """Consumption strictly below 80% (75,000) does NOT trigger a warning."""
    seed_quota("sam", tokens_used=75000)

    response = client.get("/api/v1/tokens/balance/sam")
    assert response.status_code == 200

    data = response.json()
    assert data["warning"]["warning"] is False
    assert data["warning"]["status"] is None
    assert "X-Quota-Warning" not in response.headers
    assert response.headers["X-Quota-Remaining"] == "25000"


def test_story_8_2_exact_80_percent_boundary_triggers_warning(client, seed_quota):
    """Exactly 80.0% (80,000 / 100,000) triggers the soft warning."""
    seed_quota("sam", tokens_used=80000)

    response = client.get("/api/v1/tokens/balance/sam")
    assert response.status_code == 200
    assert response.json()["warning"]["warning"] is True
    assert response.json()["warning"]["status"] == "QUOTA_WARNING_80_PERCENT"
    assert response.headers["X-Quota-Warning"] == "80"


def test_story_8_2_warning_header_on_allowance_checks(client, seed_quota):
    """FR-11: the header is returned on every quota response while usage >= 80%."""
    seed_quota("sam", tokens_used=90000)

    response = client.post(
        "/api/v1/tokens/check-allowance", json={"user_id": "sam", "requested_tokens": 500}
    )
    assert response.status_code == 200
    assert response.json()["allowed"] is True
    assert response.headers["X-Quota-Warning"] == "80"


def test_story_8_2_balance_query_is_read_only(client, db_session):
    """Querying an unknown user reports the default quota without creating a row."""
    response = client.get("/api/v1/tokens/balance/ghost_user_99")
    assert response.status_code == 200
    assert response.json()["tokens_used"] == 0
    assert response.json()["token_limit"] == 100000
    assert db_session.query(UserQuotaDB).count() == 0


def test_story_8_2_seeded_fixture_quotas(client, seeded_quotas_from_fixture):
    """Balances for every row in tests/fixtures/seed_quotas.json are served as seeded."""
    for row in seeded_quotas_from_fixture:
        data = client.get(f"/api/v1/tokens/balance/{row['user_id']}").json()
        assert data["tokens_used"] == row["tokens_used"]
        assert data["token_limit"] == row["token_limit"]
        assert data["remaining_balance"] == row["token_limit"] - row["tokens_used"]


@pytest.mark.parametrize("user_id", ["u" * 65, "s%20am"])
def test_story_8_2_balance_path_user_id_is_validated(client, user_id):
    """Path ids follow the same 1-64 chars, no-whitespace rule as body ids."""
    response = client.get(f"/api/v1/tokens/balance/{user_id}")
    assert response.status_code == 422
    assert response.json()["error_code"] == "ERR_VALIDATION"
