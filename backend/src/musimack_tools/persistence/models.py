"""Typed storage representations for bounded durable evidence."""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from musimack_tools.persistence.base import Base


class PersistenceMetadataModel(Base):
    __tablename__ = "persistence_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    persistence_version: Mapped[str] = mapped_column(String(64), nullable=False)
    creation_revision: Mapped[str] = mapped_column(String(32), nullable=False)
    application_compatibility_version: Mapped[str] = mapped_column(String(64), nullable=False)


class ConfigurationSnapshotModel(Base):
    __tablename__ = "configuration_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_type: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_json: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    __table_args__ = (CheckConstraint("length(sha256) = 64", name="ck_snapshot_sha256"),)


class RunModel(Base):
    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    orchestration_version: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_seed_url: Mapped[str] = mapped_column(Text, nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_stages_json: Mapped[str] = mapped_column(Text, nullable=False)
    stage_states_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    crawl_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recommendation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    xml_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    publication_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    final_result_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    summary_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    configuration_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("configuration_snapshots.snapshot_id", ondelete="RESTRICT"), nullable=False
    )

    __table_args__ = (Index("ix_runs_lifecycle", "lifecycle"),)


class JobModel(Base):
    __tablename__ = "jobs"

    job_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    queue_position: Mapped[int | None] = mapped_column(Integer)
    run_lifecycle: Mapped[str | None] = mapped_column(String(32))
    active_stage: Mapped[str | None] = mapped_column(String(32))
    cancellation_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    terminal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    result_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    payload_retention_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    registry_version: Mapped[str] = mapped_column(String(64), nullable=False)
    application_service_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    started_sequence: Mapped[int | None] = mapped_column(Integer)
    terminal_sequence: Mapped[int | None] = mapped_column(Integer)
    eviction_state: Mapped[str] = mapped_column(String(32), nullable=False, default="retained")
    safe_caller_label: Mapped[str | None] = mapped_column(String(128))
    configuration_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("configuration_snapshots.snapshot_id", ondelete="RESTRICT"), nullable=False
    )
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("run_id", "attempt_number", name="uq_jobs_run_attempt"),
        Index("ix_jobs_state_sequence", "state", "created_sequence"),
    )


class RunStageModel(Base):
    __tablename__ = "run_stages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    stable_order: Mapped[int] = mapped_column(Integer, nullable=False)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    safe_code: Mapped[str | None] = mapped_column(String(128))
    started_sequence: Mapped[int | None] = mapped_column(Integer)
    completed_sequence: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        UniqueConstraint("run_id", "stage", name="uq_run_stages_run_stage"),
        Index("ix_run_stages_run_order", "run_id", "stable_order"),
    )


class ProgressSnapshotModel(Base):
    __tablename__ = "progress_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_code: Mapped[str] = mapped_column(String(64), nullable=False)
    active_stage: Mapped[str | None] = mapped_column(String(32))
    crawl_state: Mapped[str | None] = mapped_column(String(32))
    discovered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    queued_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fetched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parsed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    byte_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    queue_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active_fetch_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_depth: Mapped[int | None] = mapped_column(Integer)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cancellation_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    recent_safe_error_code: Mapped[str | None] = mapped_column(String(128))
    elapsed_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    __table_args__ = (
        UniqueConstraint("job_id", "sequence", name="uq_progress_job_sequence"),
        Index("ix_progress_job_sequence", "job_id", "sequence"),
    )


class WarningModel(Base):
    __tablename__ = "warnings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_type: Mapped[str] = mapped_column(String(16), nullable=False)
    parent_id: Mapped[str] = mapped_column(String(40), nullable=False)
    stage: Mapped[str | None] = mapped_column(String(32))
    stable_code: Mapped[str] = mapped_column(String(128), nullable=False)
    source_layer: Mapped[str] = mapped_column(String(32), nullable=False)
    source_code: Mapped[str] = mapped_column(String(128), nullable=False)
    safe_message: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_url: Mapped[str | None] = mapped_column(Text)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="warning")

    __table_args__ = (
        UniqueConstraint(
            "parent_type",
            "parent_id",
            "stable_code",
            "stage",
            "safe_message",
            name="uq_warning_exact",
        ),
        Index("ix_warnings_parent_sequence", "parent_type", "parent_id", "sequence"),
    )


class FailureModel(Base):
    __tablename__ = "failures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_type: Mapped[str] = mapped_column(String(16), nullable=False)
    parent_id: Mapped[str] = mapped_column(String(40), nullable=False)
    stage: Mapped[str | None] = mapped_column(String(32))
    stable_code: Mapped[str] = mapped_column(String(128), nullable=False)
    source_layer: Mapped[str] = mapped_column(String(32), nullable=False)
    source_code: Mapped[str] = mapped_column(String(128), nullable=False)
    safe_message: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_url: Mapped[str | None] = mapped_column(Text)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="error")

    __table_args__ = (Index("ix_failures_parent_sequence", "parent_type", "parent_id", "sequence"),)


class SummaryMetadataModel(Base):
    __tablename__ = "summary_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    summary_type: Mapped[str] = mapped_column(String(16), nullable=False)
    logical_filename: Mapped[str] = mapped_column(String(128), nullable=False)
    byte_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    availability: Mapped[bool] = mapped_column(Boolean, nullable=False)
    write_outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(128))
    retention_state: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "logical_filename", name="uq_summary_run_filename"),
        CheckConstraint("length(sha256) = 64", name="ck_summary_sha256"),
    )


class ArtifactMetadataModel(Base):
    __tablename__ = "artifact_metadata"

    artifact_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.job_id", ondelete="SET NULL"))
    artifact_type: Mapped[str] = mapped_column(String(32), nullable=False)
    logical_filename: Mapped[str] = mapped_column(String(128), nullable=False)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    byte_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_count: Mapped[int | None] = mapped_column(Integer)
    publication_state: Mapped[str] = mapped_column(String(32), nullable=False)
    retention_state: Mapped[str] = mapped_column(String(32), nullable=False)
    storage_root_identifier: Mapped[str | None] = mapped_column(String(64))
    relative_storage_reference: Mapped[str | None] = mapped_column(String(256))
    failure_code: Mapped[str | None] = mapped_column(String(128))
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "artifact_type", "logical_filename", name="uq_artifact_run"),
        CheckConstraint("length(sha256) = 64", name="ck_artifact_sha256"),
        Index("ix_artifacts_run_sequence", "run_id", "sequence"),
    )


class ArtifactStorageRootModel(Base):
    """Safe durable root identity; absolute paths remain runtime-only configuration."""

    __tablename__ = "artifact_storage_roots"

    root_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    readiness_state: Mapped[str] = mapped_column(String(32), nullable=False)
    readable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    writable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    last_checked_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(128))
    storage_version: Mapped[str] = mapped_column(String(64), nullable=False)


class ArtifactRecordModel(Base):
    __tablename__ = "artifact_records"

    artifact_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    artifact_type: Mapped[str] = mapped_column(String(32), nullable=False)
    root_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_storage_roots.root_id", ondelete="RESTRICT"), nullable=False
    )
    relative_path: Mapped[str] = mapped_column(String(512), nullable=False)
    safe_filename: Mapped[str] = mapped_column(String(128), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    lifecycle_state: Mapped[str] = mapped_column(String(32), nullable=False)
    integrity_state: Mapped[str] = mapped_column(String(32), nullable=False)
    expected_byte_count: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_byte_count: Mapped[int | None] = mapped_column(Integer)
    expected_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    retention_state: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(128))
    storage_version: Mapped[str] = mapped_column(String(64), nullable=False)
    retrieval_version: Mapped[str] = mapped_column(String(64), nullable=False)
    reconciliation_version: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "run_id", "artifact_type", "root_id", "relative_path", name="uq_artifact_record"
        ),
        CheckConstraint("expected_byte_count >= 0", name="ck_artifact_record_expected_bytes"),
        CheckConstraint("length(expected_sha256) = 64", name="ck_artifact_record_sha256"),
        CheckConstraint(
            "artifact_type IN ('sitemap_xml','sitemap_index','publication_manifest',"
            "'run_summary_json','run_summary_markdown','csv_export')",
            name="ck_artifact_record_type",
        ),
        CheckConstraint(
            "lifecycle_state IN ('planned','available','missing','corrupt','expired',"
            "'deleted','retained')",
            name="ck_artifact_record_lifecycle",
        ),
        CheckConstraint(
            "integrity_state IN ('unverified','verified','missing','size_mismatch',"
            "'hash_mismatch','type_mismatch','unsafe_path','read_failed','manifest_mismatch')",
            name="ck_artifact_record_integrity",
        ),
        CheckConstraint(
            "retention_state IN ('normal','retained','expired','cleanup_pending','deleted')",
            name="ck_artifact_record_retention",
        ),
        Index("ix_artifact_records_job", "job_id"),
        Index("ix_artifact_records_run", "run_id"),
        Index("ix_artifact_records_lifecycle", "lifecycle_state"),
        Index("ix_artifact_records_expiration", "retention_state", "expires_at"),
        Index("ix_artifact_records_type", "artifact_type"),
        Index("ix_artifact_records_integrity", "integrity_state"),
    )


class ArtifactIntegrityCheckModel(Base):
    __tablename__ = "artifact_integrity_checks"

    check_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_records.artifact_id", ondelete="CASCADE"), nullable=False
    )
    checked_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    integrity_state: Mapped[str] = mapped_column(String(32), nullable=False)
    observed_byte_count: Mapped[int | None] = mapped_column(Integer)
    observed_sha256: Mapped[str | None] = mapped_column(String(64))
    reason_code: Mapped[str | None] = mapped_column(String(128))

    __table_args__ = (Index("ix_artifact_integrity_history", "artifact_id", "check_id"),)


class ArtifactLifecycleEventModel(Base):
    __tablename__ = "artifact_lifecycle_events"

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_records.artifact_id", ondelete="CASCADE"), nullable=False
    )
    occurred_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    from_state: Mapped[str | None] = mapped_column(String(32))
    to_state: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(128))

    __table_args__ = (Index("ix_artifact_lifecycle_history", "artifact_id", "event_id"),)


class ArtifactCleanupEventModel(Base):
    __tablename__ = "artifact_cleanup_events"

    cleanup_event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_records.artifact_id", ondelete="CASCADE"), nullable=False
    )
    occurred_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(128))

    __table_args__ = (Index("ix_artifact_cleanup_history", "artifact_id", "cleanup_event_id"),)


class ArtifactReconciliationEventModel(Base):
    __tablename__ = "artifact_reconciliation_events"

    reconciliation_event_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    root_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_storage_roots.root_id", ondelete="CASCADE"), nullable=False
    )
    artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifact_records.artifact_id", ondelete="SET NULL")
    )
    occurred_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    event_code: Mapped[str] = mapped_column(String(128), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (
        Index("ix_artifact_reconciliation_history", "root_id", "reconciliation_event_id"),
    )
