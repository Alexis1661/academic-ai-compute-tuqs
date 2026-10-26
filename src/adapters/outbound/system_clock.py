from datetime import datetime, timezone

from src.ports.clock import IClock


class SystemClock(IClock):
    """Outbound adapter for real system time."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)
