"""Settings are validated at startup so a bad environment fails fast, not per request."""
import pytest
from pydantic import ValidationError

from src.config import Settings


@pytest.mark.parametrize("overrides", [
    {"DEFAULT_DAILY_TOKEN_LIMIT": 0},
    {"SOFT_WARNING_THRESHOLD": 0},
    {"SOFT_WARNING_THRESHOLD": 1.5},
    {"SOFT_WARNING_THRESHOLD": 0.805},
    {"LOG_LEVEL": "LOUD"},
])
def test_invalid_settings_are_rejected(overrides):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **overrides)


def test_log_level_is_normalised():
    assert Settings(_env_file=None, LOG_LEVEL="info").LOG_LEVEL == "INFO"
