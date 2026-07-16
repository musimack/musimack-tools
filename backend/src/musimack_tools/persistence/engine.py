"""Explicit SQLite engine, session, and transaction lifecycle."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import URL, Engine, create_engine, event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import ConnectionPoolEntry, StaticPool

from musimack_tools.persistence.path_safety import prepare_database_parent

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sqlalchemy.engine.interfaces import DBAPIConnection

    from musimack_tools.domain.persistence import PersistenceConfiguration

_DISABLED_RUNTIME = "cannot create a database runtime when persistence is disabled"
_MISSING_PATH = "an explicit database path is required"
_INVALID_CONNECTION = "SQLite persistence requires a sqlite3 connection"
_JOURNAL_NOT_APPLIED = "configured SQLite journal mode was not applied"


@dataclass(slots=True)
class PersistenceRuntime:
    configuration: PersistenceConfiguration
    engine: Engine
    session_factory: sessionmaker[Session]

    def dispose(self) -> None:
        self.engine.dispose()

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            with session.begin():
                yield session
        except SQLAlchemyError:
            session.rollback()
            raise
        finally:
            session.close()


def create_persistence_runtime(
    configuration: PersistenceConfiguration,
    *,
    repository_root: Path | None = None,
    in_memory: bool = False,
) -> PersistenceRuntime:
    """Create an injected runtime; importing persistence never calls this function."""
    if not configuration.enabled:
        raise ValueError(_DISABLED_RUNTIME)
    url: str | URL
    if in_memory:
        url = "sqlite+pysqlite:///:memory:"
        pool_arguments: dict[str, Any] = {
            "poolclass": StaticPool,
            "connect_args": {"check_same_thread": False},
        }
    else:
        path = configuration.database_path
        if path is None:
            raise ValueError(_MISSING_PATH)
        prepare_database_parent(
            path,
            create_parent=configuration.create_parent_directory,
            repository_root=repository_root,
        )
        url = URL.create("sqlite+pysqlite", database=str(path))
        pool_arguments = {
            "connect_args": {
                "timeout": configuration.connection_timeout_seconds,
                "check_same_thread": False,
            }
        }
    engine = create_engine(url, echo=configuration.echo_sql, future=True, **pool_arguments)
    _configure_sqlite_connections(engine, configuration, in_memory=in_memory)
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    return PersistenceRuntime(configuration, engine, factory)


def _configure_sqlite_connections(
    engine: Engine,
    configuration: PersistenceConfiguration,
    *,
    in_memory: bool,
) -> None:
    @event.listens_for(engine, "connect")
    def configure(
        dbapi_connection: DBAPIConnection,
        connection_record: ConnectionPoolEntry,
    ) -> None:
        del connection_record
        if not isinstance(dbapi_connection, sqlite3.Connection):
            raise TypeError(_INVALID_CONNECTION)
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(f"PRAGMA busy_timeout={configuration.busy_timeout_milliseconds:d}")
            cursor.execute(f"PRAGMA foreign_keys={'ON' if configuration.foreign_keys else 'OFF'}")
            if not in_memory:
                cursor.execute(f"PRAGMA journal_mode={configuration.journal_mode.value}")
                effective = str(cursor.fetchone()[0]).upper()
                if effective != configuration.journal_mode.value:
                    raise RuntimeError(_JOURNAL_NOT_APPLIED)
            cursor.execute(f"PRAGMA synchronous={configuration.synchronous_mode.value}")
        finally:
            cursor.close()
