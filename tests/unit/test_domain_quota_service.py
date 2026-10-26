"""Pure domain tests: no FastAPI, no database."""
from datetime import datetime, timezone

import pytest

from src.domain.exceptions import InvalidTokenCountError
from src.domain.models import UserQuota, next_daily_reset, period_key
from src.domain.services import QuotaDomainService

NOW = datetime(2026, 10, 25, 23, 59, 59, tzinfo=timezone.utc)


@pytest.fixture
def service():
    return QuotaDomainService(warning_threshold=0.80)


def quota(used, limit=100000):
    return UserQuota(user_id="sam", date="2026-10-25", token_limit=limit, tokens_used=used)


@pytest.mark.parametrize("prompt,completion", [(-1, 5), (5, -1), (0, 0)])
def test_invalid_token_counts_raise(service, prompt, completion):
    with pytest.raises(InvalidTokenCountError):
        service.validate_token_counts(prompt, completion)


def test_build_ledger_entry_totals_and_timestamp(service):
    entry = service.build_ledger_entry("sam", "CS-480", 500, 250, NOW)
    assert entry.total_tokens == 750
    assert entry.timestamp == NOW
    assert len(entry.id) == 36


@pytest.mark.parametrize("used,expected", [(79999, False), (80000, True), (100000, True)])
def test_soft_warning_threshold(service, used, expected):
    info = service.evaluate_soft_warning(quota(used))
    assert info.warning is expected
    assert info.status == ("QUOTA_WARNING_80_PERCENT" if expected else None)
    assert info.remaining_tokens_before_denial == 100000 - used


def test_crossing_detected_only_on_transition(service):
    assert service.crossed_warning_threshold(quota(82000), added_tokens=3000) is True
    assert service.crossed_warning_threshold(quota(85000), added_tokens=3000) is False
    assert service.crossed_warning_threshold(quota(70000), added_tokens=3000) is False


@pytest.mark.parametrize("used,requested,allowed", [
    (99500, 500, True),
    (99501, 500, False),
    (100000, 1, False),
    (0, 100000, True),
    (0, 100001, False),
])
def test_allowance_zero_tolerance(service, used, requested, allowed):
    decision = service.evaluate_allowance(quota(used), requested, NOW)
    assert decision.allowed is allowed
    assert decision.reason_code == (None if allowed else "DAILY_QUOTA_EXCEEDED")


def test_allowance_rejects_non_positive_request(service):
    with pytest.raises(InvalidTokenCountError):
        service.evaluate_allowance(quota(0), 0, NOW)


def test_remaining_balance_never_negative():
    assert quota(150001).remaining_balance == 0


def test_next_daily_reset_is_next_utc_midnight():
    assert next_daily_reset(NOW) == datetime(2026, 10, 26, tzinfo=timezone.utc)
    assert next_daily_reset(datetime(2026, 10, 26, tzinfo=timezone.utc)) == datetime(
        2026, 10, 27, tzinfo=timezone.utc
    )


def test_period_key_and_reset_come_from_the_same_instant():
    just_before = datetime(2026, 10, 25, 23, 59, 59, 999999, tzinfo=timezone.utc)
    assert period_key(just_before) == "2026-10-25"
    assert next_daily_reset(just_before) == datetime(2026, 10, 26, tzinfo=timezone.utc)


def test_naive_datetimes_are_treated_as_utc():
    naive = datetime(2026, 10, 25, 23, 30)
    assert period_key(naive) == "2026-10-25"
    assert next_daily_reset(naive) == datetime(2026, 10, 26, tzinfo=timezone.utc)
