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

    DEFAULT_DAILY_TOKEN_LIMIT: int = 100000
    SOFT_WARNING_THRESHOLD: float = 0.80

    FLEET_FIXTURE_PATH: str = "tests/fixtures/fleet_nodes.json"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
