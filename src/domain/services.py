import uuid
from datetime import datetime

from src.domain.exceptions import InvalidTokenCountError
from src.domain.models import (
    AllowanceDecision,
    QuotaWarningInfo,
    TokenLedgerEntry,
    UserQuota,
    next_daily_reset,
)

DAILY_QUOTA_EXCEEDED = "DAILY_QUOTA_EXCEEDED"
DAILY_QUOTA_EXCEEDED_MESSAGE = "Daily token quota exhausted; resets at 00:00 UTC"


class QuotaDomainService:
    """
    Pure domain service: token validation, ledger entry creation, soft warning and
    allowance evaluation. Zero infrastructure or HTTP framework dependencies.
    """

    def __init__(self, warning_threshold: float = 0.80):
        self.warning_threshold = warning_threshold

    @property
    def threshold_percent(self) -> int:
        return round(self.warning_threshold * 100)

    @property
    def warning_status(self) -> str:
        return f"QUOTA_WARNING_{self.threshold_percent}_PERCENT"

    def validate_token_counts(self, prompt_tokens: int, completion_tokens: int) -> int:
        if prompt_tokens < 0 or completion_tokens < 0:
            raise InvalidTokenCountError("Prompt and completion tokens must be non-negative integers")
        total = prompt_tokens + completion_tokens
        if total <= 0:
            raise InvalidTokenCountError("Total tokens for an event must be strictly greater than zero")
        return total

    def build_ledger_entry(
        self,
        user_id: str,
        subject_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        occurred_at: datetime,
    ) -> TokenLedgerEntry:
        """Story 8.1: validates the event and builds its immutable ledger record."""
        total_tokens = self.validate_token_counts(prompt_tokens, completion_tokens)
        return TokenLedgerEntry(
            id=str(uuid.uuid4()),
            user_id=user_id,
            subject_id=subject_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            timestamp=occurred_at,
        )

    def crossed_warning_threshold(self, quota_after: UserQuota, added_tokens: int) -> bool:
        """True when this consumption moved usage from below the threshold to at/above it."""
        before = UserQuota(
            user_id=quota_after.user_id,
            date=quota_after.date,
            token_limit=quota_after.token_limit,
            tokens_used=quota_after.tokens_used - added_tokens,
        )
        return (
            not before.is_warning_threshold_reached(self.warning_threshold)
            and quota_after.is_warning_threshold_reached(self.warning_threshold)
        )

    def evaluate_soft_warning(self, quota: UserQuota) -> QuotaWarningInfo:
        """Story 8.2: evaluates whether consumption has hit or crossed the 80% threshold."""
        remaining = quota.remaining_balance
        threshold = f"{self.threshold_percent}%"

        if quota.is_warning_threshold_reached(self.warning_threshold):
            return QuotaWarningInfo(
                warning=True,
                threshold=threshold,
                threshold_percent=self.threshold_percent,
                remaining_tokens_before_denial=remaining,
                status=self.warning_status,
                message=(
                    f"Warning: {quota.tokens_used} of {quota.token_limit} daily tokens consumed. "
                    f"{remaining} tokens remain before hard denial."
                ),
            )
        return QuotaWarningInfo(
            warning=False,
            threshold=threshold,
            threshold_percent=self.threshold_percent,
            remaining_tokens_before_denial=remaining,
        )

    def evaluate_allowance(
        self, quota: UserQuota, requested_tokens: int, now: datetime
    ) -> AllowanceDecision:
        """
        Story 8.3: admits the request only if (tokens_used + requested) <= token_limit.
        Every denial carries a catalog reason code and a human-readable reason (AD-6).
        """
        if requested_tokens <= 0:
            raise InvalidTokenCountError("Requested tokens must be strictly positive")

        allowed = quota.can_consume(requested_tokens)
        return AllowanceDecision(
            allowed=allowed,
            reason=None if allowed else DAILY_QUOTA_EXCEEDED_MESSAGE,
            reason_code=None if allowed else DAILY_QUOTA_EXCEEDED,
            requested_tokens=requested_tokens,
            remaining_balance=quota.remaining_balance,
            current_used=quota.tokens_used,
            token_limit=quota.token_limit,
            resets_at=next_daily_reset(now),
        )
