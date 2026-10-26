"""
Application layer: one use case per story. Depends only on domain objects and ports,
so the HTTP adapter stays thin and the use cases can be tested without FastAPI.
"""
import logging
from dataclasses import dataclass
from datetime import datetime

from src.domain.models import (
    AllowanceDecision,
    QuotaWarningInfo,
    TokenLedgerEntry,
    UserQuota,
    next_daily_reset,
)
from src.domain.services import QuotaDomainService
from src.ports.clock import IClock
from src.ports.repository import IQuotaRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TokenEventCommand:
    user_id: str
    subject_id: str
    prompt_tokens: int
    completion_tokens: int


@dataclass(frozen=True)
class TokenEventResult:
    entry: TokenLedgerEntry
    quota: UserQuota
    warning: QuotaWarningInfo
    resets_at: datetime


@dataclass(frozen=True)
class BalanceResult:
    quota: UserQuota
    warning: QuotaWarningInfo
    resets_at: datetime


@dataclass(frozen=True)
class AllowanceResult:
    decision: AllowanceDecision
    warning: QuotaWarningInfo


class _QuotaUseCase:
    def __init__(
        self,
        repository: IQuotaRepository,
        clock: IClock,
        domain: QuotaDomainService,
        default_limit: int,
    ):
        self.repository = repository
        self.clock = clock
        self.domain = domain
        self.default_limit = default_limit


class IngestTokenEvent(_QuotaUseCase):
    """Story 8.1 (+ 8.2 on ingestion): record a consumption event atomically."""

    def execute(self, command: TokenEventCommand) -> TokenEventResult:
        now = self.clock.now()
        entry = self.domain.build_ledger_entry(
            user_id=command.user_id,
            subject_id=command.subject_id,
            prompt_tokens=command.prompt_tokens,
            completion_tokens=command.completion_tokens,
            occurred_at=now,
        )
        quota = self.repository.record_consumption(
            entry, date=self.clock.today_str(), default_limit=self.default_limit
        )
        warning = self.domain.evaluate_soft_warning(quota)

        logger.info(
            "token_event_recorded user=%s subject=%s total=%d used=%d limit=%d",
            entry.user_id, entry.subject_id, entry.total_tokens,
            quota.tokens_used, quota.token_limit,
        )
        if self.domain.crossed_warning_threshold(quota, entry.total_tokens):
            logger.warning(
                "quota_warning_crossed user=%s threshold=%s remaining=%d",
                quota.user_id, warning.threshold, warning.remaining_tokens_before_denial,
            )
        if quota.tokens_used > quota.token_limit:
            # Metering records real consumption; the overrun is logged for audit.
            logger.warning(
                "quota_overrun user=%s used=%d limit=%d",
                quota.user_id, quota.tokens_used, quota.token_limit,
            )
        return TokenEventResult(entry, quota, warning, next_daily_reset(now))


class GetQuotaBalance(_QuotaUseCase):
    """Story 8.2 (balance query): current usage plus soft-warning evaluation."""

    def execute(self, user_id: str) -> BalanceResult:
        now = self.clock.now()
        quota = self.repository.get_quota_or_default(
            user_id, self.clock.today_str(), self.default_limit
        )
        return BalanceResult(quota, self.domain.evaluate_soft_warning(quota), next_daily_reset(now))


class CheckAllowance(_QuotaUseCase):
    """Story 8.3: zero-tolerance admission check against the 100% daily ceiling."""

    def execute(self, user_id: str, requested_tokens: int) -> AllowanceResult:
        now = self.clock.now()
        quota = self.repository.get_quota_or_default(
            user_id, self.clock.today_str(), self.default_limit
        )
        decision = self.domain.evaluate_allowance(quota, requested_tokens, now)
        if not decision.allowed:
            logger.info(
                "allowance_denied user=%s requested=%d used=%d limit=%d reason_code=%s",
                user_id, requested_tokens, quota.tokens_used, quota.token_limit,
                decision.reason_code,
            )
        return AllowanceResult(decision, self.domain.evaluate_soft_warning(quota))
