"""Short-transaction SQLAlchemy repository for durable bounded evidence."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import SQLAlchemyError

from musimack_tools.domain.application import APPLICATION_SERVICE_VERSION
from musimack_tools.domain.job import JobState
from musimack_tools.domain.persistence import (
    ArtifactType,
    CleanupResult,
    PersistedJobMetadata,
    PersistenceDiagnostics,
    PersistenceFailureCode,
    PersistenceOperationResult,
    PersistenceReadinessState,
    ReconciliationReport,
    ReconciliationState,
    RetentionState,
)
from musimack_tools.domain.run import RunLifecycle, RunStage, RunStageState
from musimack_tools.domain.storage import PersistenceRepository
from musimack_tools.persistence.mapping import (
    artifact_identifier,
    canonical_configuration,
    safe_message,
    safe_url,
    sha256_bytes,
    stage_states_json,
)
from musimack_tools.persistence.migrations import schema_is_current
from musimack_tools.persistence.models import (
    ArtifactMetadataModel,
    ConfigurationSnapshotModel,
    FailureModel,
    JobModel,
    ProgressSnapshotModel,
    RunModel,
    RunStageModel,
    SummaryMetadataModel,
    WarningModel,
)
from musimack_tools.persistence.transactions import map_database_error, safely_record

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from musimack_tools.domain.job import (
        JobCoordinationFailure,
        JobCoordinationWarning,
        JobSnapshot,
    )
    from musimack_tools.domain.run import CrawlRunRequest, CrawlRunResult
    from musimack_tools.domain.run_progress import RunProgressEvent
    from musimack_tools.persistence.engine import PersistenceRuntime

_INTERRUPTED_STATES = {
    JobState.ACCEPTED.value,
    JobState.QUEUED.value,
    JobState.STARTING.value,
    JobState.RUNNING.value,
    JobState.CANCELLING.value,
}
_MISSING_JOB = "persisted job record is unavailable"
_MISSING_RUN = "persisted run record is unavailable"


class SQLAlchemyPersistenceRepository(PersistenceRepository):
    def __init__(self, runtime: PersistenceRuntime) -> None:
        self._runtime = runtime
        self._retention = runtime.configuration.retention

    def record_submission(
        self,
        snapshot: JobSnapshot,
        request: CrawlRunRequest,
    ) -> PersistenceOperationResult:
        def operation() -> None:
            canonical, digest = canonical_configuration(request)
            with self._runtime.transaction() as session:
                config = session.get(ConfigurationSnapshotModel, digest)
                if config is None:
                    session.add(
                        ConfigurationSnapshotModel(
                            snapshot_id=digest,
                            snapshot_type="crawl_run",
                            schema_version=self._runtime.configuration.schema_version,
                            canonical_json=canonical,
                            sha256=digest,
                        )
                    )
                run = session.get(RunModel, snapshot.run_id)
                if run is None:
                    run = RunModel(
                        run_id=snapshot.run_id,
                        orchestration_version=request.orchestration_version,
                        normalized_seed_url=(
                            safe_url(request.crawl_request.seed_url.normalized) or ""
                        ),
                        lifecycle=RunLifecycle.PENDING.value,
                        requested_stages_json=json.dumps(
                            [stage.value for stage in request.requested_stages],
                            separators=(",", ":"),
                        ),
                        stage_states_json="[]",
                        configuration_snapshot_id=digest,
                    )
                    session.add(run)
                sequence = self._next_job_sequence(session)
                session.add(
                    JobModel(
                        job_id=snapshot.job_id,
                        run_id=snapshot.run_id,
                        attempt_number=snapshot.attempt_number,
                        state=snapshot.state.value,
                        queue_position=snapshot.queue_position,
                        run_lifecycle=(
                            snapshot.run_lifecycle.value
                            if snapshot.run_lifecycle is not None
                            else None
                        ),
                        active_stage=(
                            snapshot.active_stage.value
                            if snapshot.active_stage is not None
                            else None
                        ),
                        cancellation_requested=snapshot.cancellation_requested,
                        terminal=snapshot.terminal,
                        result_available=snapshot.final_result_available,
                        payload_retention_policy="metadata_only",
                        registry_version=snapshot.registry_version,
                        application_service_version=APPLICATION_SERVICE_VERSION,
                        created_sequence=sequence,
                        started_sequence=None,
                        terminal_sequence=None,
                        eviction_state=RetentionState.RETAINED.value,
                        safe_caller_label=(
                            safe_message(request.caller_label, 128)
                            if request.caller_label is not None
                            else None
                        ),
                        configuration_snapshot_id=digest,
                        warning_count=snapshot.warning_count,
                        failure_count=snapshot.failure_count,
                    )
                )

        return safely_record("record_submission", operation)

    def record_transition(self, snapshot: JobSnapshot) -> PersistenceOperationResult:
        def operation() -> None:
            with self._runtime.transaction() as session:
                job = self._required_job(session, snapshot.job_id)
                self._map_job_snapshot(job, snapshot)

        return safely_record("record_transition", operation)

    def record_progress(
        self,
        job_id: str,
        run_id: str,
        event: RunProgressEvent,
    ) -> PersistenceOperationResult:
        def operation() -> None:
            with self._runtime.transaction() as session:
                job = self._required_job(session, job_id)
                snapshot = event.snapshot
                crawl = snapshot.crawl_progress
                session.add(
                    ProgressSnapshotModel(
                        job_id=job_id,
                        run_id=run_id,
                        sequence=event.sequence,
                        event_code=event.code.value,
                        active_stage=(
                            snapshot.active_stage.value
                            if snapshot.active_stage is not None
                            else None
                        ),
                        crawl_state=(crawl.state.value if crawl is not None else None),
                        discovered_count=snapshot.urls_discovered,
                        queued_count=snapshot.urls_queued,
                        fetched_count=snapshot.urls_fetched,
                        parsed_count=snapshot.urls_parsed,
                        byte_count=snapshot.bytes_fetched,
                        queue_size=snapshot.queue_size,
                        active_fetch_count=snapshot.active_count,
                        current_depth=snapshot.current_depth,
                        warning_count=snapshot.warning_count,
                        failure_count=snapshot.failure_count,
                        cancellation_requested=snapshot.cancellation_requested,
                        recent_safe_error_code=snapshot.recent_crawl_error_code,
                        elapsed_seconds=snapshot.elapsed_seconds,
                    )
                )
                job.run_lifecycle = snapshot.lifecycle.value
                job.active_stage = (
                    snapshot.active_stage.value if snapshot.active_stage is not None else None
                )
                job.warning_count = snapshot.warning_count
                job.failure_count = snapshot.failure_count
                run = self._required_run(session, run_id)
                run.lifecycle = snapshot.lifecycle.value
                run.warning_count = snapshot.warning_count
                run.failure_count = snapshot.failure_count
                if snapshot.active_stage is not None and snapshot.stage_state is not None:
                    self._upsert_stage(
                        session,
                        run_id,
                        snapshot.active_stage.value,
                        snapshot.stage_state.value,
                        event.sequence,
                    )
                session.flush()
                self._truncate_progress(session, job_id)

        return safely_record("record_progress", operation)

    def record_terminal(
        self,
        snapshot: JobSnapshot,
        result: CrawlRunResult | None,
        warnings: tuple[JobCoordinationWarning, ...],
        failure: JobCoordinationFailure | None,
    ) -> PersistenceOperationResult:
        def operation() -> None:
            with self._runtime.transaction() as session:
                job = self._required_job(session, snapshot.job_id)
                self._map_job_snapshot(job, snapshot)
                job.terminal_sequence = self._next_terminal_sequence(session)
                if result is not None:
                    self._record_run_result(session, snapshot.job_id, result)
                for index, warning in enumerate(warnings, start=1):
                    self._append_warning(
                        session,
                        "job",
                        snapshot.job_id,
                        warning.code,
                        warning.explanation,
                        index,
                    )
                if failure is not None:
                    session.add(
                        FailureModel(
                            parent_type="job",
                            parent_id=snapshot.job_id,
                            stage=None,
                            stable_code=failure.code.value,
                            source_layer="coordination",
                            source_code=failure.code.value,
                            safe_message=safe_message(failure.explanation),
                            normalized_url=None,
                            sequence=1,
                            severity="error",
                        )
                    )

        return safely_record("record_terminal", operation)

    def diagnostics(self) -> PersistenceDiagnostics:
        try:
            with self._runtime.engine.connect() as connection:
                sqlite_version = str(
                    connection.execute(text("select sqlite_version()")).scalar_one()
                )
                foreign_keys = bool(connection.execute(text("PRAGMA foreign_keys")).scalar_one())
                journal_mode = str(
                    connection.execute(text("PRAGMA journal_mode")).scalar_one()
                ).upper()
            current = schema_is_current(self._runtime.engine)
        except SQLAlchemyError as error:
            return PersistenceDiagnostics(
                state=PersistenceReadinessState.NOT_READY,
                enabled=True,
                database_reachable=False,
                sqlite_version=None,
                foreign_keys_enabled=None,
                journal_mode=None,
                schema_current=False,
                pending_migration=True,
                repository_ready=False,
                reconciliation=ReconciliationState.FAILED,
                failure_code=map_database_error(error, write=False),
            )
        required = current and self._interrupted_count() > 0
        expected_journal = self._runtime.configuration.journal_mode.value
        journal_ok = journal_mode == expected_journal
        state = (
            PersistenceReadinessState.READY
            if current and foreign_keys and journal_ok
            else PersistenceReadinessState.NOT_READY
        )
        return PersistenceDiagnostics(
            state=state,
            enabled=True,
            database_reachable=True,
            sqlite_version=sqlite_version,
            foreign_keys_enabled=foreign_keys,
            journal_mode=journal_mode,
            schema_current=current,
            pending_migration=not current,
            repository_ready=current and foreign_keys and journal_ok,
            reconciliation=(
                ReconciliationState.REQUIRED if required else ReconciliationState.NOT_REQUIRED
            ),
        )

    def reconcile_interrupted(self) -> ReconciliationReport:
        try:
            with self._runtime.transaction() as session:
                jobs = tuple(
                    session.scalars(
                        select(JobModel)
                        .where(JobModel.state.in_(_INTERRUPTED_STATES))
                        .order_by(JobModel.created_sequence, JobModel.job_id)
                    )
                )
                preserved = int(
                    session.scalar(
                        select(func.count()).select_from(JobModel).where(JobModel.terminal)
                    )
                    or 0
                )
                for job in jobs:
                    completed = int(
                        session.scalar(
                            select(func.count())
                            .select_from(RunStageModel)
                            .where(
                                RunStageModel.run_id == job.run_id,
                                RunStageModel.state.in_(
                                    {
                                        RunStageState.COMPLETED.value,
                                        RunStageState.COMPLETED_WITH_WARNINGS.value,
                                    }
                                ),
                            )
                        )
                        or 0
                    )
                    job.state = (
                        JobState.PARTIALLY_COMPLETED.value if completed else JobState.FAILED.value
                    )
                    job.run_lifecycle = (
                        RunLifecycle.PARTIALLY_COMPLETED.value
                        if completed
                        else RunLifecycle.FAILED.value
                    )
                    job.terminal = True
                    job.cancellation_requested = False
                    job.failure_count += 1
                    job.terminal_sequence = self._next_terminal_sequence(session)
                    run = self._required_run(session, job.run_id)
                    run.lifecycle = job.run_lifecycle
                    run.failure_count += 1
                    session.add(
                        FailureModel(
                            parent_type="job",
                            parent_id=job.job_id,
                            stage=None,
                            stable_code="process_restart_interrupted",
                            source_layer="reconciliation",
                            source_code="process_restart_interrupted",
                            safe_message="Process restart interrupted non-terminal work",
                            normalized_url=None,
                            sequence=job.failure_count,
                            severity="error",
                        )
                    )
                    pending = session.scalars(
                        select(RunStageModel).where(
                            RunStageModel.run_id == job.run_id,
                            RunStageModel.state.in_(
                                {RunStageState.PENDING.value, RunStageState.RUNNING.value}
                            ),
                        )
                    )
                    for stage in pending:
                        stage.state = RunStageState.BLOCKED.value
                        stage.safe_code = "process_restart_interrupted"
                attempts = self._highest_attempts_in_session(session)
            return ReconciliationReport(
                ReconciliationState.COMPLETED,
                len(jobs),
                len(jobs),
                preserved,
                attempts,
            )
        except SQLAlchemyError:
            return ReconciliationReport(
                ReconciliationState.FAILED,
                0,
                0,
                0,
                (),
                PersistenceFailureCode.RECONCILIATION_FAILED,
            )

    def highest_attempts(self) -> tuple[tuple[str, int], ...]:
        try:
            with self._runtime.transaction() as session:
                return self._highest_attempts_in_session(session)
        except SQLAlchemyError:
            return ()

    def retained_terminal_jobs(self) -> tuple[PersistedJobMetadata, ...]:
        try:
            with self._runtime.transaction() as session:
                jobs = session.scalars(
                    select(JobModel)
                    .where(
                        JobModel.terminal, JobModel.eviction_state != RetentionState.EVICTED.value
                    )
                    .order_by(JobModel.terminal_sequence, JobModel.job_id)
                )
                values: list[PersistedJobMetadata] = []
                for job in jobs:
                    latest = session.scalar(
                        select(func.max(ProgressSnapshotModel.sequence)).where(
                            ProgressSnapshotModel.job_id == job.job_id
                        )
                    )
                    values.append(
                        PersistedJobMetadata(
                            job.job_id,
                            job.run_id,
                            job.attempt_number,
                            job.state,
                            job.terminal,
                            job.result_available,
                            job.warning_count,
                            job.failure_count,
                            latest,
                        )
                    )
                return tuple(values)
        except SQLAlchemyError:
            return ()

    def cleanup(self) -> CleanupResult:
        try:
            with self._runtime.transaction() as session:
                progress = self._trim_progress(session)
                warnings = self._trim_warnings(session)
                failures = self._trim_failures(session)
                artifacts = self._trim_artifacts(session)
                summaries = self._trim_summaries(session)
                terminal = self._trim_terminal_jobs(session)
            return CleanupResult(progress, warnings, failures, artifacts, summaries, terminal, 0)
        except SQLAlchemyError:
            return CleanupResult(0, 0, 0, 0, 0, 0, 0, PersistenceFailureCode.CLEANUP_FAILED)

    def dispose(self) -> None:
        self._runtime.dispose()

    @staticmethod
    def _required_job(session: Session, job_id: str) -> JobModel:
        job = session.get(JobModel, job_id)
        if job is None:
            raise LookupError(_MISSING_JOB)
        return job

    @staticmethod
    def _required_run(session: Session, run_id: str) -> RunModel:
        run = session.get(RunModel, run_id)
        if run is None:
            raise LookupError(_MISSING_RUN)
        return run

    @staticmethod
    def _next_job_sequence(session: Session) -> int:
        return int(session.scalar(select(func.max(JobModel.created_sequence))) or 0) + 1

    @staticmethod
    def _next_terminal_sequence(session: Session) -> int:
        return int(session.scalar(select(func.max(JobModel.terminal_sequence))) or 0) + 1

    @staticmethod
    def _map_job_snapshot(job: JobModel, snapshot: JobSnapshot) -> None:
        job.state = snapshot.state.value
        job.queue_position = snapshot.queue_position
        job.run_lifecycle = (
            snapshot.run_lifecycle.value if snapshot.run_lifecycle is not None else None
        )
        job.active_stage = (
            snapshot.active_stage.value if snapshot.active_stage is not None else None
        )
        job.cancellation_requested = snapshot.cancellation_requested
        job.terminal = snapshot.terminal
        job.result_available = snapshot.final_result_available
        job.warning_count = snapshot.warning_count
        job.failure_count = snapshot.failure_count
        if snapshot.state in {JobState.STARTING, JobState.RUNNING} and job.started_sequence is None:
            job.started_sequence = job.created_sequence

    @staticmethod
    def _upsert_stage(
        session: Session,
        run_id: str,
        stage: str,
        state: str,
        sequence: int,
    ) -> None:
        item = session.scalar(
            select(RunStageModel).where(
                RunStageModel.run_id == run_id, RunStageModel.stage == stage
            )
        )
        if item is None:
            item = RunStageModel(
                run_id=run_id,
                stage=stage,
                state=state,
                stable_order=[stage_value.value for stage_value in RunStage].index(stage),
                warning_count=0,
                failure_count=0,
                safe_code=None,
                started_sequence=sequence if state == RunStageState.RUNNING.value else None,
                completed_sequence=(
                    sequence
                    if state
                    in {
                        RunStageState.COMPLETED.value,
                        RunStageState.COMPLETED_WITH_WARNINGS.value,
                        RunStageState.BLOCKED.value,
                        RunStageState.CANCELLED.value,
                        RunStageState.FAILED.value,
                    }
                    else None
                ),
            )
            session.add(item)
        else:
            item.state = state
            if state == RunStageState.RUNNING.value and item.started_sequence is None:
                item.started_sequence = sequence
            if state not in {RunStageState.PENDING.value, RunStageState.RUNNING.value}:
                item.completed_sequence = sequence

    def _truncate_progress(self, session: Session, job_id: str) -> None:
        limit = self._retention.maximum_progress_rows_per_job
        ids = tuple(
            session.scalars(
                select(ProgressSnapshotModel.id)
                .where(ProgressSnapshotModel.job_id == job_id)
                .order_by(ProgressSnapshotModel.sequence.desc())
                .offset(limit)
            )
        )
        if ids:
            session.execute(delete(ProgressSnapshotModel).where(ProgressSnapshotModel.id.in_(ids)))

    def _record_run_result(self, session: Session, job_id: str, result: CrawlRunResult) -> None:
        run = self._required_run(session, result.run_id)
        run.lifecycle = result.lifecycle.value
        run.stage_states_json = stage_states_json(result)
        run.crawl_count = len(result.crawl_result.url_records) if result.crawl_result else 0
        run.recommendation_count = (
            len(result.recommendation_projection.recommendations)
            if result.recommendation_projection
            else 0
        )
        run.xml_count = result.xml_bundle.total_entries if result.xml_bundle else 0
        run.publication_count = (
            result.publication_result.published_file_count if result.publication_result else 0
        )
        run.warning_count = len(result.warnings)
        run.failure_count = len(result.failures)
        run.final_result_available = True
        run.summary_available = bool(result.summaries)
        for order, stage in enumerate(result.stages):
            item = session.scalar(
                select(RunStageModel).where(
                    RunStageModel.run_id == result.run_id,
                    RunStageModel.stage == stage.stage.value,
                )
            )
            if item is None:
                session.add(
                    RunStageModel(
                        run_id=result.run_id,
                        stage=stage.stage.value,
                        state=stage.state.value,
                        stable_order=order,
                        warning_count=sum(w.stage is stage.stage for w in result.warnings),
                        failure_count=sum(f.stage is stage.stage for f in result.failures),
                        safe_code=None,
                        started_sequence=None,
                        completed_sequence=None,
                    )
                )
            else:
                item.state = stage.state.value
                item.warning_count = sum(w.stage is stage.stage for w in result.warnings)
                item.failure_count = sum(f.stage is stage.stage for f in result.failures)
        for index, warning in enumerate(result.warnings, start=1):
            self._append_warning(
                session,
                "run",
                result.run_id,
                warning.code,
                warning.message,
                index,
                stage=warning.stage.value,
                url=warning.url,
            )
        for index, failure in enumerate(result.failures, start=1):
            session.add(
                FailureModel(
                    parent_type="run",
                    parent_id=result.run_id,
                    stage=failure.stage.value if failure.stage is not None else None,
                    stable_code=failure.code.value,
                    source_layer="run",
                    source_code=failure.code.value,
                    safe_message=safe_message(failure.explanation),
                    normalized_url=None,
                    sequence=index,
                    severity="error",
                )
            )
        self._record_summaries(session, job_id, result)
        self._record_artifacts(session, job_id, result)

    @staticmethod
    def _append_warning(  # noqa: PLR0913 -- normalized evidence fields remain explicit.
        session: Session,
        parent_type: str,
        parent_id: str,
        code: str,
        message: str,
        sequence: int,
        *,
        stage: str | None = None,
        url: str | None = None,
    ) -> None:
        exists = session.scalar(
            select(WarningModel.id).where(
                WarningModel.parent_type == parent_type,
                WarningModel.parent_id == parent_id,
                WarningModel.stable_code == code,
                WarningModel.stage == stage,
                WarningModel.safe_message == safe_message(message),
            )
        )
        if exists is None:
            session.add(
                WarningModel(
                    parent_type=parent_type,
                    parent_id=parent_id,
                    stage=stage,
                    stable_code=code,
                    source_layer=parent_type,
                    source_code=code,
                    safe_message=safe_message(message),
                    normalized_url=safe_url(url),
                    sequence=sequence,
                    severity="warning",
                )
            )

    @staticmethod
    def _record_summaries(session: Session, job_id: str, result: CrawlRunResult) -> None:
        write_state = (
            result.summary_write_result.state.value
            if result.summary_write_result is not None
            else "not_requested"
        )
        for artifact in result.summaries:
            session.add(
                SummaryMetadataModel(
                    run_id=result.run_id,
                    summary_type=artifact.format.value,
                    logical_filename=artifact.logical_name,
                    byte_count=artifact.byte_count,
                    sha256=artifact.sha256,
                    availability=True,
                    write_outcome=write_state,
                    failure_code=None,
                    retention_state=RetentionState.RETAINED.value,
                )
            )
            kind = (
                ArtifactType.RUN_SUMMARY_JSON
                if artifact.format.value == "json"
                else ArtifactType.RUN_SUMMARY_MARKDOWN
            )
            session.add(
                ArtifactMetadataModel(
                    artifact_id=artifact_identifier(result.run_id, kind, artifact.logical_name),
                    run_id=result.run_id,
                    job_id=job_id,
                    artifact_type=kind.value,
                    logical_filename=artifact.logical_name,
                    media_type=(
                        "application/json; charset=utf-8"
                        if artifact.format.value == "json"
                        else "text/markdown; charset=utf-8"
                    ),
                    byte_count=artifact.byte_count,
                    sha256=artifact.sha256,
                    entry_count=None,
                    publication_state=write_state,
                    retention_state=RetentionState.RETAINED.value,
                    storage_root_identifier=None,
                    relative_storage_reference=None,
                    failure_code=None,
                    sequence=10_000 + len(session.new),
                )
            )

    @staticmethod
    def _record_artifacts(session: Session, job_id: str, result: CrawlRunResult) -> None:
        bundle = result.xml_bundle
        if bundle is None:
            return
        publication_state = (
            result.publication_result.state.value
            if result.publication_result is not None
            else "generated"
        )
        sequence = 0
        for document in bundle.documents:
            sequence += 1
            kind = ArtifactType.SITEMAP_XML
            session.add(
                ArtifactMetadataModel(
                    artifact_id=artifact_identifier(result.run_id, kind, document.logical_name),
                    run_id=result.run_id,
                    job_id=job_id,
                    artifact_type=kind.value,
                    logical_filename=document.logical_name,
                    media_type=document.media_type,
                    byte_count=document.byte_count,
                    sha256=sha256_bytes(document.xml_bytes),
                    entry_count=document.entry_count,
                    publication_state=publication_state,
                    retention_state=RetentionState.RETAINED.value,
                    storage_root_identifier=None,
                    relative_storage_reference=None,
                    failure_code=None,
                    sequence=sequence,
                )
            )
        if bundle.index_document is not None:
            sequence += 1
            index = bundle.index_document
            kind = ArtifactType.SITEMAP_INDEX
            session.add(
                ArtifactMetadataModel(
                    artifact_id=artifact_identifier(result.run_id, kind, index.logical_name),
                    run_id=result.run_id,
                    job_id=job_id,
                    artifact_type=kind.value,
                    logical_filename=index.logical_name,
                    media_type=index.media_type,
                    byte_count=index.byte_count,
                    sha256=sha256_bytes(index.xml_bytes),
                    entry_count=index.entry_count,
                    publication_state=publication_state,
                    retention_state=RetentionState.RETAINED.value,
                    storage_root_identifier=None,
                    relative_storage_reference=None,
                    failure_code=None,
                    sequence=sequence,
                )
            )
        plan = result.publication_plan
        if plan is not None:
            sequence += 1
            manifest = plan.manifest_artifact
            kind = ArtifactType.SITEMAP_MANIFEST
            session.add(
                ArtifactMetadataModel(
                    artifact_id=artifact_identifier(result.run_id, kind, manifest.logical_name),
                    run_id=result.run_id,
                    job_id=job_id,
                    artifact_type=kind.value,
                    logical_filename=manifest.logical_name,
                    media_type="application/json; charset=utf-8",
                    byte_count=manifest.byte_count,
                    sha256=manifest.sha256,
                    entry_count=len(manifest.manifest.files),
                    publication_state=publication_state,
                    retention_state=RetentionState.RETAINED.value,
                    storage_root_identifier=None,
                    relative_storage_reference=None,
                    failure_code=None,
                    sequence=sequence,
                )
            )

    def _interrupted_count(self) -> int:
        with self._runtime.transaction() as session:
            return int(
                session.scalar(
                    select(func.count())
                    .select_from(JobModel)
                    .where(JobModel.state.in_(_INTERRUPTED_STATES))
                )
                or 0
            )

    @staticmethod
    def _highest_attempts_in_session(session: Session) -> tuple[tuple[str, int], ...]:
        rows = session.execute(
            select(JobModel.run_id, func.max(JobModel.attempt_number))
            .group_by(JobModel.run_id)
            .order_by(JobModel.run_id)
        )
        return tuple((str(run_id), int(attempt)) for run_id, attempt in rows)

    def _trim_progress(self, session: Session) -> int:
        rows = tuple(
            session.scalars(
                select(ProgressSnapshotModel).order_by(
                    ProgressSnapshotModel.job_id, ProgressSnapshotModel.sequence
                )
            )
        )
        grouped: dict[str, list[ProgressSnapshotModel]] = defaultdict(list)
        for row in rows:
            grouped[row.job_id].append(row)
        return self._delete_excess(session, grouped, self._retention.maximum_progress_rows_per_job)

    def _trim_artifacts(self, session: Session) -> int:
        rows = tuple(
            session.scalars(
                select(ArtifactMetadataModel).order_by(
                    ArtifactMetadataModel.run_id, ArtifactMetadataModel.sequence
                )
            )
        )
        grouped: dict[str, list[ArtifactMetadataModel]] = defaultdict(list)
        for row in rows:
            grouped[row.run_id].append(row)
        return self._delete_excess(session, grouped, self._retention.maximum_artifact_rows_per_run)

    def _trim_summaries(self, session: Session) -> int:
        rows = tuple(
            session.scalars(
                select(SummaryMetadataModel).order_by(
                    SummaryMetadataModel.run_id, SummaryMetadataModel.id
                )
            )
        )
        grouped: dict[str, list[SummaryMetadataModel]] = defaultdict(list)
        for row in rows:
            grouped[row.run_id].append(row)
        return self._delete_excess(session, grouped, self._retention.maximum_summary_rows_per_run)

    @staticmethod
    def _delete_excess[ModelT](
        session: Session,
        grouped: dict[str, list[ModelT]],
        limit: int,
    ) -> int:
        removed = 0
        for values in grouped.values():
            for row in values[: max(0, len(values) - limit)]:
                session.delete(row)
                removed += 1
        return removed

    def _trim_warnings(self, session: Session) -> int:
        rows = tuple(
            session.scalars(
                select(WarningModel).order_by(
                    WarningModel.parent_type,
                    WarningModel.parent_id,
                    WarningModel.sequence,
                    WarningModel.id,
                )
            )
        )
        grouped: dict[str, list[WarningModel]] = defaultdict(list)
        for row in rows:
            grouped[f"{row.parent_type}\0{row.parent_id}"].append(row)
        return self._delete_excess(
            session, grouped, self._retention.maximum_warning_rows_per_parent
        )

    def _trim_failures(self, session: Session) -> int:
        rows = tuple(
            session.scalars(
                select(FailureModel).order_by(
                    FailureModel.parent_type,
                    FailureModel.parent_id,
                    FailureModel.sequence,
                    FailureModel.id,
                )
            )
        )
        grouped: dict[str, list[FailureModel]] = defaultdict(list)
        for row in rows:
            grouped[f"{row.parent_type}\0{row.parent_id}"].append(row)
        return self._delete_excess(
            session, grouped, self._retention.maximum_failure_rows_per_parent
        )

    def _trim_terminal_jobs(self, session: Session) -> int:
        jobs = tuple(
            session.scalars(
                select(JobModel)
                .where(JobModel.terminal)
                .order_by(JobModel.terminal_sequence, JobModel.job_id)
            )
        )
        excess = jobs[: max(0, len(jobs) - self._retention.maximum_terminal_jobs)]
        for job in excess:
            if self._retention.retain_evicted_job_metadata:
                job.eviction_state = RetentionState.EVICTED.value
                job.payload_retention_policy = "metadata_only"
                session.execute(
                    delete(ProgressSnapshotModel).where(ProgressSnapshotModel.job_id == job.job_id)
                )
            else:
                session.delete(job)
        return len(excess)
