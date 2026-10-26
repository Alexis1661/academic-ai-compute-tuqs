"""The Alembic migration produces exactly the schema the ORM expects."""
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text

from src.adapters.outbound.db import Base, build_engine
from src.adapters.outbound.migrations import PROJECT_ROOT, run_migrations


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


def test_counters_are_bigint_after_migration(tmp_path):
    """PRD FR-5 / AD-3: 64-bit counters (revision 0002)."""
    url = f"sqlite:///{(tmp_path / 'bigint.db').as_posix()}"
    run_migrations(url)
    engine = build_engine(url)
    try:
        with engine.connect() as conn:
            inspector = inspect(conn)
            quota = {c["name"]: str(c["type"]) for c in inspector.get_columns("user_quotas")}
            ledger = {c["name"]: str(c["type"]) for c in inspector.get_columns("token_ledger")}
    finally:
        engine.dispose()
    assert quota["tokens_used"] == quota["token_limit"] == "BIGINT"
    assert ledger["prompt_tokens"] == ledger["completion_tokens"] == ledger["total_tokens"] == "BIGINT"


def test_upgrade_from_0001_preserves_existing_rows(tmp_path):
    """0002 rebuilds the tables on SQLite (batch mode); data and constraints must survive."""
    url = f"sqlite:///{(tmp_path / 'upgrade.db').as_posix()}"
    config = Config()
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    config.attributes["configure_logger"] = False
    command.upgrade(config, "0001")

    engine = build_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO user_quotas (user_id, date, tokens_used, token_limit) "
                "VALUES ('sam', '2026-10-25', 10000, 100000)"
            ))
        run_migrations(url)
        with engine.connect() as conn:
            row = conn.execute(text("SELECT tokens_used, token_limit FROM user_quotas")).one()
            checks = {c["name"] for c in inspect(conn).get_check_constraints("user_quotas")}
    finally:
        engine.dispose()
    assert tuple(row) == (10000, 100000)
    assert "ck_user_quotas_tokens_used_nonneg" in checks


def test_percent_sign_in_database_url_does_not_break_migrations(tmp_path):
    """A URL-encoded character (e.g. in a password) must not hit configparser interpolation."""
    url = f"sqlite:///{(tmp_path / 'with%25percent.db').as_posix()}"
    run_migrations(url)
