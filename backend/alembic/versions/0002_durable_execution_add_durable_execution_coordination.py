"""add durable execution coordination

Revision ID: 0002_durable_execution
Revises: 0001_persistence
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0002_durable_execution"
down_revision = "0001_persistence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "durable_sequences",
        sa.Column("sequence_name", sa.String(64), primary_key=True),
        sa.Column("current_value", sa.Integer(), nullable=False),
    )
    op.create_table(
        "workers",
        sa.Column("worker_id", sa.String(70), primary_key=True),
        sa.Column("worker_protocol_version", sa.String(64), nullable=False),
        sa.Column("durable_execution_version", sa.String(64), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("maximum_concurrency", sa.Integer(), nullable=False),
        sa.Column("current_claimed_count", sa.Integer(), nullable=False),
        sa.Column("started_sequence", sa.Integer(), nullable=False),
        sa.Column("last_heartbeat_sequence", sa.Integer(), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("shutdown_requested", sa.Boolean(), nullable=False),
        sa.Column("failure_code", sa.String(128)),
        sa.Column("metadata_version", sa.Integer(), nullable=False),
    )
    op.create_index("ix_workers_state_heartbeat", "workers", ["state", "last_heartbeat_at"])
    op.create_table(
        "durable_jobs",
        sa.Column(
            "job_id",
            sa.String(40),
            sa.ForeignKey("jobs.job_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("durable_state", sa.String(32), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("submission_sequence", sa.Integer(), nullable=False, unique=True),
        sa.Column("availability_sequence", sa.Integer(), nullable=False),
        sa.Column(
            "claimed_worker_id",
            sa.String(70),
            sa.ForeignKey("workers.worker_id", ondelete="SET NULL"),
        ),
        sa.Column("lease_generation", sa.Integer(), nullable=False),
        sa.Column("cancellation_requested", sa.Boolean(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("maximum_attempts", sa.Integer(), nullable=False),
        sa.Column("retry_eligible", sa.Boolean(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
        sa.Column("last_failure_code", sa.String(128)),
        sa.Column("terminal_disposition", sa.String(32)),
        sa.Column("worker_protocol_version", sa.String(64), nullable=False),
        sa.Column("durable_execution_version", sa.String(64), nullable=False),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("recovery_count", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_durable_jobs_claim",
        "durable_jobs",
        [
            "durable_state",
            "cancellation_requested",
            "availability_sequence",
            "submission_sequence",
            "job_id",
        ],
    )
    op.create_index(
        "ix_durable_jobs_worker_state",
        "durable_jobs",
        ["claimed_worker_id", "durable_state"],
    )
    op.create_index("ix_durable_jobs_retry_at", "durable_jobs", ["durable_state", "next_retry_at"])
    op.create_table(
        "job_leases",
        sa.Column("lease_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "job_id",
            sa.String(40),
            sa.ForeignKey("jobs.job_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "worker_id",
            sa.String(70),
            sa.ForeignKey("workers.worker_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("lease_token", sa.String(40), nullable=False, unique=True),
        sa.Column("lease_generation", sa.Integer(), nullable=False),
        sa.Column("acquired_sequence", sa.Integer(), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_heartbeat_sequence", sa.Integer(), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.Column("release_reason", sa.String(128)),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("worker_protocol_version", sa.String(64), nullable=False),
        sa.UniqueConstraint("job_id", "lease_generation", name="uq_job_lease_generation"),
    )
    op.create_index(
        "uq_job_leases_one_active",
        "job_leases",
        ["job_id"],
        unique=True,
        sqlite_where=sa.text("active = 1"),
    )
    op.create_index("ix_job_leases_worker_active", "job_leases", ["worker_id", "active"])
    op.create_index("ix_job_leases_expiration", "job_leases", ["active", "expires_at"])
    op.create_table(
        "job_execution_attempts",
        sa.Column("attempt_record_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "job_id",
            sa.String(40),
            sa.ForeignKey("jobs.job_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "worker_id",
            sa.String(70),
            sa.ForeignKey("workers.worker_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("execution_number", sa.Integer(), nullable=False),
        sa.Column("lease_generation", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("failure_code", sa.String(128)),
        sa.Column("retryable", sa.Boolean(), nullable=False),
        sa.Column("cancellation_observed", sa.Boolean(), nullable=False),
        sa.Column("run_lifecycle", sa.String(32)),
        sa.Column("progress_sequence_start", sa.Integer()),
        sa.Column("progress_sequence_end", sa.Integer()),
        sa.Column("created_sequence", sa.Integer(), nullable=False),
        sa.UniqueConstraint("job_id", "execution_number", name="uq_execution_job_number"),
    )
    op.create_index(
        "ix_execution_job_created",
        "job_execution_attempts",
        ["job_id", "created_sequence"],
    )
    op.create_table(
        "durable_recovery_events",
        sa.Column("recovery_event_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "job_id",
            sa.String(40),
            sa.ForeignKey("jobs.job_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "worker_id",
            sa.String(70),
            sa.ForeignKey("workers.worker_id", ondelete="SET NULL"),
        ),
        sa.Column("event_sequence", sa.Integer(), nullable=False, unique=True),
        sa.Column("event_code", sa.String(128), nullable=False),
        sa.Column("disposition", sa.String(32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_recovery_job_sequence",
        "durable_recovery_events",
        ["job_id", "event_sequence"],
    )


def downgrade() -> None:
    op.drop_table("durable_recovery_events")
    op.drop_table("job_execution_attempts")
    op.drop_table("job_leases")
    op.drop_table("durable_jobs")
    op.drop_table("workers")
    op.drop_table("durable_sequences")
