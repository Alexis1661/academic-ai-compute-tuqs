from abc import ABC, abstractmethod

from src.domain.models import TokenLedgerEntry, UserQuota


class IQuotaRepository(ABC):
    """Abstract port for User Quotas and Token Ledger persistence."""

    @abstractmethod
    def get_quota_or_default(self, user_id: str, date: str, default_limit: int) -> UserQuota:
        """Read the quota for user/date; if absent, return an unused default quota without writing."""

    @abstractmethod
    def record_consumption(
        self, entry: TokenLedgerEntry, date: str, default_limit: int
    ) -> UserQuota:
        """
        Atomically (one transaction, AD-1): create the quota row if absent, increment
        tokens_used by entry.total_tokens in the database, and append the ledger entry.
        Returns the quota state after the increment.
        """

    @abstractmethod
    def reserve_tokens(
        self, user_id: str, date: str, requested_tokens: int, default_limit: int
    ) -> UserQuota:
        """
        Story 8.4 / AD-19: atomically reserve `requested_tokens` from the daily bucket.

        Uses a database-level conditional update (no read-modify-write in Python) so that
        two simultaneous requests against a near-empty bucket cannot both succeed.

        Returns the updated UserQuota on success.
        Raises QuotaExceededError when tokens_used + requested > token_limit.
        Raises StorageUnavailableError on infrastructure failure.
        """

    @abstractmethod
    def bulk_reset_daily_quotas(self, period: str) -> int:
        """Create missing current-period rows from prior limits, preserving history.

        Existing current-period usage must not be erased; return rows created.
        """

    @abstractmethod
    def ping(self) -> bool:
        """Return True when the store answers a trivial query."""
