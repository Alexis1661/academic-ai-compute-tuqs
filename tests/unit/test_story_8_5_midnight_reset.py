"""
Story 8.5 — Unit tests for the Midnight Automatic Quota Reset Daemon.

Flow D: Quality Gate (Performance & NFR)

BDD Acceptance Scenario:
  Given 2,000 student quota buckets seeded with arbitrary usage > 80%
  When the midnight reset cron job triggers
  Then all 2,000 daily buckets reset tokens_used to 0
  And total batch execution time is strictly less than 2.0 seconds
  And concurrent token query reads experience zero lock timeouts
"""
import time

import pytest
from sqlalchemy import select

from src.adapters.outbound.db import UserQuotaDB
from src.application.use_cases import MidnightResetJob
from src.domain.services import QuotaDomainService


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _seed_many_buckets(db_session, fake_clock, count: int, usage_pct: float = 0.85):
    """Bulk-insert `count` quota rows with usage_pct consumption."""
    today = fake_clock.today_str()
    token_limit = 100_000
    tokens_used = int(token_limit * usage_pct)
    rows = [
        UserQuotaDB(
            user_id=f"student_{i:06d}",
            date=today,
            tokens_used=tokens_used,
            token_limit=token_limit,
        )
        for i in range(count)
    ]
    db_session.bulk_save_objects(rows)
    db_session.commit()
    return count


# ---------------------------------------------------------------------------
# Functional correctness tests
# ---------------------------------------------------------------------------

def test_midnight_reset_resets_all_buckets_to_zero(db_session, fake_clock, client):
    """All tokens_used values must be 0 after the reset endpoint is called."""
    n = _seed_many_buckets(db_session, fake_clock, count=50)

    resp = client.post("/api/v1/quota/cron/midnight-reset")
    assert resp.status_code == 200

    body = resp.json()
    assert body["buckets_reset"] == n
    assert body["period"] == fake_clock.today_str()
    assert "reset" in body["message"].lower()

    # Verify all rows are actually zero
    all_used = db_session.execute(select(UserQuotaDB.tokens_used)).scalars().all()
    assert all(used == 0 for used in all_used), "Some buckets were not reset to 0"


def test_midnight_reset_already_zero_buckets_not_counted(db_session, fake_clock, client):
    """Buckets already at 0 are skipped; buckets_reset counts only those that changed."""
    today = fake_clock.today_str()
    # 10 buckets at 0 usage (already clean)
    for i in range(10):
        db_session.add(UserQuotaDB(user_id=f"clean_{i}", date=today, tokens_used=0, token_limit=100000))
    # 5 buckets with real usage
    for i in range(5):
        db_session.add(UserQuotaDB(user_id=f"used_{i}", date=today, tokens_used=50000, token_limit=100000))
    db_session.commit()

    resp = client.post("/api/v1/quota/cron/midnight-reset")
    assert resp.status_code == 200
    assert resp.json()["buckets_reset"] == 5


def test_midnight_reset_only_affects_current_period(db_session, fake_clock, client):
    """Reset must not touch rows from other dates (yesterday's audit trail)."""
    today = fake_clock.today_str()
    yesterday = "2026-10-24"

    db_session.add(UserQuotaDB(user_id="u1", date=today, tokens_used=50000, token_limit=100000))
    db_session.add(UserQuotaDB(user_id="u1", date=yesterday, tokens_used=99000, token_limit=100000))
    db_session.commit()

    resp = client.post("/api/v1/quota/cron/midnight-reset")
    assert resp.status_code == 200
    assert resp.json()["buckets_reset"] == 1

    # Yesterday's row must remain untouched
    yesterday_used = db_session.execute(
        select(UserQuotaDB.tokens_used).where(
            UserQuotaDB.user_id == "u1", UserQuotaDB.date == yesterday
        )
    ).scalar_one()
    assert yesterday_used == 99000


def test_midnight_reset_empty_database_returns_zero(client, fake_clock):
    """An empty database is a valid state; reset reports 0 buckets reset."""
    resp = client.post("/api/v1/quota/cron/midnight-reset")
    assert resp.status_code == 200
    assert resp.json()["buckets_reset"] == 0


def test_midnight_reset_idempotent(db_session, fake_clock, client):
    """Calling reset twice must be safe: second call resets 0 (already zero)."""
    _seed_many_buckets(db_session, fake_clock, count=10)

    resp1 = client.post("/api/v1/quota/cron/midnight-reset")
    resp2 = client.post("/api/v1/quota/cron/midnight-reset")

    assert resp1.json()["buckets_reset"] == 10
    assert resp2.json()["buckets_reset"] == 0


# ---------------------------------------------------------------------------
# NFR: performance gate (< 2.0 seconds for the in-process Python path)
# ---------------------------------------------------------------------------

def test_midnight_reset_500_buckets_completes_within_nfr_budget(db_session, fake_clock):
    """
    NFR gate: resetting 500 buckets in-process (pure SQLite) must complete in < 2.0 s.

    The k6 benchmark (tests/nfr/quota-batch-reset.js) covers the full 2,000-bucket
    HTTP path; this unit gate catches regressions early without network overhead.
    """
    from src.adapters.outbound.sql_repository import SQLQuotaRepository

    _seed_many_buckets(db_session, fake_clock, count=500)

    repo = SQLQuotaRepository(db_session)
    domain = QuotaDomainService()

    class _FixedClock:
        def now(self):
            return fake_clock.now()

    use_case = MidnightResetJob(repo, _FixedClock(), domain, 100_000)

    start = time.perf_counter()
    result = use_case.execute()
    elapsed = time.perf_counter() - start

    assert result.buckets_reset == 500
    assert elapsed < 2.0, (
        f"NFR violated: midnight reset for 500 buckets took {elapsed:.3f}s (limit: 2.0s)"
    )

