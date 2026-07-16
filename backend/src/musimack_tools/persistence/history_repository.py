"""Read-only, bounded SQLAlchemy query layer for durable history."""

# ruff: noqa: FBT001, PLR0911 - availability has an explicit state precedence.

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from sqlalchemy import Select, and_, exists, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import aliased

from musimack_tools.domain.history import (
    HistoricalArtifact,
    HistoricalAttempt,
    HistoricalJob,
    HistoricalMessage,
    HistoricalRun,
    HistoricalStage,
    HistoryAvailability,
    HistoryDiagnostics,
    HistoryError,
    HistoryFailureCode,
    JobHistoryFilter,
    RunHistoryFilter,
    duration_seconds,
)
from musimack_tools.persistence.durable_models import (
    DurableJobModel,
    DurableRecoveryEventModel,
    JobExecutionAttemptModel,
)
from musimack_tools.persistence.migrations import schema_is_current
from musimack_tools.persistence.models import (
    ArtifactRecordModel,
    FailureModel,
    JobModel,
    ProgressSnapshotModel,
    RunModel,
    RunStageModel,
    SummaryMetadataModel,
    WarningModel,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from sqlalchemy.orm import Session
    from sqlalchemy.orm.attributes import InstrumentedAttribute
    from sqlalchemy.sql.elements import ColumnElement

    from musimack_tools.persistence.engine import PersistenceRuntime

_INTERRUPTED_CODES = {"process_restart_interrupted", "stale_lease_recovered"}
_COMPLETED_STAGES = {"completed", "completed_with_warnings"}
_FAILED_STAGES = {"failed", "blocked"}
_SKIPPED_STAGES = {"skipped", "cancelled"}
_ARTIFACT_DOWNLOADABLE = {"available", "retained"}
_ARTIFACT_MISSING = {"missing", "corrupt"}


class HistoryRepository(Protocol):
    def list_jobs(
        self, filters: JobHistoryFilter, limit: int, after: tuple[int, str] | None
    ) -> tuple[tuple[HistoricalJob, int, str], ...]: ...

    def get_job(self, job_id: str) -> HistoricalJob | None: ...

    def list_runs(
        self, filters: RunHistoryFilter, limit: int, after: tuple[int, str] | None
    ) -> tuple[tuple[HistoricalRun, int, str], ...]: ...

    def get_run(self, run_id: str) -> HistoricalRun | None: ...


class SQLAlchemyHistoryRepository:
    """Query accepted durable tables with a fresh short-lived session per operation."""

    def __init__(self, runtime: PersistenceRuntime) -> None:
        self._runtime = runtime

    def list_jobs(
        self, filters: JobHistoryFilter, limit: int, after: tuple[int, str] | None
    ) -> tuple[tuple[HistoricalJob, int, str], ...]:
        try:
            with self._runtime.transaction() as session:
                statement = self._job_statement(filters)
                if after is not None:
                    sequence, identifier = after
                    statement = statement.where(
                        or_(
                            JobModel.created_sequence < sequence,
                            and_(
                                JobModel.created_sequence == sequence,
                                JobModel.job_id < identifier,
                            ),
                        )
                    )
                rows = session.execute(
                    statement.order_by(
                        JobModel.created_sequence.desc(), JobModel.job_id.desc()
                    ).limit(limit)
                ).all()
                return tuple(
                    (
                        self._job_projection(session, job, run, durable),
                        job.created_sequence,
                        job.job_id,
                    )
                    for job, run, durable in rows
                )
        except SQLAlchemyError:
            raise HistoryError(HistoryFailureCode.QUERY_FAILED, "History query failed.") from None

    def get_job(self, job_id: str) -> HistoricalJob | None:
        rows = self.list_jobs(JobHistoryFilter(job_id=job_id), 1, None)
        return rows[0][0] if rows else None

    def list_runs(
        self, filters: RunHistoryFilter, limit: int, after: tuple[int, str] | None
    ) -> tuple[tuple[HistoricalRun, int, str], ...]:
        latest = aliased(JobModel)
        max_sequence = (
            select(func.max(JobModel.created_sequence))
            .where(JobModel.run_id == RunModel.run_id)
            .correlate(RunModel)
            .scalar_subquery()
        )
        statement = select(RunModel, latest).join(
            latest, and_(latest.run_id == RunModel.run_id, latest.created_sequence == max_sequence)
        )
        statement = self._apply_run_filters(statement, filters, latest)
        if after is not None:
            sequence, identifier = after
            statement = statement.where(
                or_(
                    latest.created_sequence < sequence,
                    and_(latest.created_sequence == sequence, RunModel.run_id < identifier),
                )
            )
        try:
            with self._runtime.transaction() as session:
                rows = session.execute(
                    statement.order_by(
                        latest.created_sequence.desc(), RunModel.run_id.desc()
                    ).limit(limit)
                ).all()
                return tuple(
                    (
                        self._run_projection(session, run, job),
                        job.created_sequence,
                        run.run_id,
                    )
                    for run, job in rows
                )
        except SQLAlchemyError:
            raise HistoryError(HistoryFailureCode.QUERY_FAILED, "History query failed.") from None

    def get_run(self, run_id: str) -> HistoricalRun | None:
        rows = self.list_runs(RunHistoryFilter(run_id=run_id), 1, None)
        return rows[0][0] if rows else None

    def attempts(self, job_id: str, limit: int) -> tuple[HistoricalAttempt, ...]:
        try:
            with self._runtime.transaction() as session:
                rows = tuple(
                    session.scalars(
                        select(JobExecutionAttemptModel)
                        .where(JobExecutionAttemptModel.job_id == job_id)
                        .order_by(JobExecutionAttemptModel.execution_number)
                        .limit(limit)
                    )
                )
                return tuple(
                    HistoricalAttempt(
                        attempt_number=item.execution_number,
                        execution_number=item.execution_number,
                        state=item.outcome,
                        started_at=item.started_at,
                        terminal_at=item.finished_at,
                        worker_id=item.worker_id,
                        lease_generation=item.lease_generation,
                        retryable=item.retryable,
                        failure_code=item.failure_code,
                        terminal_disposition=item.outcome if item.finished_at else None,
                        cancellation_observed=item.cancellation_observed,
                        duration_seconds=duration_seconds(item.started_at, item.finished_at),
                    )
                    for item in rows
                )
        except SQLAlchemyError:
            raise HistoryError(HistoryFailureCode.QUERY_FAILED, "History query failed.") from None

    def stages(self, run_id: str, limit: int) -> tuple[HistoricalStage, ...]:
        try:
            with self._runtime.transaction() as session:
                rows = tuple(
                    session.scalars(
                        select(RunStageModel)
                        .where(RunStageModel.run_id == run_id)
                        .order_by(RunStageModel.stable_order, RunStageModel.id)
                        .limit(limit)
                    )
                )
                return tuple(
                    HistoricalStage(
                        stage=item.stage,
                        order=item.stable_order,
                        state=item.state,
                        started_at=item.started_at,
                        terminal_at=item.terminal_at,
                        duration_seconds=duration_seconds(item.started_at, item.terminal_at),
                        warning_count=item.warning_count,
                        failure_count=item.failure_count,
                        result_available=item.state in _COMPLETED_STAGES,
                        partial=item.state in _FAILED_STAGES,
                    )
                    for item in rows
                )
        except SQLAlchemyError:
            raise HistoryError(HistoryFailureCode.QUERY_FAILED, "History query failed.") from None

    def warnings(self, run_id: str, limit: int) -> tuple[HistoricalMessage, ...]:
        return self._messages(WarningModel, run_id, limit)

    def failures(self, run_id: str, limit: int) -> tuple[HistoricalMessage, ...]:
        return self._messages(FailureModel, run_id, limit)

    def artifacts(self, run_id: str, limit: int) -> tuple[HistoricalArtifact, ...]:
        try:
            with self._runtime.transaction() as session:
                rows = tuple(
                    session.scalars(
                        select(ArtifactRecordModel)
                        .where(ArtifactRecordModel.run_id == run_id)
                        .order_by(ArtifactRecordModel.created_at, ArtifactRecordModel.artifact_id)
                        .limit(limit)
                    )
                )
                return tuple(
                    HistoricalArtifact(
                        artifact_id=item.artifact_id,
                        artifact_type=item.artifact_type,
                        lifecycle_state=item.lifecycle_state,
                        integrity_state=item.integrity_state,
                        filename=item.safe_filename,
                        content_type=item.content_type,
                        byte_count=item.expected_byte_count,
                        created_at=item.created_at,
                        last_verified_at=item.last_verified_at,
                        download_available=(
                            item.lifecycle_state in _ARTIFACT_DOWNLOADABLE
                            and item.integrity_state == "verified"
                        ),
                    )
                    for item in rows
                )
        except SQLAlchemyError:
            raise HistoryError(HistoryFailureCode.QUERY_FAILED, "History query failed.") from None

    def diagnostics(
        self,
        *,
        enabled: bool,
        default_page_size: int,
        maximum_page_size: int,
        last_successful_query_at: datetime | None,
        last_failure_reason: str | None,
    ) -> HistoryDiagnostics:
        try:
            with self._runtime.transaction() as session:
                missing_runs = int(
                    session.scalar(
                        select(func.count(func.distinct(ArtifactRecordModel.run_id))).where(
                            ArtifactRecordModel.lifecycle_state.in_(_ARTIFACT_MISSING)
                        )
                    )
                    or 0
                )
                return HistoryDiagnostics(
                    enabled=enabled,
                    default_page_size=default_page_size,
                    maximum_page_size=maximum_page_size,
                    historical_job_count=_count(session, JobModel),
                    historical_run_count=_count(session, RunModel),
                    terminal_job_count=_count(session, JobModel, JobModel.terminal.is_(True)),
                    interrupted_job_count=_count(
                        session,
                        FailureModel,
                        FailureModel.stable_code.in_(_INTERRUPTED_CODES),
                    ),
                    retry_attempt_count=_count(session, JobExecutionAttemptModel),
                    metadata_only_count=_count(
                        session, JobModel, JobModel.eviction_state == "evicted"
                    ),
                    runs_with_artifacts=int(
                        session.scalar(
                            select(func.count(func.distinct(ArtifactRecordModel.run_id)))
                        )
                        or 0
                    ),
                    runs_with_missing_artifacts=missing_runs,
                    last_successful_query_at=last_successful_query_at,
                    last_failure_reason=last_failure_reason,
                    migration_ready=schema_is_current(self._runtime.engine),
                    database_ready=True,
                )
        except SQLAlchemyError:
            raise HistoryError(HistoryFailureCode.QUERY_FAILED, "History query failed.") from None

    @staticmethod
    def _job_statement(
        filters: JobHistoryFilter,
    ) -> Select[tuple[JobModel, RunModel, DurableJobModel]]:
        statement = (
            select(JobModel, RunModel, DurableJobModel)
            .join(RunModel, RunModel.run_id == JobModel.run_id)
            .outerjoin(DurableJobModel, DurableJobModel.job_id == JobModel.job_id)
        )
        criteria: list[ColumnElement[bool]] = []
        direct = (
            (filters.job_id, JobModel.job_id),
            (filters.run_id, JobModel.run_id),
            (filters.state, JobModel.state),
            (filters.seed, RunModel.normalized_seed_url),
            (filters.retention_state, JobModel.eviction_state),
        )
        criteria.extend(column == value for value, column in direct if value is not None)
        if filters.scheduler_mode == "durable":
            criteria.append(DurableJobModel.job_id.is_not(None))
        elif filters.scheduler_mode == "in_memory":
            criteria.append(DurableJobModel.job_id.is_(None))
        criteria.extend(
            _time_criteria(JobModel.submitted_at, filters.submitted_from, filters.submitted_to)
        )
        criteria.extend(
            _time_criteria(JobModel.terminal_at, filters.terminal_from, filters.terminal_to)
        )
        if filters.cancellation_requested is not None:
            criteria.append(JobModel.cancellation_requested.is_(filters.cancellation_requested))
        if filters.retry_eligible is not None:
            criteria.append(DurableJobModel.retry_eligible.is_(filters.retry_eligible))
        if filters.recovered is not None:
            recovered = exists().where(DurableRecoveryEventModel.job_id == JobModel.job_id)
            criteria.append(recovered if filters.recovered else ~recovered)
        if filters.interrupted is not None:
            interrupted = exists().where(
                FailureModel.parent_type == "job",
                FailureModel.parent_id == JobModel.job_id,
                FailureModel.stable_code.in_(_INTERRUPTED_CODES),
            )
            criteria.append(interrupted if filters.interrupted else ~interrupted)
        if filters.artifacts_available is not None:
            available = exists().where(
                ArtifactRecordModel.job_id == JobModel.job_id,
                ArtifactRecordModel.lifecycle_state.in_(_ARTIFACT_DOWNLOADABLE),
            )
            criteria.append(available if filters.artifacts_available else ~available)
        return statement.where(*criteria)

    @staticmethod
    def _apply_run_filters(
        statement: Select[tuple[RunModel, JobModel]],
        filters: RunHistoryFilter,
        job: type[JobModel],
    ) -> Select[tuple[RunModel, JobModel]]:
        criteria: list[ColumnElement[bool]] = []
        direct = (
            (filters.run_id, RunModel.run_id),
            (filters.job_id, job.job_id),
            (filters.state, RunModel.lifecycle),
        )
        criteria.extend(column == value for value, column in direct if value is not None)
        criteria.extend(
            _time_criteria(RunModel.started_at, filters.started_from, filters.started_to)
        )
        criteria.extend(
            _time_criteria(RunModel.terminal_at, filters.terminal_from, filters.terminal_to)
        )
        if filters.completion_state is not None:
            criteria.append(RunModel.lifecycle == filters.completion_state)
        if filters.stage_state is not None:
            criteria.append(
                exists().where(
                    RunStageModel.run_id == RunModel.run_id,
                    RunStageModel.state == filters.stage_state,
                )
            )
        for requested, column in (
            (filters.has_warnings, RunModel.warning_count),
            (filters.has_failures, RunModel.failure_count),
        ):
            if requested is not None:
                criteria.append(column > 0 if requested else column == 0)
        if filters.has_artifacts is not None:
            present = exists().where(ArtifactRecordModel.run_id == RunModel.run_id)
            criteria.append(present if filters.has_artifacts else ~present)
        if filters.partial is not None:
            partial = RunModel.lifecycle == "partially_completed"
            criteria.append(partial if filters.partial else ~partial)
        if filters.interrupted is not None:
            interrupted = exists().where(
                FailureModel.parent_type == "job",
                FailureModel.parent_id == job.job_id,
                FailureModel.stable_code.in_(_INTERRUPTED_CODES),
            )
            criteria.append(interrupted if filters.interrupted else ~interrupted)
        if filters.retention_state is not None:
            criteria.append(job.eviction_state == filters.retention_state)
        return statement.where(*criteria)

    def _job_projection(
        self, session: Session, job: JobModel, run: RunModel, durable: DurableJobModel | None
    ) -> HistoricalJob:
        artifact_states = tuple(
            session.scalars(
                select(ArtifactRecordModel.lifecycle_state).where(
                    ArtifactRecordModel.job_id == job.job_id
                )
            )
        )
        recovered = (
            session.scalar(select(exists().where(DurableRecoveryEventModel.job_id == job.job_id)))
            is True
        )
        interrupted = (
            session.scalar(
                select(
                    exists().where(
                        FailureModel.parent_type == "job",
                        FailureModel.parent_id == job.job_id,
                        FailureModel.stable_code.in_(_INTERRUPTED_CODES),
                    )
                )
            )
            is True
        )
        return HistoricalJob(
            job_id=job.job_id,
            run_id=job.run_id,
            seed=run.normalized_seed_url,
            scheduler_mode="durable" if durable is not None else "in_memory",
            state=job.state,
            queue_state=durable.durable_state if durable is not None else None,
            attempt_count=(durable.retry_count + 1 if durable is not None else job.attempt_number),
            maximum_attempts=durable.maximum_attempts if durable is not None else None,
            retry_eligible_at=durable.next_retry_at if durable is not None else None,
            cancellation_requested=job.cancellation_requested,
            submitted_at=job.submitted_at,
            started_at=job.started_at,
            terminal_at=job.terminal_at,
            last_failure_code=durable.last_failure_code if durable is not None else None,
            terminal_disposition=durable.terminal_disposition if durable is not None else None,
            interrupted=interrupted,
            recovered=recovered,
            retention_state=job.eviction_state,
            result_available=job.result_available,
            artifact_available=any(state in _ARTIFACT_DOWNLOADABLE for state in artifact_states),
            summary_available=run.summary_available,
            availability=_availability(job, artifact_states, interrupted),
        )

    def _run_projection(self, session: Session, run: RunModel, job: JobModel) -> HistoricalRun:
        stages = tuple(
            session.scalars(select(RunStageModel).where(RunStageModel.run_id == run.run_id))
        )
        artifacts = tuple(
            session.scalars(
                select(ArtifactRecordModel.lifecycle_state).where(
                    ArtifactRecordModel.run_id == run.run_id
                )
            )
        )
        summaries = set(
            session.scalars(
                select(SummaryMetadataModel.summary_type).where(
                    SummaryMetadataModel.run_id == run.run_id,
                    SummaryMetadataModel.availability.is_(True),
                )
            )
        )
        bytes_fetched = session.scalar(
            select(func.max(ProgressSnapshotModel.byte_count)).where(
                ProgressSnapshotModel.run_id == run.run_id
            )
        )
        interrupted = (
            session.scalar(
                select(
                    exists().where(
                        FailureModel.parent_type == "job",
                        FailureModel.parent_id == job.job_id,
                        FailureModel.stable_code.in_(_INTERRUPTED_CODES),
                    )
                )
            )
            is True
        )
        return HistoricalRun(
            run_id=run.run_id,
            job_id=job.job_id,
            seed=run.normalized_seed_url,
            lifecycle=run.lifecycle,
            started_at=run.started_at,
            terminal_at=run.terminal_at,
            duration_seconds=duration_seconds(run.started_at, run.terminal_at),
            current_stage=job.active_stage,
            stage_count=len(stages),
            completed_stage_count=sum(stage.state in _COMPLETED_STAGES for stage in stages),
            failed_stage_count=sum(stage.state in _FAILED_STAGES for stage in stages),
            skipped_stage_count=sum(stage.state in _SKIPPED_STAGES for stage in stages),
            crawl_count=run.crawl_count,
            crawl_byte_count=int(bytes_fetched) if bytes_fetched is not None else None,
            recommendation_count=run.recommendation_count,
            xml_count=run.xml_count,
            publication_count=run.publication_count,
            warning_count=run.warning_count,
            failure_count=run.failure_count,
            artifact_count=len(artifacts),
            summary_json_available="json" in summaries,
            summary_markdown_available="markdown" in summaries,
            partial=run.lifecycle == "partially_completed",
            interrupted=interrupted,
            retention_state=job.eviction_state,
            availability=_availability(job, artifacts, interrupted),
        )

    def _messages(
        self, model: type[WarningModel | FailureModel], run_id: str, limit: int
    ) -> tuple[HistoricalMessage, ...]:
        try:
            with self._runtime.transaction() as session:
                rows: Sequence[WarningModel | FailureModel] = tuple(
                    session.scalars(
                        select(model)
                        .where(model.parent_type == "run", model.parent_id == run_id)
                        .order_by(model.sequence, model.id)
                        .limit(limit)
                    )
                )
                return tuple(
                    HistoricalMessage(
                        item.stable_code,
                        item.stage,
                        item.severity,
                        item.safe_message,
                        item.occurred_at,
                        item.normalized_url,
                    )
                    for item in rows
                )
        except SQLAlchemyError:
            raise HistoryError(HistoryFailureCode.QUERY_FAILED, "History query failed.") from None


def _time_criteria(
    column: InstrumentedAttribute[datetime | None],
    start: datetime | None,
    end: datetime | None,
) -> list[ColumnElement[bool]]:
    criteria: list[ColumnElement[bool]] = []
    if start is not None:
        criteria.append(column >= start)
    if end is not None:
        criteria.append(column <= end)
    return criteria


def _count(
    session: Session,
    model: type[JobModel | RunModel | FailureModel | JobExecutionAttemptModel],
    *criteria: ColumnElement[bool],
) -> int:
    return int(session.scalar(select(func.count()).select_from(model).where(*criteria)) or 0)


def _availability(
    job: JobModel, artifact_states: Sequence[str], interrupted: bool
) -> HistoryAvailability:
    if interrupted:
        return HistoryAvailability.INTERRUPTED
    if job.eviction_state == "evicted":
        return HistoryAvailability.EVICTED
    if "missing" in artifact_states or "corrupt" in artifact_states:
        return HistoryAvailability.ARTIFACT_MISSING
    if "expired" in artifact_states:
        return HistoryAvailability.ARTIFACT_EXPIRED
    if artifact_states and all(state == "deleted" for state in artifact_states):
        return HistoryAvailability.ARTIFACT_DELETED
    if not job.result_available:
        return (
            HistoryAvailability.METADATA_ONLY
            if job.terminal
            else HistoryAvailability.RESULT_UNAVAILABLE
        )
    if "retained" in artifact_states or job.eviction_state == "retained":
        return HistoryAvailability.RETAINED
    return HistoryAvailability.FULL
