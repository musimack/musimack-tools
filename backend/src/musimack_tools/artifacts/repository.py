"""Short-transaction SQLAlchemy repository for artifact metadata and evidence."""

# ruff: noqa: TRY003 - storage type failures are fixed internal invariants.

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from musimack_tools.domain.artifacts import (
    ArtifactError,
    ArtifactFailureCode,
    ArtifactIntegrityState,
    ArtifactLifecycleState,
    ArtifactRecord,
    ArtifactRetentionState,
    ArtifactRootReadiness,
    ArtifactType,
    validate_artifact_transition,
)
from musimack_tools.persistence.models import (
    ArtifactCleanupEventModel,
    ArtifactIntegrityCheckModel,
    ArtifactLifecycleEventModel,
    ArtifactReconciliationEventModel,
    ArtifactRecordModel,
    ArtifactStorageRootModel,
)

if TYPE_CHECKING:
    from musimack_tools.persistence.engine import PersistenceRuntime


class ArtifactRepository(Protocol):
    def register_root(self, readiness: ArtifactRootReadiness) -> None: ...
    def add(self, record: ArtifactRecord) -> ArtifactRecord: ...
    def get(self, artifact_id: str) -> ArtifactRecord | None: ...
    def list(self, *, offset: int, limit: int) -> tuple[ArtifactRecord, ...]: ...
    def update_verification(  # noqa: PLR0913
        self,
        artifact_id: str,
        *,
        lifecycle: ArtifactLifecycleState,
        integrity: ArtifactIntegrityState,
        observed_bytes: int | None,
        observed_sha256: str | None,
        checked_at: datetime,
        reason_code: str | None,
    ) -> ArtifactRecord: ...
    def transition(  # noqa: PLR0913
        self,
        artifact_id: str,
        *,
        lifecycle: ArtifactLifecycleState,
        retention: ArtifactRetentionState,
        occurred_at: datetime,
        reason_code: str | None,
        deleted_at: datetime | None = None,
    ) -> ArtifactRecord: ...
    def cleanup_candidates(self, now: datetime, limit: int) -> tuple[ArtifactRecord, ...]: ...
    def record_cleanup(
        self, artifact_id: str, occurred_at: datetime, outcome: str, reason_code: str | None
    ) -> None: ...
    def record_reconciliation(
        self,
        root_id: str,
        artifact_id: str | None,
        occurred_at: datetime,
        event_code: str,
        outcome: str,
    ) -> None: ...


class SQLAlchemyArtifactRepository:
    def __init__(self, runtime: PersistenceRuntime) -> None:
        self._runtime = runtime

    def register_root(self, readiness: ArtifactRootReadiness) -> None:
        with self._runtime.transaction() as session:
            row = session.get(ArtifactStorageRootModel, readiness.root_id)
            if row is None:
                row = ArtifactStorageRootModel(
                    root_id=readiness.root_id,
                    enabled=True,
                    readiness_state="ready" if readiness.ready else "not_ready",
                    readable=readiness.readable,
                    writable=readiness.writable,
                    last_checked_at=readiness.checked_at,
                    reason_code=readiness.reason_code,
                    storage_version="seo-toolkit-artifact-storage-v1",
                )
                session.add(row)
            else:
                row.readiness_state = "ready" if readiness.ready else "not_ready"
                row.readable = readiness.readable
                row.writable = readiness.writable
                row.last_checked_at = readiness.checked_at
                row.reason_code = readiness.reason_code

    def add(self, record: ArtifactRecord) -> ArtifactRecord:
        existing = self.get(record.artifact_id)
        if existing is not None:
            if existing == record:
                return existing
            raise ArtifactError(
                ArtifactFailureCode.REGISTRATION_CONFLICT,
                "Artifact registration conflicts with durable metadata.",
            )
        try:
            with self._runtime.transaction() as session:
                session.add(_to_model(record))
                session.flush()
                session.add(
                    ArtifactLifecycleEventModel(
                        artifact_id=record.artifact_id,
                        occurred_at=record.created_at,
                        from_state=None,
                        to_state=record.lifecycle_state.value,
                        reason_code=record.reason_code,
                    )
                )
        except IntegrityError:
            raise ArtifactError(
                ArtifactFailureCode.REGISTRATION_CONFLICT,
                "Artifact registration conflicts with durable metadata.",
            ) from None
        return record

    def get(self, artifact_id: str) -> ArtifactRecord | None:
        with self._runtime.transaction() as session:
            row = session.get(ArtifactRecordModel, artifact_id)
            return None if row is None else _from_model(row)

    def list(self, *, offset: int, limit: int) -> tuple[ArtifactRecord, ...]:
        with self._runtime.transaction() as session:
            rows = session.scalars(
                select(ArtifactRecordModel)
                .order_by(ArtifactRecordModel.created_at, ArtifactRecordModel.artifact_id)
                .offset(offset)
                .limit(limit)
            )
            return tuple(_from_model(row) for row in rows)

    def update_verification(  # noqa: PLR0913
        self,
        artifact_id: str,
        *,
        lifecycle: ArtifactLifecycleState,
        integrity: ArtifactIntegrityState,
        observed_bytes: int | None,
        observed_sha256: str | None,
        checked_at: datetime,
        reason_code: str | None,
    ) -> ArtifactRecord:
        with self._runtime.transaction() as session:
            row = session.get(ArtifactRecordModel, artifact_id)
            if row is None:
                raise ArtifactError(ArtifactFailureCode.NOT_FOUND, "Artifact was not found.")
            previous = row.lifecycle_state
            validate_artifact_transition(ArtifactLifecycleState(previous), lifecycle)
            row.lifecycle_state = lifecycle.value
            row.integrity_state = integrity.value
            row.observed_byte_count = observed_bytes
            row.observed_sha256 = observed_sha256
            row.last_verified_at = checked_at
            row.reason_code = reason_code
            if lifecycle in {ArtifactLifecycleState.AVAILABLE, ArtifactLifecycleState.RETAINED}:
                row.available_at = row.available_at or checked_at
            session.add(
                ArtifactIntegrityCheckModel(
                    artifact_id=artifact_id,
                    checked_at=checked_at,
                    integrity_state=integrity.value,
                    observed_byte_count=observed_bytes,
                    observed_sha256=observed_sha256,
                    reason_code=reason_code,
                )
            )
            if previous != lifecycle.value:
                session.add(
                    ArtifactLifecycleEventModel(
                        artifact_id=artifact_id,
                        occurred_at=checked_at,
                        from_state=previous,
                        to_state=lifecycle.value,
                        reason_code=reason_code,
                    )
                )
            session.flush()
            return _from_model(row)

    def transition(  # noqa: PLR0913
        self,
        artifact_id: str,
        *,
        lifecycle: ArtifactLifecycleState,
        retention: ArtifactRetentionState,
        occurred_at: datetime,
        reason_code: str | None,
        deleted_at: datetime | None = None,
    ) -> ArtifactRecord:
        with self._runtime.transaction() as session:
            row = session.get(ArtifactRecordModel, artifact_id)
            if row is None:
                raise ArtifactError(ArtifactFailureCode.NOT_FOUND, "Artifact was not found.")
            previous = row.lifecycle_state
            validate_artifact_transition(ArtifactLifecycleState(previous), lifecycle)
            row.lifecycle_state = lifecycle.value
            row.retention_state = retention.value
            row.reason_code = reason_code
            row.deleted_at = deleted_at
            session.add(
                ArtifactLifecycleEventModel(
                    artifact_id=artifact_id,
                    occurred_at=occurred_at,
                    from_state=previous,
                    to_state=lifecycle.value,
                    reason_code=reason_code,
                )
            )
            session.flush()
            return _from_model(row)

    def cleanup_candidates(self, now: datetime, limit: int) -> tuple[ArtifactRecord, ...]:
        with self._runtime.transaction() as session:
            rows = session.scalars(
                select(ArtifactRecordModel)
                .where(
                    ArtifactRecordModel.expires_at.is_not(None),
                    ArtifactRecordModel.expires_at <= now,
                    ArtifactRecordModel.retention_state.in_(
                        ("normal", "expired", "cleanup_pending")
                    ),
                    ArtifactRecordModel.lifecycle_state.not_in(("planned", "deleted", "retained")),
                )
                .order_by(ArtifactRecordModel.expires_at, ArtifactRecordModel.artifact_id)
                .limit(limit)
            )
            return tuple(_from_model(row) for row in rows)

    def record_cleanup(
        self, artifact_id: str, occurred_at: datetime, outcome: str, reason_code: str | None
    ) -> None:
        with self._runtime.transaction() as session:
            session.add(
                ArtifactCleanupEventModel(
                    artifact_id=artifact_id,
                    occurred_at=occurred_at,
                    outcome=outcome,
                    reason_code=reason_code,
                )
            )

    def record_reconciliation(
        self,
        root_id: str,
        artifact_id: str | None,
        occurred_at: datetime,
        event_code: str,
        outcome: str,
    ) -> None:
        with self._runtime.transaction() as session:
            session.add(
                ArtifactReconciliationEventModel(
                    root_id=root_id,
                    artifact_id=artifact_id,
                    occurred_at=occurred_at,
                    event_code=event_code,
                    outcome=outcome,
                )
            )


def _aware(value: object | None) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise TypeError("artifact timestamp has invalid storage type")
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _from_model(row: ArtifactRecordModel) -> ArtifactRecord:
    created = _aware(row.created_at)
    if created is None:
        raise TypeError("artifact creation timestamp is missing")
    return ArtifactRecord(
        row.artifact_id,
        row.job_id,
        row.run_id,
        ArtifactType(row.artifact_type),
        row.root_id,
        row.relative_path,
        row.safe_filename,
        row.content_type,
        ArtifactLifecycleState(row.lifecycle_state),
        ArtifactIntegrityState(row.integrity_state),
        row.expected_byte_count,
        row.observed_byte_count,
        row.expected_sha256,
        row.observed_sha256,
        created,
        _aware(row.available_at),
        _aware(row.last_verified_at),
        _aware(row.expires_at),
        _aware(row.deleted_at),
        ArtifactRetentionState(row.retention_state),
        row.reason_code,
        row.storage_version,
        row.retrieval_version,
        row.reconciliation_version,
    )


def _to_model(record: ArtifactRecord) -> ArtifactRecordModel:
    return ArtifactRecordModel(
        artifact_id=record.artifact_id,
        job_id=record.job_id,
        run_id=record.run_id,
        artifact_type=record.artifact_type.value,
        root_id=record.root_id,
        relative_path=record.relative_path,
        safe_filename=record.filename,
        content_type=record.content_type,
        lifecycle_state=record.lifecycle_state.value,
        integrity_state=record.integrity_state.value,
        expected_byte_count=record.expected_byte_count,
        observed_byte_count=record.observed_byte_count,
        expected_sha256=record.expected_sha256,
        observed_sha256=record.observed_sha256,
        created_at=record.created_at,
        available_at=record.available_at,
        last_verified_at=record.last_verified_at,
        expires_at=record.expires_at,
        deleted_at=record.deleted_at,
        retention_state=record.retention_state.value,
        reason_code=record.reason_code,
        storage_version=record.storage_version,
        retrieval_version=record.retrieval_version,
        reconciliation_version=record.reconciliation_version,
    )
