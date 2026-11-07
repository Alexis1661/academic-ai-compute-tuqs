"""
Story 8.4 — ATDD Red Phase (Flow A: ATDD-First).

Invariant AD-19: Quota reservation and balance checking must be strictly atomic.
Zero overdrafts permitted under concurrent requests.

BDD Acceptance Scenario:
  Given user "sam_student" has a daily quota balance of exactly 500 tokens
  When Request A (400 tokens) and Request B (400 tokens) arrive at the same millisecond
  Then exactly one request returns HTTP 200 with tokens successfully reserved
  And the other request returns HTTP 429 Quota Exceeded
  And the database balance remains at exactly 100 tokens (never negative)
"""
import threading

import pytest
from sqlalchemy import select

from src.adapters.outbound.db import UserQuotaDB


@pytest.fixture
def seed_sam_student_500(db_session, fake_clock):
    """sam_student with exactly 500 tokens remaining (500 used of 1000 limit)."""
    record = UserQuotaDB(
        user_id="sam_student",
        date=fake_clock.today_str(),
        tokens_used=500,
        token_limit=1000,
    )
    db_session.add(record)
    db_session.commit()
    return record


def _post_reserve(client, user_id: str, tokens: int, results: list, index: int) -> None:
    """Thread target: POST to /api/v1/quota/reserve and store (status_code, json)."""
    resp = client.post(
        "/api/v1/quota/reserve",
        json={"user_id": user_id, "requested_tokens": tokens},
    )
    results[index] = (resp.status_code, resp.json())


def test_bdd_scenario_atomic_adjudication_prevents_overdraft(
    client, seed_sam_student_500, db_session, fake_clock
):
    """
    BDD: Atomic adjudication prevents quota overdraft.

    Two simultaneous 400-token requests against a 500-token bucket must result in
    exactly one approval (HTTP 200) and one rejection (HTTP 429), leaving the balance
    at exactly 100 tokens — never negative.
    """
    results = [None, None]
    barrier = threading.Barrier(2)

    def request_with_barrier(index: int) -> None:
        barrier.wait()  # synchronize both threads to fire simultaneously
        _post_reserve(client, "sam_student", 400, results, index)

    threads = [
        threading.Thread(target=request_with_barrier, args=(i,))
        for i in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    status_codes = {results[0][0], results[1][0]}
    assert 200 in status_codes, f"Expected one HTTP 200; got {status_codes}"
    assert 429 in status_codes, f"Expected one HTTP 429; got {status_codes}"

    # Verify the rejected response body
    rejected = next(body for code, body in results if code == 429)
    assert rejected["remaining_tokens"] == 100
    assert rejected["requested_tokens"] == 400

    # Verify the approved response body
    approved = next(body for code, body in results if code == 200)
    assert approved["reserved_tokens"] == 400
    assert approved["remaining_tokens"] == 100

    # Database invariant: balance must be exactly 100, never negative
    tokens_used = db_session.execute(
        select(UserQuotaDB.tokens_used).where(UserQuotaDB.user_id == "sam_student")
    ).scalar_one()
    assert tokens_used == 900, (
        f"Expected tokens_used=900 (500 initial + 400 reserved), got {tokens_used}. "
        "Overdraft guard failed."
    )


def test_reservation_decrements_balance_by_exact_amount(client, seed_sam_student_500, db_session, fake_clock):
    """Single reservation of 400 tokens leaves balance at 100."""
    resp = client.post(
        "/api/v1/quota/reserve",
        json={"user_id": "sam_student", "requested_tokens": 400},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["reserved_tokens"] == 400
    assert body["remaining_tokens"] == 100

    tokens_used = db_session.execute(
        select(UserQuotaDB.tokens_used).where(UserQuotaDB.user_id == "sam_student")
    ).scalar_one()
    assert tokens_used == 900


def test_reservation_rejected_when_insufficient_balance(client, seed_sam_student_500, fake_clock):
    """A single request for more tokens than remaining balance returns HTTP 429."""
    resp = client.post(
        "/api/v1/quota/reserve",
        json={"user_id": "sam_student", "requested_tokens": 600},
    )
    assert resp.status_code == 429
    body = resp.json()
    assert body["remaining_tokens"] == 500
    assert body["requested_tokens"] == 600


def test_reservation_invalid_zero_tokens(client, seed_sam_student_500):
    """Zero requested_tokens must be rejected with HTTP 422."""
    resp = client.post(
        "/api/v1/quota/reserve",
        json={"user_id": "sam_student", "requested_tokens": 0},
    )
    assert resp.status_code == 422


def test_reservation_new_user_uses_default_limit(client, fake_clock):
    """A user with no quota row gets a fresh bucket with the default limit."""
    resp = client.post(
        "/api/v1/quota/reserve",
        json={"user_id": "new_user", "requested_tokens": 100},
    )
    # With default limit of 100,000 tokens, 100 tokens must be approved
    assert resp.status_code == 200

