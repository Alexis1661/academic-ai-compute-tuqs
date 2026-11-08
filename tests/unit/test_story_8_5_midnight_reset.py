"""Midnight rollover preserves ledger-period consistency and fails closed."""
from datetime import timedelta

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from src.adapters.outbound.db import UserQuotaDB
from src.config import settings


@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", SecretStr("test-admin-secret"))
    return {"X-Admin-Token": "test-admin-secret"}


def seed(db_session, fake_clock, count=1, used=85000, days_ago=1):
    day = (fake_clock.now() - timedelta(days=days_ago)).date().isoformat()
    db_session.add_all([UserQuotaDB(user_id=f"student_{i}", date=day,
                       tokens_used=used, token_limit=100000) for i in range(count)])
    db_session.commit()
    return day


def test_rollover_creates_new_rows_preserves_history(db_session, fake_clock, client, admin):
    previous = seed(db_session, fake_clock, 50)
    response = client.post("/api/v1/quota/cron/midnight-reset", headers=admin)
    assert response.status_code == 200
    assert response.json()["buckets_reset"] == 50
    db_session.expire_all()
    old = db_session.execute(select(UserQuotaDB).where(UserQuotaDB.date == previous)).scalars().all()
    current = db_session.execute(select(UserQuotaDB).where(UserQuotaDB.date == fake_clock.today_str())).scalars().all()
    assert len(old) == len(current) == 50
    assert all(row.tokens_used == 85000 for row in old)
    assert all(row.tokens_used == 0 and row.token_limit == 100000 for row in current)


def test_rollover_never_erases_current_usage_and_is_idempotent(db_session, fake_clock, client, admin):
    seed(db_session, fake_clock)
    db_session.add(UserQuotaDB(user_id="student_0", date=fake_clock.today_str(), tokens_used=123, token_limit=100000))
    db_session.commit()
    for _ in range(2):
        response = client.post("/api/v1/quota/cron/midnight-reset", headers=admin)
        assert response.status_code == 200
        assert response.json()["buckets_reset"] == 0
    db_session.expire_all()
    row = db_session.execute(select(UserQuotaDB).where(UserQuotaDB.date == fake_clock.today_str())).scalar_one()
    assert row.tokens_used == 123


def test_rollover_uses_latest_previous_limit(db_session, fake_clock, client, admin):
    seed(db_session, fake_clock, days_ago=2)
    seed(db_session, fake_clock, days_ago=1)
    yesterday = (fake_clock.now() - timedelta(days=1)).date().isoformat()
    row = db_session.execute(select(UserQuotaDB).where(UserQuotaDB.date == yesterday)).scalar_one()
    row.token_limit = 200000
    db_session.commit()
    assert client.post("/api/v1/quota/cron/midnight-reset", headers=admin).json()["buckets_reset"] == 1
    current = db_session.execute(select(UserQuotaDB).where(UserQuotaDB.date == fake_clock.today_str())).scalar_one()
    assert current.token_limit == 200000


def test_empty_rollover(client, admin):
    assert client.post("/api/v1/quota/cron/midnight-reset", headers=admin).json()["buckets_reset"] == 0


def test_administration_fails_closed(client, monkeypatch, admin):
    reset = "/api/v1/quota/cron/midnight-reset"
    seed_url = "/api/v1/quota/cron/seed-test-buckets"
    payload = {"count": 2}
    monkeypatch.setattr(settings, "ENABLE_TEST_SEED", True)
    assert client.post(reset).status_code == 403
    assert client.post(reset, headers={"X-Admin-Token": "wrong"}).status_code == 403
    assert client.post(seed_url, json=payload).status_code == 403
    monkeypatch.setattr(settings, "ADMIN_TOKEN", None)
    assert client.post(reset, headers=admin).status_code == 403
    monkeypatch.setattr(settings, "ADMIN_TOKEN", SecretStr("test-admin-secret"))
    monkeypatch.setattr(settings, "ENABLE_TEST_SEED", False)
    assert client.post(seed_url, json=payload, headers=admin).status_code == 404
    monkeypatch.setattr(settings, "ENABLE_TEST_SEED", True)
    monkeypatch.setattr(settings, "APP_ENV", "production")
    assert client.post(seed_url, json=payload, headers=admin).status_code == 404


def test_seed_reports_actual_insertions_and_previous_period(client, fake_clock, monkeypatch, admin):
    monkeypatch.setattr(settings, "ENABLE_TEST_SEED", True)
    monkeypatch.setattr(settings, "APP_ENV", "test")
    url = "/api/v1/quota/cron/seed-test-buckets"
    first = client.post(url, json={"count": 2}, headers=admin)
    second = client.post(url, json={"count": 2}, headers=admin)
    assert first.status_code == second.status_code == 201
    assert first.json()["seeded"] == 2
    assert second.json()["seeded"] == 0
    assert first.json()["period"] == (fake_clock.now() - timedelta(days=1)).date().isoformat()
    assert client.post("/api/v1/quota/cron/midnight-reset", headers=admin).json()["buckets_reset"] == 2


def test_rollover_preserves_real_consumption_and_ledger(client, db_session, fake_clock, admin):
    from src.adapters.outbound.db import TokenLedgerDB
    prior_day = fake_clock.today_str()
    response = client.post("/api/v1/tokens/events", json={
        "user_id": "sam_history", "subject_id": "CS101", "prompt_tokens": 120,
        "completion_tokens": 30})
    assert response.status_code == 201
    fake_clock.advance(days=1)
    response = client.post("/api/v1/quota/cron/midnight-reset", headers=admin)
    assert response.status_code == 200
    assert response.json()["buckets_reset"] == 1
    db_session.expire_all()
    rows = db_session.execute(select(UserQuotaDB).where(UserQuotaDB.user_id == "sam_history")).scalars().all()
    assert {r.date: r.tokens_used for r in rows} == {prior_day: 150, fake_clock.today_str(): 0}
    ledger = db_session.execute(select(TokenLedgerDB).where(TokenLedgerDB.user_id == "sam_history")).scalar_one()
    assert ledger.total_tokens == 150
