import logging

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "Academic-AI-Compute-TUQS"
    APP_ENV: str = "development"
    API_V1_PREFIX: str = "/api/v1"
    PORT: int = 8000
    HOST: str = "0.0.0.0"
    LOG_LEVEL: str = "INFO"

    DATABASE_URL: str = "sqlite:///./tuqs.db"
    # Apply Alembic migrations on startup (disabled by the test suite)
    AUTO_MIGRATE: bool = True

    DEFAULT_DAILY_TOKEN_LIMIT: int = Field(100000, gt=0)
    SOFT_WARNING_THRESHOLD: float = Field(0.80, gt=0, le=1)

    FLEET_FIXTURE_PATH: str = "tests/fixtures/fleet_nodes.json"

    @field_validator("LOG_LEVEL")
    @classmethod
    def _known_log_level(cls, value: str) -> str:
        level = value.upper()
        if not isinstance(logging.getLevelName(level), int):
            raise ValueError(f"unknown LOG_LEVEL: {value}")
        return level

    @field_validator("SOFT_WARNING_THRESHOLD")
    @classmethod
    def _whole_percent(cls, value: float) -> float:
        # The warning label and the X-Quota-Warning header carry a whole percent
        if abs(value * 100 - round(value * 100)) > 1e-9:
            raise ValueError("SOFT_WARNING_THRESHOLD must be a whole percent, e.g. 0.80")
        return value

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
