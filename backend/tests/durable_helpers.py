"""Deterministic durable-execution fixtures shared by focused tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import TYPE_CHECKING

from musimack_tools.domain.durable_execution import (
    DurableExecutionConfiguration,
    RetryPolicy,
    SchedulerMode,
    WorkerIdentity,
)
from musimack_tools.domain.persistence import PersistenceConfiguration
from musimack_tools.persistence.durable_repository import (
    SQLAlchemyDurableExecutionRepository,
)
from musimack_tools.persistence.engine import create_persistence_runtime
from musimack_tools.persistence.migrations import upgrade_to_head
from persistence_helpers import BACKEND_ROOT

if TYPE_CHECKING:
    from pathlib import Path

    from musimack_tools.persistence.engine import PersistenceRuntime

_TOKEN_SEQUENCE = count(1)


class FakeClock:
    def __init__(self) -> None:
        self.value = datetime(2030, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


def durable_configuration(**changes: object) -> DurableExecutionConfiguration:
    configuration = DurableExecutionConfiguration(
        enabled=True,
        worker_enabled=True,
        worker_id=WorkerIdentity("worker-test"),
        scheduler_mode=SchedulerMode.DURABLE,
        retry_policy=RetryPolicy.NEVER,
    )
    return replace(configuration, **changes)  # type: ignore[arg-type]


def durable_repository(
    root: Path,
    *,
    clock: FakeClock | None = None,
    configuration: DurableExecutionConfiguration | None = None,
) -> tuple[PersistenceRuntime, SQLAlchemyDurableExecutionRepository]:
    database = root / "durable.db"
    persistence = PersistenceConfiguration(enabled=True, database_path=database)
    url = f"sqlite+pysqlite:///{database.as_posix()}"
    upgrade_to_head(url, backend_root=BACKEND_ROOT)
    runtime = create_persistence_runtime(persistence)

    def token_factory() -> str:
        return f"lease-{next(_TOKEN_SEQUENCE):032x}"

    repository = SQLAlchemyDurableExecutionRepository(
        runtime,
        configuration or durable_configuration(),
        clock=clock or FakeClock(),
        token_factory=token_factory,
    )
    return runtime, repository
