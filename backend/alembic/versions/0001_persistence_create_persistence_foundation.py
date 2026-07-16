"""create persistence foundation

Revision ID: 0001_persistence
Revises: none
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op
from musimack_tools.domain.application import APPLICATION_SERVICE_VERSION
from musimack_tools.domain.persistence import DATABASE_SCHEMA_VERSION, PERSISTENCE_VERSION

revision = "0001_persistence"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    metadata = _migration_metadata()
    metadata.create_all(bind=op.get_bind())
    op.bulk_insert(
        metadata.tables["persistence_metadata"],
        [
            {
                "id": 1,
                "schema_version": DATABASE_SCHEMA_VERSION,
                "persistence_version": PERSISTENCE_VERSION,
                "creation_revision": revision,
                "application_compatibility_version": APPLICATION_SERVICE_VERSION,
            }
        ],
    )


def downgrade() -> None:
    _migration_metadata().drop_all(bind=op.get_bind())


def _migration_metadata() -> sa.MetaData:
    metadata = sa.MetaData()
    sa.Table(
        "persistence_metadata",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("persistence_version", sa.String(64), nullable=False),
        sa.Column("creation_revision", sa.String(32), nullable=False),
        sa.Column("application_compatibility_version", sa.String(64), nullable=False),
    )
    snapshots = sa.Table(
        "configuration_snapshots",
        metadata,
        sa.Column("snapshot_id", sa.String(64), primary_key=True),
        sa.Column("snapshot_type", sa.String(32), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("canonical_json", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False, unique=True),
        sa.CheckConstraint("length(sha256) = 64", name="ck_snapshot_sha256"),
    )
    runs = sa.Table(
        "runs",
        metadata,
        sa.Column("run_id", sa.String(32), primary_key=True),
        sa.Column("orchestration_version", sa.String(64), nullable=False),
        sa.Column("normalized_seed_url", sa.Text(), nullable=False),
        sa.Column("lifecycle", sa.String(32), nullable=False),
        sa.Column("requested_stages_json", sa.Text(), nullable=False),
        sa.Column("stage_states_json", sa.Text(), nullable=False),
        sa.Column("crawl_count", sa.Integer(), nullable=False),
        sa.Column("recommendation_count", sa.Integer(), nullable=False),
        sa.Column("xml_count", sa.Integer(), nullable=False),
        sa.Column("publication_count", sa.Integer(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("final_result_available", sa.Boolean(), nullable=False),
        sa.Column("summary_available", sa.Boolean(), nullable=False),
        sa.Column(
            "configuration_snapshot_id",
            sa.String(64),
            sa.ForeignKey(snapshots.c.snapshot_id, ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Index("ix_runs_lifecycle", "lifecycle"),
    )
    jobs = sa.Table(
        "jobs",
        metadata,
        sa.Column("job_id", sa.String(40), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(32),
            sa.ForeignKey(runs.c.run_id, ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("queue_position", sa.Integer()),
        sa.Column("run_lifecycle", sa.String(32)),
        sa.Column("active_stage", sa.String(32)),
        sa.Column("cancellation_requested", sa.Boolean(), nullable=False),
        sa.Column("terminal", sa.Boolean(), nullable=False),
        sa.Column("result_available", sa.Boolean(), nullable=False),
        sa.Column("payload_retention_policy", sa.String(32), nullable=False),
        sa.Column("registry_version", sa.String(64), nullable=False),
        sa.Column("application_service_version", sa.String(64), nullable=False),
        sa.Column("created_sequence", sa.Integer(), nullable=False),
        sa.Column("started_sequence", sa.Integer()),
        sa.Column("terminal_sequence", sa.Integer()),
        sa.Column("eviction_state", sa.String(32), nullable=False),
        sa.Column("safe_caller_label", sa.String(128)),
        sa.Column(
            "configuration_snapshot_id",
            sa.String(64),
            sa.ForeignKey(snapshots.c.snapshot_id, ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.UniqueConstraint("run_id", "attempt_number", name="uq_jobs_run_attempt"),
        sa.Index("ix_jobs_state_sequence", "state", "created_sequence"),
    )
    sa.Table(
        "run_stages",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.String(32),
            sa.ForeignKey(runs.c.run_id, ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("stable_order", sa.Integer(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("safe_code", sa.String(128)),
        sa.Column("started_sequence", sa.Integer()),
        sa.Column("completed_sequence", sa.Integer()),
        sa.UniqueConstraint("run_id", "stage", name="uq_run_stages_run_stage"),
        sa.Index("ix_run_stages_run_order", "run_id", "stable_order"),
    )
    sa.Table(
        "progress_snapshots",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "job_id",
            sa.String(40),
            sa.ForeignKey(jobs.c.job_id, ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.String(32),
            sa.ForeignKey(runs.c.run_id, ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_code", sa.String(64), nullable=False),
        sa.Column("active_stage", sa.String(32)),
        sa.Column("crawl_state", sa.String(32)),
        sa.Column("discovered_count", sa.Integer(), nullable=False),
        sa.Column("queued_count", sa.Integer(), nullable=False),
        sa.Column("fetched_count", sa.Integer(), nullable=False),
        sa.Column("parsed_count", sa.Integer(), nullable=False),
        sa.Column("byte_count", sa.Integer(), nullable=False),
        sa.Column("queue_size", sa.Integer(), nullable=False),
        sa.Column("active_fetch_count", sa.Integer(), nullable=False),
        sa.Column("current_depth", sa.Integer()),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("cancellation_requested", sa.Boolean(), nullable=False),
        sa.Column("recent_safe_error_code", sa.String(128)),
        sa.Column("elapsed_seconds", sa.Float(), nullable=False),
        sa.UniqueConstraint("job_id", "sequence", name="uq_progress_job_sequence"),
        sa.Index("ix_progress_job_sequence", "job_id", "sequence"),
    )
    _message_table(metadata, "warnings", unique=True)
    _message_table(metadata, "failures", unique=False)
    sa.Table(
        "summary_metadata",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.String(32),
            sa.ForeignKey(runs.c.run_id, ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("summary_type", sa.String(16), nullable=False),
        sa.Column("logical_filename", sa.String(128), nullable=False),
        sa.Column("byte_count", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("availability", sa.Boolean(), nullable=False),
        sa.Column("write_outcome", sa.String(32), nullable=False),
        sa.Column("failure_code", sa.String(128)),
        sa.Column("retention_state", sa.String(32), nullable=False),
        sa.UniqueConstraint("run_id", "logical_filename", name="uq_summary_run_filename"),
        sa.CheckConstraint("length(sha256) = 64", name="ck_summary_sha256"),
    )
    sa.Table(
        "artifact_metadata",
        metadata,
        sa.Column("artifact_id", sa.String(96), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(32),
            sa.ForeignKey(runs.c.run_id, ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("job_id", sa.String(40), sa.ForeignKey(jobs.c.job_id, ondelete="SET NULL")),
        sa.Column("artifact_type", sa.String(32), nullable=False),
        sa.Column("logical_filename", sa.String(128), nullable=False),
        sa.Column("media_type", sa.String(128), nullable=False),
        sa.Column("byte_count", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("entry_count", sa.Integer()),
        sa.Column("publication_state", sa.String(32), nullable=False),
        sa.Column("retention_state", sa.String(32), nullable=False),
        sa.Column("storage_root_identifier", sa.String(64)),
        sa.Column("relative_storage_reference", sa.String(256)),
        sa.Column("failure_code", sa.String(128)),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.UniqueConstraint("run_id", "artifact_type", "logical_filename", name="uq_artifact_run"),
        sa.CheckConstraint("length(sha256) = 64", name="ck_artifact_sha256"),
        sa.Index("ix_artifacts_run_sequence", "run_id", "sequence"),
    )
    return metadata


def _message_table(metadata: sa.MetaData, name: str, *, unique: bool) -> None:
    constraints: list[sa.SchemaItem] = []
    if unique:
        constraints.append(
            sa.UniqueConstraint(
                "parent_type",
                "parent_id",
                "stable_code",
                "stage",
                "safe_message",
                name="uq_warning_exact",
            )
        )
    sa.Table(
        name,
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("parent_type", sa.String(16), nullable=False),
        sa.Column("parent_id", sa.String(40), nullable=False),
        sa.Column("stage", sa.String(32)),
        sa.Column("stable_code", sa.String(128), nullable=False),
        sa.Column("source_layer", sa.String(32), nullable=False),
        sa.Column("source_code", sa.String(128), nullable=False),
        sa.Column("safe_message", sa.String(512), nullable=False),
        sa.Column("normalized_url", sa.Text()),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        *constraints,
        sa.Index(f"ix_{name}_parent_sequence", "parent_type", "parent_id", "sequence"),
    )
