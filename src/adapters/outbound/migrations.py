from pathlib import Path

from alembic import command
from alembic.config import Config

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def run_migrations(database_url: str) -> None:
    """Upgrade the database at `database_url` to the latest Alembic revision."""
    config = Config()
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    # configparser interpolation: a literal % (URL-encoded password) must be doubled
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")
