import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.adapters.outbound.db import Base, UserQuotaDB, get_db
from src.composition import get_clock
from src.config import settings
from src.main import app
from tests.fixtures.fake_clock import FakeClock

# Never migrate the real DATABASE_URL from tests: no tuqs.db side effects on disk.
settings.AUTO_MIGRATE = False

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# In-memory SQLite database for deterministic, high-speed test execution
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture
def fake_clock():
    """Deterministic clock fixed at 2026-10-25T12:00:00Z."""
    return FakeClock()


@pytest.fixture
def db_session():
    """Provides a clean in-memory database session for each test."""
    Base.metadata.create_all(bind=test_engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def client(db_session, fake_clock):
    """FastAPI test client wired to the in-memory database and the fake clock."""
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_clock] = lambda: fake_clock
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def seed_quota(db_session, fake_clock):
    """Factory: seed a quota row for today's (fake) UTC date."""
    def _seed(user_id: str = "sam", tokens_used: int = 0, token_limit: int = 100000):
        record = UserQuotaDB(
            user_id=user_id,
            date=fake_clock.today_str(),
            tokens_used=tokens_used,
            token_limit=token_limit,
        )
        db_session.add(record)
        db_session.commit()
        return record
    return _seed


@pytest.fixture
def seed_sam_quota(seed_quota):
    """Sam with 10,000 used of 100,000 daily limit (Story 8.1 Given)."""
    return seed_quota("sam", tokens_used=10000)


@pytest.fixture
def seed_sam_exhausted_quota(seed_quota):
    """Sam with 100,000 used of 100,000 daily limit (Story 8.3 Given)."""
    return seed_quota("sam", tokens_used=100000)


@pytest.fixture
def seeded_quotas_from_fixture(seed_quota, fake_clock):
    """Loads tests/fixtures/seed_quotas.json (dated 2026-10-25, the fake clock's date)."""
    rows = json.loads((FIXTURES_DIR / "seed_quotas.json").read_text(encoding="utf-8"))
    for row in rows:
        assert row["date"] == fake_clock.today_str()
        seed_quota(row["user_id"], tokens_used=row["tokens_used"], token_limit=row["token_limit"])
    return rows
