"""SQLAlchemy representations for durable queue and worker coordination."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - SQLAlchemy resolves mapped annotations at runtime.

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from musimack_tools.persistence.base import Base


class DurableSequenceModel(Base):
    __tablename__ = "durable_sequences"

    sequence_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    current_value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class WorkerModel(Base):
    __tablename__ = "workers"

    worker_id: Mapped[str] = mapped_column(String(70), primary_key=True)
    worker_protocol_version: Mapped[str] = mapped_column(String(64), nullable=False)
    durable_execution_version: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    maximum_concurrency: Mapped[int] = mapped_column(Integer, nullable=False)
    current_claimed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    last_heartbeat_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    shutdown_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    failure_code: Mapped[str | None] = mapped_column(String(128))
    metadata_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (Index("ix_workers_state_heartbeat", "state", "last_heartbeat_at"),)


class DurableJobModel(Base):
    __tablename__ = "durable_jobs"

    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.job_id", ondelete="CASCADE"), primary_key=True
    )
    durable_state: Mapped[str] = mapped_column(String(32), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    submission_sequence: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    availability_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    claimed_worker_id: Mapped[str | None] = mapped_column(
        ForeignKey("workers.worker_id", ondelete="SET NULL")
    )
    lease_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cancellation_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    maximum_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    retry_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_code: Mapped[str | None] = mapped_column(String(128))
    terminal_disposition: Mapped[str | None] = mapped_column(String(32))
    worker_protocol_version: Mapped[str] = mapped_column(String(64), nullable=False)
    durable_execution_version: Mapped[str] = mapped_column(String(64), nullable=False)
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    recovery_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index(
            "ix_durable_jobs_claim",
            "durable_state",
            "cancellation_requested",
            "availability_sequence",
            "submission_sequence",
            "job_id",
        ),
        Index("ix_durable_jobs_worker_state", "claimed_worker_id", "durable_state"),
        Index("ix_durable_jobs_retry_at", "durable_state", "next_retry_at"),
    )


class JobLeaseModel(Base):
    __tablename__ = "job_leases"

    lease_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False
    )
    worker_id: Mapped[str] = mapped_column(
        ForeignKey("workers.worker_id", ondelete="CASCADE"), nullable=False
    )
    lease_token: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    lease_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    acquired_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_heartbeat_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    release_reason: Mapped[str | None] = mapped_column(String(128))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    worker_protocol_version: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("job_id", "lease_generation", name="uq_job_lease_generation"),
        Index(
            "uq_job_leases_one_active",
            "job_id",
            unique=True,
            sqlite_where=text("active = 1"),
        ),
        Index("ix_job_leases_worker_active", "worker_id", "active"),
        Index("ix_job_leases_expiration", "active", "expires_at"),
    )


class JobExecutionAttemptModel(Base):
    __tablename__ = "job_execution_attempts"

    attempt_record_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False
    )
    execution_number: Mapped[int] = mapped_column(Integer, nullable=False)
    worker_id: Mapped[str] = mapped_column(
        ForeignKey("workers.worker_id", ondelete="RESTRICT"), nullable=False
    )
    lease_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(128))
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cancellation_observed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    run_lifecycle: Mapped[str | None] = mapped_column(String(32))
    progress_sequence_start: Mapped[int | None] = mapped_column(Integer)
    progress_sequence_end: Mapped[int | None] = mapped_column(Integer)
    created_sequence: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("job_id", "execution_number", name="uq_execution_job_number"),
        Index("ix_execution_job_created", "job_id", "created_sequence"),
    )


class DurableRecoveryEventModel(Base):
    __tablename__ = "durable_recovery_events"

    recovery_event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False
    )
    worker_id: Mapped[str | None] = mapped_column(
        ForeignKey("workers.worker_id", ondelete="SET NULL")
    )
    event_sequence: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    event_code: Mapped[str] = mapped_column(String(128), nullable=False)
    disposition: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_recovery_job_sequence", "job_id", "event_sequence"),)
