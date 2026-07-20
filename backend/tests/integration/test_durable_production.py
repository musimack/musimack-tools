"""Optional production composition and environment-backed durable settings tests."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, text

from durable_helpers import durable_repository
from musimack_tools.core.config import Settings
from musimack_tools.deployment.application import create_production_app
from musimack_tools.deployment.durable import DurableExecutionSettings
from musimack_tools.deployment.persistence import PersistenceSettings
from musimack_tools.deployment.persistence_runtime import (
    PreparedPersistence,
    prepare_persistence,
)
from musimack_tools.deployment.settings import ProductionSettings
from musimack_tools.deployment.worker import (
    DurableExecutionStartupError,
    prepare_durable_execution,
)
from musimack_tools.domain.durable_execution import SchedulerMode
from musimack_tools.domain.job import JobSubmissionRequest
from musimack_tools.domain.persistence import ReconciliationState
from musimack_tools.domain.storage import NullPersistenceRepository
from musimack_tools.main import create_app
from musimack_tools.persistence.repositories import SQLAlchemyPersistenceRepository
from persistence_helpers import (
    BACKEND_ROOT,
    cleanup_persistence_test_artifacts,  # noqa: F401
    sample_request,
)

if TYPE_CHECKING:
    from pathlib import Path

    from musimack_tools.api.dependencies import InternalApiApplication
    from musimack_tools.crawl.cancellation import CancellationToken
    from musimack_tools.jobs.coordinator import JobRunExecutor
    from musimack_tools.run.progress import RunProgressSink

_TOKEN = "durable-production-test-token"  # noqa: S105 - inert test credential.


def _factory(cancellation: CancellationToken, progress_sink: RunProgressSink) -> JobRunExecutor:
    del cancellation, progress_sink
    return cast("JobRunExecutor", object())


def test_durable_settings_default_to_disabled_without_worker_identity() -> None:
    settings = DurableExecutionSettings.model_validate({})
    configuration = settings.to_configuration()
    assert not configuration.enabled
    assert not configuration.worker_enabled
    assert configuration.worker_id is None
    assert configuration.scheduler_mode is SchedulerMode.IN_MEMORY


def test_durable_settings_map_explicit_worker_configuration() -> None:
    settings = DurableExecutionSettings.model_validate(
        {
            "durable_execution_enabled": True,
            "worker_enabled": True,
            "worker_id": "worker-production",
            "worker_max_concurrency": 2,
            "worker_max_claim_batch": 2,
        }
    )
    configuration = settings.to_configuration()
    assert configuration.enabled
    assert configuration.worker_id is not None
    assert configuration.worker_id.value == "worker-production"
    assert configuration.maximum_concurrent_claimed_jobs == 2


@pytest.mark.parametrize(
    "values",
    [
        {"worker_enabled": True, "worker_id": "worker-test"},
        {"durable_execution_enabled": True, "worker_enabled": True},
        {
            "durable_execution_enabled": True,
            "worker_enabled": True,
            "worker_id": "hostname user",
        },
        {
            "durable_execution_enabled": True,
            "worker_enabled": True,
            "worker_id": "worker-test",
            "worker_heartbeat_interval_seconds": 30,
            "worker_lease_duration_seconds": 30,
        },
    ],
)
def test_invalid_durable_settings_fail_closed(values: dict[str, object]) -> None:
    with pytest.raises((ValidationError, ValueError)):
        DurableExecutionSettings.model_validate(values).to_configuration()


def test_disabled_durable_composition_requires_no_database_or_worker() -> None:
    null = NullPersistenceRepository()
    persistence = PreparedPersistence(null, null.diagnostics(), None)
    prepared = prepare_durable_execution(DurableExecutionSettings.model_validate({}), persistence)
    assert not prepared.configuration.enabled
    assert prepared.repository is None
    assert prepared.worker is None
    assert prepared.diagnostics.recovery_complete


def test_enabled_durable_composition_requires_ready_persistence() -> None:
    null = NullPersistenceRepository()
    persistence = PreparedPersistence(null, null.diagnostics(), None)
    with pytest.raises(DurableExecutionStartupError, match="ready persistence"):
        prepare_durable_execution(
            DurableExecutionSettings.model_validate({"durable_execution_enabled": True}),
            persistence,
        )


def test_enabled_worker_requires_explicit_run_factory(tmp_path: Path) -> None:
    runtime, _repository = durable_repository(tmp_path)
    evidence = SQLAlchemyPersistenceRepository(runtime)
    persistence = PreparedPersistence(evidence, evidence.diagnostics(), None)
    settings = DurableExecutionSettings.model_validate(
        {
            "durable_execution_enabled": True,
            "worker_enabled": True,
            "worker_id": "worker-test",
        }
    )
    try:
        with pytest.raises(DurableExecutionStartupError, match="run-service factory"):
            prepare_durable_execution(settings, persistence, runtime=runtime)
    finally:
        runtime.dispose()


def test_worker_is_composed_explicitly_without_starting_a_task(tmp_path: Path) -> None:
    runtime, _repository = durable_repository(tmp_path)
    evidence = SQLAlchemyPersistenceRepository(runtime)
    persistence = PreparedPersistence(evidence, evidence.diagnostics(), None)
    settings = DurableExecutionSettings.model_validate(
        {
            "durable_execution_enabled": True,
            "worker_enabled": True,
            "worker_id": "worker-test",
        }
    )
    try:
        prepared = prepare_durable_execution(
            settings, persistence, runtime=runtime, run_service_factory=_factory
        )
        assert prepared.worker is not None
        assert prepared.worker.startup_report is None
        assert prepared.diagnostics.worker_state is None
    finally:
        runtime.dispose()


def test_durable_queue_authority_bypasses_legacy_interrupted_reconciliation(
    tmp_path: Path,
) -> None:
    runtime, repository = durable_repository(tmp_path)
    database = tmp_path / "durable.db"
    submission = repository.submit(JobSubmissionRequest(sample_request()))
    assert submission.result.snapshot is not None
    job_id = submission.result.snapshot.job_id
    runtime.dispose()
    prepared = prepare_persistence(
        PersistenceSettings.model_validate(
            {
                "enabled": True,
                "database_path": database,
                "reconcile_on_startup": True,
            }
        ),
        backend_root=BACKEND_ROOT,
        repository_root=tmp_path,
        durable_queue_authority=True,
    )
    try:
        engine = create_engine(f"sqlite+pysqlite:///{database.as_posix()}")
        try:
            with engine.connect() as connection:
                state = connection.execute(
                    text("SELECT state FROM jobs WHERE job_id = :job_id"), {"job_id": job_id}
                ).scalar_one()
        finally:
            engine.dispose()
        assert state == "queued"
        assert prepared.bootstrap is not None
        assert prepared.bootstrap.reconciliation.state is ReconciliationState.NOT_REQUIRED
    finally:
        prepared.repository.dispose()


def test_production_app_keeps_ten_internal_routes_and_registers_worker_lifecycle(
    tmp_path: Path,
) -> None:
    runtime, _repository = durable_repository(tmp_path)
    evidence = SQLAlchemyPersistenceRepository(runtime)
    persistence = PreparedPersistence(evidence, evidence.diagnostics(), None)
    durable = prepare_durable_execution(
        DurableExecutionSettings.model_validate(
            {
                "durable_execution_enabled": True,
                "worker_enabled": True,
                "worker_id": "worker-test",
            }
        ),
        persistence,
        runtime=runtime,
        run_service_factory=_factory,
    )
    service = cast("InternalApiApplication", object())
    production = ProductionSettings.model_validate(
        {"enabled": True, "bearer_token": _TOKEN, "include_openapi": True}
    )
    try:
        app = create_production_app(
            service,
            production,
            Settings(),
            persistence=persistence,
            durable=durable,
        )
        internal = [path for path in app.openapi()["paths"] if path.startswith("/api/internal/")]
        assert len(internal) == 12
        assert app.state.durable_readiness.enabled
        assert len(app.router.on_startup) == 1
        assert len(app.router.on_shutdown) == 1

        async def exercise_lifecycle() -> None:
            await app.router.on_startup[0]()
            assert app.state.durable_readiness.worker_registered
            assert app.state.durable_readiness.worker_state.value == "ready"
            await app.router.on_shutdown[0]()
            assert app.state.durable_readiness.worker_state.value == "stopped"

        asyncio.run(exercise_lifecycle())
    finally:
        runtime.dispose()


def test_default_app_remains_health_only_and_has_no_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    app = create_app(Settings())
    assert list(app.openapi()["paths"]) == ["/api/health"]
    assert not hasattr(app.state, "durable_readiness")
    assert not app.router.on_startup
    assert not tuple(tmp_path.glob("*.db"))
