"""
Story 8.4 — reservation acceptance and concurrent transaction tests.

The historical red-phase console output is unavailable; this current green test
is not evidence that a test was executed before implementation.

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
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import pytest
from sqlalchemy import select

from src.adapters.outbound.db import UserQuotaDB, build_engine, get_db
from src.adapters.outbound.migrations import run_migrations
from src.composition import get_clock
from src.main import app


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


def test_bdd_scenario_atomic_adjudication_prevents_overdraft(tmp_path, fake_clock):
    """Race real independent SQLite connections against a migrated file database.

    Each HTTP dependency checks out its connection before a two-party barrier. This
    proves that the requests use distinct live DBAPI connections, unlike StaticPool.
    Repeating the exact 500/400/400 BDD case exercises the write race 20 times.
    SQLite serializes writes; this test does not claim PostgreSQL row-lock behavior.
    """
    url = f"sqlite:///{(tmp_path / 'reservation-race.db').as_posix()}"
    run_migrations(url)
    engine = build_engine(url)
    sessions = sessionmaker(bind=engine)
    barrier = threading.Barrier(2, timeout=10)
    connection_ids = []
    connection_lock = threading.Lock()

    def override_get_db():
        with sessions() as session:
            # Keep both physical connections checked out concurrently before either
            # request can execute its transaction.
            raw = session.connection().connection.driver_connection
            with connection_lock:
                connection_ids.append(id(raw))
            barrier.wait()
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_clock] = lambda: fake_clock
    try:
        with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as pool:
            for i in range(20):
                user = f"sam_student_{i}"
                with sessions.begin() as session:
                    session.add(UserQuotaDB(user_id=user, date=fake_clock.today_str(),
                                            tokens_used=500, token_limit=1000))
                first = pool.submit(client.post, "/api/v1/quota/reserve",
                                    json={"user_id": user, "requested_tokens": 400})
                second = pool.submit(client.post, "/api/v1/quota/reserve",
                                     json={"user_id": user, "requested_tokens": 400})
                responses = [first.result(timeout=20), second.result(timeout=20)]
                assert sorted(response.status_code for response in responses) == [200, 429]
                rejected = next(r.json() for r in responses if r.status_code == 429)
                approved = next(r.json() for r in responses if r.status_code == 200)
                assert (rejected["remaining_tokens"], rejected["requested_tokens"]) == (100, 400)
                assert (approved["remaining_tokens"], approved["reserved_tokens"]) == (100, 400)
                with sessions() as session:
                    used = session.execute(select(UserQuotaDB.tokens_used).where(
                        UserQuotaDB.user_id == user)).scalar_one()
                assert used == 900
        assert len(connection_ids) == 40
        assert all(connection_ids[i] != connection_ids[i + 1] for i in range(0, 40, 2))
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


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

