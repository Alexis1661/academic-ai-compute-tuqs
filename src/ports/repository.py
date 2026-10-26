from abc import ABC, abstractmethod
from typing import List

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
    def get_ledger_entries(self, user_id: str, limit: int = 50) -> List[TokenLedgerEntry]:
        """Query recent ledger transactions for a user, newest first."""

    @abstractmethod
    def ping(self) -> bool:
        """Return True when the store answers a trivial query."""
