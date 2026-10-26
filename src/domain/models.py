from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Optional


# Daily periods are UTC days (00:00 UTC reset, Annex Story 8.3). For Impl-1 this
# supersedes the America/Bogota period key of ARCHITECTURE.md AD-5 (review decision 2026-10-26).


def _as_utc(now: datetime) -> datetime:
    """Naive datetimes are treated as UTC, never as local time."""
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def period_key(now: datetime) -> str:
    """Daily quota period key (YYYY-MM-DD, UTC) for the instant `now`."""
    return _as_utc(now).date().isoformat()


def next_daily_reset(now: datetime) -> datetime:
    """Returns the next 00:00 UTC boundary after `now` (daily quota period reset, AD-5)."""
    today_utc = _as_utc(now).date()
    return datetime.combine(today_utc + timedelta(days=1), time.min, tzinfo=timezone.utc)


@dataclass(frozen=True)
class QuotaWarningInfo:
    """Soft-warning evaluation result for the 80% quota threshold (Story 8.2)."""
    warning: bool
    threshold: str
    threshold_percent: int
    remaining_tokens_before_denial: int
    status: Optional[str] = None
    message: Optional[str] = None


@dataclass(frozen=True)
class AllowanceDecision:
    """Hard denial decision for compute admission (Story 8.3)."""
    allowed: bool
    reason: Optional[str]
    reason_code: Optional[str]
    requested_tokens: int
    remaining_balance: int
    current_used: int
    token_limit: int
    resets_at: datetime


@dataclass(frozen=True)
class UserQuota:
    """Daily quota of one user for one UTC date (aggregate root)."""
    user_id: str
    date: str
    token_limit: int
    tokens_used: int = 0

    @property
    def remaining_balance(self) -> int:
        return max(0, self.token_limit - self.tokens_used)

    @property
    def consumption_ratio(self) -> float:
        if self.token_limit <= 0:
            return 1.0
        return self.tokens_used / self.token_limit

    @property
    def percentage_used(self) -> float:
        return round(self.consumption_ratio * 100.0, 2)

    def is_warning_threshold_reached(self, threshold: float = 0.80) -> bool:
        return self.consumption_ratio >= threshold

    def can_consume(self, requested_tokens: int) -> bool:
        return (self.tokens_used + requested_tokens) <= self.token_limit


@dataclass(frozen=True)
class TokenLedgerEntry:
    """Immutable, append-only ledger record of token consumption (Story 8.1, AD-4)."""
    id: str
    user_id: str
    subject_id: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    timestamp: datetime
