from sqlalchemy import select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from src.adapters.outbound.db import TokenLedgerDB, UserQuotaDB
from src.domain.exceptions import QuotaExceededError, StorageUnavailableError
from src.domain.models import TokenLedgerEntry, UserQuota
from src.ports.repository import IQuotaRepository

# Chunk size for Story 8.5 bulk reset: keeps each UPDATE statement small enough
# to avoid long-held table locks while still being efficient.
_RESET_CHUNK_SIZE = 500


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
        try:
            record = self.session.execute(
                select(UserQuotaDB).where(UserQuotaDB.user_id == user_id, UserQuotaDB.date == date)
            ).scalar_one_or_none()
        except OperationalError as exc:
            # AD-7: never answer a quota read from anything but the store
            raise StorageUnavailableError() from exc
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

    def reserve_tokens(
        self, user_id: str, date: str, requested_tokens: int, default_limit: int
    ) -> UserQuota:
        """
        Story 8.4 / AD-19: atomically reserve tokens using a conditional UPDATE.

        Strategy (works on both SQLite and PostgreSQL without row-level SELECT FOR UPDATE):
          1. Upsert the daily quota row (create if absent).
          2. Conditional UPDATE: only increment when the new total would not exceed the limit.
             The WHERE clause is the guard: tokens_used + :n <= token_limit.
          3. If the UPDATE matched 0 rows the bucket is exhausted → QuotaExceededError.
          4. The final SELECT reads the authoritative post-update state.

        No Python-level read-modify-write means two racing threads cannot both pass the guard
        and both succeed — the database serialises the conditional writes.
        """
        quotas = UserQuotaDB.__table__
        insert = _dialect_insert(self.session.get_bind().dialect.name)
        try:
            # Step 1: provision the daily row if absent
            self.session.execute(
                insert(quotas)
                .values(
                    user_id=user_id,
                    date=date,
                    tokens_used=0,
                    token_limit=default_limit,
                )
                .on_conflict_do_nothing(index_elements=["user_id", "date"])
            )

            # Step 2: conditional atomic increment — guard is in the WHERE clause
            result = self.session.execute(
                update(quotas)
                .where(
                    quotas.c.user_id == user_id,
                    quotas.c.date == date,
                    # The overdraft guard: only proceed if the resulting balance stays >= 0
                    quotas.c.tokens_used + requested_tokens <= quotas.c.token_limit,
                )
                .values(tokens_used=quotas.c.tokens_used + requested_tokens)
                .returning(quotas.c.tokens_used, quotas.c.token_limit)
            ).one_or_none()

            if result is None:
                # Guard condition failed: insufficient balance. Read current state to build error.
                current = self.session.execute(
                    select(UserQuotaDB).where(
                        UserQuotaDB.user_id == user_id, UserQuotaDB.date == date
                    )
                ).scalar_one_or_none()
                remaining = (
                    max(0, current.token_limit - current.tokens_used)
                    if current is not None
                    else default_limit
                )
                raise QuotaExceededError(
                    remaining_tokens=remaining,
                    requested_tokens=requested_tokens,
                )

            self.session.commit()
            tokens_used, token_limit = result
            return UserQuota(
                user_id=user_id,
                date=date,
                token_limit=token_limit,
                tokens_used=tokens_used,
            )

        except QuotaExceededError:
            raise
        except OperationalError as exc:
            self.session.rollback()
            raise StorageUnavailableError() from exc
        except Exception:
            self.session.rollback()
            raise

    def bulk_reset_daily_quotas(self, period: str) -> int:
        """
        Story 8.5: chunked bulk UPDATE reset for high-throughput midnight processing.

        Updates are issued in batches of _RESET_CHUNK_SIZE rows so the write lock
        is held for microseconds per chunk, leaving concurrent read queries unblocked.

        Returns the total number of rows reset.
        """
        quotas = UserQuotaDB.__table__
        total_reset = 0
        try:
            while True:
                # Fetch a batch of primary-key IDs to reset
                ids = self.session.execute(
                    select(quotas.c.id)
                    .where(quotas.c.date == period, quotas.c.tokens_used > 0)
                    .limit(_RESET_CHUNK_SIZE)
                ).scalars().all()

                if not ids:
                    break

                self.session.execute(
                    update(quotas)
                    .where(quotas.c.id.in_(ids))
                    .values(tokens_used=0)
                )
                self.session.commit()
                total_reset += len(ids)

        except OperationalError as exc:
            self.session.rollback()
            raise StorageUnavailableError() from exc
        except Exception:
            self.session.rollback()
            raise

        return total_reset

    def ping(self) -> bool:
        try:
            self.session.execute(text("SELECT 1"))
            return True
        except Exception:
            return False
