"""
AD-1 / AD-4 on a real file-backed SQLite database (migrated with Alembic):
concurrent events never lose updates and the counter reconciles with the ledger.
"""
import threading

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from src.adapters.outbound.db import TokenLedgerDB, UserQuotaDB, build_engine
from src.adapters.outbound.migrations import run_migrations
from src.adapters.outbound.sql_repository import SQLQuotaRepository
from src.application.use_cases import IngestTokenEvent, TokenEventCommand
from src.domain.services import QuotaDomainService
from tests.fixtures.fake_clock import FakeClock

THREADS = 8
EVENTS_PER_THREAD = 25
TOKENS_PER_EVENT = 100


@pytest.fixture
def file_session_factory(tmp_path):
    url = f"sqlite:///{(tmp_path / 'atomic.db').as_posix()}"
    run_migrations(url)
    engine = build_engine(url)
    yield sessionmaker(bind=engine)
    engine.dispose()


def _ingest(session_factory, clock, n_events, errors):
    session = session_factory()
    try:
        use_case = IngestTokenEvent(SQLQuotaRepository(session), clock, QuotaDomainService(), 10**6)
        for _ in range(n_events):
            use_case.execute(TokenEventCommand("race", "CS-480", TOKENS_PER_EVENT, 0))
    except Exception as exc:  # surfaced by the assertion below
        errors.append(exc)
    finally:
        session.close()


def test_concurrent_events_do_not_lose_updates(file_session_factory):
    clock = FakeClock()
    errors = []
    threads = [
        threading.Thread(target=_ingest, args=(file_session_factory, clock, EVENTS_PER_THREAD, errors))
        for _ in range(THREADS)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    expected = THREADS * EVENTS_PER_THREAD * TOKENS_PER_EVENT
    with file_session_factory() as session:
        tokens_used = session.execute(
            select(UserQuotaDB.tokens_used).where(UserQuotaDB.user_id == "race")
        ).scalar_one()
        ledger_sum, ledger_rows = session.execute(
            select(func.sum(TokenLedgerDB.total_tokens), func.count())
            .where(TokenLedgerDB.user_id == "race")
        ).one()

    assert tokens_used == expected
    # AD-4 conservation: the daily counter equals the sum of its ledger deltas
    assert ledger_sum == tokens_used
    assert ledger_rows == THREADS * EVENTS_PER_THREAD


def test_failed_ledger_insert_rolls_back_counter(file_session_factory):
    """Counter increment and ledger append commit together or not at all."""
    clock = FakeClock()
    with file_session_factory() as session:
        repo = SQLQuotaRepository(session)
        use_case = IngestTokenEvent(repo, clock, QuotaDomainService(), 100000)
        first = use_case.execute(TokenEventCommand("sam", "CS-480", 10, 0))

        duplicate = first.entry  # same primary key -> ledger insert must fail
        with pytest.raises(Exception):
            repo.record_consumption(duplicate, date=clock.today_str(), default_limit=100000)

        tokens_used = session.execute(
            select(UserQuotaDB.tokens_used).where(UserQuotaDB.user_id == "sam")
        ).scalar_one()
        assert tokens_used == 10
