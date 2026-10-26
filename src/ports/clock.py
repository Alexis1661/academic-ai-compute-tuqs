from abc import ABC, abstractmethod
from datetime import datetime

from src.domain.models import period_key


class IClock(ABC):
    """Single source of time (AD-5); swapped for a FakeClock in tests."""

    @abstractmethod
    def now(self) -> datetime:
        """Current timezone-aware UTC datetime."""

    def today_str(self) -> str:
        """Current daily period key (UTC date, YYYY-MM-DD)."""
        return period_key(self.now())
