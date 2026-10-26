"""The Alembic migration produces exactly the schema the ORM expects."""
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from src.adapters.outbound.db import Base, build_engine
from src.adapters.outbound.migrations import run_migrations


def test_migration_matches_orm_metadata(tmp_path):
    url = f"sqlite:///{(tmp_path / 'migrated.db').as_posix()}"
    run_migrations(url)
    engine = build_engine(url)
    try:
        with engine.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
            inspector = inspect(conn)
            tables = set(inspector.get_table_names())
            quota_checks = {c["name"] for c in inspector.get_check_constraints("user_quotas")}
            ledger_checks = {c["name"] for c in inspector.get_check_constraints("token_ledger")}
    finally:
        engine.dispose()

    assert diff == []
    assert {"user_quotas", "token_ledger", "alembic_version"} <= tables
    assert {"ck_user_quotas_tokens_used_nonneg", "ck_user_quotas_token_limit_positive"} <= quota_checks
    assert {"ck_token_ledger_total_sum", "ck_token_ledger_total_positive"} <= ledger_checks


def test_migration_is_idempotent(tmp_path):
    url = f"sqlite:///{(tmp_path / 'twice.db').as_posix()}"
    run_migrations(url)
    run_migrations(url)  # already at head: no-op, no error
