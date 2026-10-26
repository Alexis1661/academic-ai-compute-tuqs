from datetime import timezone
from typing import List

from sqlalchemy import select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from src.adapters.outbound.db import TokenLedgerDB, UserQuotaDB
from src.domain.exceptions import StorageUnavailableError
from src.domain.models import TokenLedgerEntry, UserQuota
from src.ports.repository import IQuotaRepository


def _dialect_insert(dialect_name: str):
    if dialect_name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif dialect_name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        raise NotImplementedError(f"Unsupported database dialect: {dialect_name}")
    return insert


class SQLQuotaRepository(IQuotaRepository):
    """
    SQLAlchemy outbound adapter implementing IQuotaRepository.
    Increments are computed by the database (tokens_used = tokens_used + :n), never
    read-modify-write in Python, so concurrent events cannot lose updates (AD-1).
    """

    def __init__(self, session: Session):
        self.session = session

    def get_quota_or_default(self, user_id: str, date: str, default_limit: int) -> UserQuota:
        record = self.session.execute(
            select(UserQuotaDB).where(UserQuotaDB.user_id == user_id, UserQuotaDB.date == date)
        ).scalar_one_or_none()
        if record is None:
            return UserQuota(user_id=user_id, date=date, token_limit=default_limit, tokens_used=0)
        return UserQuota(
            user_id=record.user_id,
            date=record.date,
            token_limit=record.token_limit,
            tokens_used=record.tokens_used,
        )

    def record_consumption(
        self, entry: TokenLedgerEntry, date: str, default_limit: int
    ) -> UserQuota:
        quotas = UserQuotaDB.__table__
        insert = _dialect_insert(self.session.get_bind().dialect.name)
        try:
            # 1. Provision the daily row if absent; a concurrent creator wins silently.
            self.session.execute(
                insert(quotas)
                .values(user_id=entry.user_id, date=date, tokens_used=0, token_limit=default_limit)
                .on_conflict_do_nothing(index_elements=["user_id", "date"])
            )
            # 2. Atomic in-database increment.
            tokens_used, token_limit = self.session.execute(
                update(quotas)
                .where(quotas.c.user_id == entry.user_id, quotas.c.date == date)
                .values(tokens_used=quotas.c.tokens_used + entry.total_tokens)
                .returning(quotas.c.tokens_used, quotas.c.token_limit)
            ).one()
            # 3. Append the ledger entry in the same transaction.
            self.session.add(
                TokenLedgerDB(
                    id=entry.id,
                    user_id=entry.user_id,
                    subject_id=entry.subject_id,
                    prompt_tokens=entry.prompt_tokens,
                    completion_tokens=entry.completion_tokens,
                    total_tokens=entry.total_tokens,
                    timestamp=entry.timestamp,
                )
            )
            self.session.commit()
        except OperationalError as exc:
            self.session.rollback()
            raise StorageUnavailableError() from exc
        except Exception:
            self.session.rollback()
            raise

        return UserQuota(
            user_id=entry.user_id, date=date, token_limit=token_limit, tokens_used=tokens_used
        )

    def get_ledger_entries(self, user_id: str, limit: int = 50) -> List[TokenLedgerEntry]:
        records = self.session.execute(
            select(TokenLedgerDB)
            .where(TokenLedgerDB.user_id == user_id)
            .order_by(TokenLedgerDB.timestamp.desc())
            .limit(limit)
        ).scalars()
        return [
            TokenLedgerEntry(
                id=r.id,
                user_id=r.user_id,
                subject_id=r.subject_id,
                prompt_tokens=r.prompt_tokens,
                completion_tokens=r.completion_tokens,
                total_tokens=r.total_tokens,
                # SQLite drops tzinfo on read; stored values are always UTC
                timestamp=r.timestamp if r.timestamp.tzinfo else r.timestamp.replace(tzinfo=timezone.utc),
            )
            for r in records
        ]

    def ping(self) -> bool:
        try:
            self.session.execute(text("SELECT 1"))
            return True
        except Exception:
            return False
