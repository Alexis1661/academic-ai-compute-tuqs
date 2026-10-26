from abc import ABC, abstractmethod
from datetime import datetime, timezone


class IClock(ABC):
    """Single source of time (AD-5); swapped for a FakeClock in tests."""

    @abstractmethod
    def now(self) -> datetime:
        """Current timezone-aware UTC datetime."""

    def today_str(self) -> str:
        """Current UTC date in ISO YYYY-MM-DD format."""
        return self.now().astimezone(timezone.utc).date().isoformat()
