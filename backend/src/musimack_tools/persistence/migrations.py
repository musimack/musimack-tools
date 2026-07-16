"""Internal Alembic runner and schema-revision inspection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect, text

if TYPE_CHECKING:
    from pathlib import Path

INITIAL_PERSISTENCE_REVISION = "0001_persistence"


def alembic_configuration(database_url: str, *, backend_root: Path) -> Config:
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def upgrade_to_head(database_url: str, *, backend_root: Path) -> None:
    command.upgrade(alembic_configuration(database_url, backend_root=backend_root), "head")


def downgrade_to_base(database_url: str, *, backend_root: Path) -> None:
    command.downgrade(alembic_configuration(database_url, backend_root=backend_root), "base")


def current_revision(engine: Engine) -> str | None:
    if "alembic_version" not in inspect(engine).get_table_names():
        return None
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()


def schema_is_current(engine: Engine) -> bool:
    return current_revision(engine) == INITIAL_PERSISTENCE_REVISION
