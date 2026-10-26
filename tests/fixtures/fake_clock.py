from datetime import datetime, timedelta, timezone

from src.ports.clock import IClock

# Fixed instant matching tests/fixtures/seed_quotas.json ("date": "2026-10-25")
DEFAULT_NOW = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)


class FakeClock(IClock):
    """Deterministic clock for tests (AD-5): time only moves when the test says so."""

    def __init__(self, now: datetime = DEFAULT_NOW):
        self._now = now

    def now(self) -> datetime:
        return self._now

    def set(self, now: datetime) -> None:
        self._now = now

    def advance(self, **delta) -> None:
        self._now += timedelta(**delta)
