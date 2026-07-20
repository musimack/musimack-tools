"""Alembic environment for the local SQLite persistence schema."""

from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from musimack_tools.persistence import (
    auth_models,  # noqa: F401 -- registers mapped tables.
    durable_models,  # noqa: F401 -- registers mapped tables.
    image_audit_models,  # noqa: F401 -- registers mapped tables.
    internal_link_models,  # noqa: F401 -- registers mapped tables.
    link_audit_models,  # noqa: F401 -- registers mapped tables.
    migration_qa_models,  # noqa: F401 -- registers mapped tables.
    models,  # noqa: F401 -- registers mapped tables.
    site_audit_models,  # noqa: F401 -- registers mapped tables.
    site_audit_settings_models,  # noqa: F401 -- registers mapped tables.
    sitemap_audit_models,  # noqa: F401 -- registers mapped tables.
    structured_data_models,  # noqa: F401 -- registers mapped tables.
)
from musimack_tools.persistence.base import Base

config = context.config
_MISSING_DATABASE_URL = "an explicit Alembic database URL is required"
x_arguments = context.get_x_argument(as_dictionary=True)
if "database_url" in x_arguments:
    config.set_main_option("sqlalchemy.url", x_arguments["database_url"])
if not config.get_main_option("sqlalchemy.url"):
    raise RuntimeError(_MISSING_DATABASE_URL)
if config.config_file_name is not None:
    # Migration setup must not disable application loggers in an embedding process.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        output_buffer=config.attributes.get("output_buffer"),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        context.configure(
            connection=connection, target_metadata=target_metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
