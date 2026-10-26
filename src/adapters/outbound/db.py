from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker

from src.config import settings

Base = declarative_base()


class UserQuotaDB(Base):
    """Daily user quota row. Mirrors migrations/versions/0001_initial_schema.py."""
    __tablename__ = "user_quotas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False)
    date = Column(String(10), nullable=False)
    tokens_used = Column(Integer, nullable=False, default=0)
    token_limit = Column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_user_date"),
        CheckConstraint("tokens_used >= 0", name="ck_user_quotas_tokens_used_nonneg"),
        CheckConstraint("token_limit > 0", name="ck_user_quotas_token_limit_positive"),
    )


class TokenLedgerDB(Base):
    """Append-only token consumption events (AD-4)."""
    __tablename__ = "token_ledger"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(64), nullable=False)
    subject_id = Column(String(64), nullable=False)
    prompt_tokens = Column(Integer, nullable=False)
    completion_tokens = Column(Integer, nullable=False)
    total_tokens = Column(Integer, nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("prompt_tokens >= 0", name="ck_token_ledger_prompt_nonneg"),
        CheckConstraint("completion_tokens >= 0", name="ck_token_ledger_completion_nonneg"),
        CheckConstraint(
            "total_tokens = prompt_tokens + completion_tokens", name="ck_token_ledger_total_sum"
        ),
        CheckConstraint("total_tokens > 0", name="ck_token_ledger_total_positive"),
        Index("ix_token_ledger_user_ts", "user_id", "timestamp"),
    )


def _connect_args(url: str) -> dict:
    # timeout: SQLite busy wait so concurrent writers queue instead of failing
    return {"check_same_thread": False, "timeout": 30} if url.startswith("sqlite") else {}


def build_engine(url: str):
    return create_engine(url, connect_args=_connect_args(url))


engine = build_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """Dependency provider for a request-scoped database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
