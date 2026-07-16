"""add durable artifact storage

Revision ID: 0003_artifact_storage
Revises: 0002_durable_execution
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0003_artifact_storage"
down_revision = "0002_durable_execution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "artifact_storage_roots",
        sa.Column("root_id", sa.String(64), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("readiness_state", sa.String(32), nullable=False),
        sa.Column("readable", sa.Boolean(), nullable=False),
        sa.Column("writable", sa.Boolean(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason_code", sa.String(128)),
        sa.Column("storage_version", sa.String(64), nullable=False),
    )
    op.create_table(
        "artifact_records",
        sa.Column("artifact_id", sa.String(64), primary_key=True),
        sa.Column(
            "job_id",
            sa.String(40),
            sa.ForeignKey("jobs.job_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.String(32),
            sa.ForeignKey("runs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("artifact_type", sa.String(32), nullable=False),
        sa.Column(
            "root_id",
            sa.String(64),
            sa.ForeignKey("artifact_storage_roots.root_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("relative_path", sa.String(512), nullable=False),
        sa.Column("safe_filename", sa.String(128), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=False),
        sa.Column("lifecycle_state", sa.String(32), nullable=False),
        sa.Column("integrity_state", sa.String(32), nullable=False),
        sa.Column("expected_byte_count", sa.Integer(), nullable=False),
        sa.Column("observed_byte_count", sa.Integer()),
        sa.Column("expected_sha256", sa.String(64), nullable=False),
        sa.Column("observed_sha256", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True)),
        sa.Column("last_verified_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("retention_state", sa.String(32), nullable=False),
        sa.Column("reason_code", sa.String(128)),
        sa.Column("storage_version", sa.String(64), nullable=False),
        sa.Column("retrieval_version", sa.String(64), nullable=False),
        sa.Column("reconciliation_version", sa.String(64), nullable=False),
        sa.UniqueConstraint(
            "run_id", "artifact_type", "root_id", "relative_path", name="uq_artifact_record"
        ),
        sa.CheckConstraint("expected_byte_count >= 0", name="ck_artifact_record_expected_bytes"),
        sa.CheckConstraint("length(expected_sha256) = 64", name="ck_artifact_record_sha256"),
        sa.CheckConstraint(
            "artifact_type IN ('sitemap_xml','sitemap_index','publication_manifest',"
            "'run_summary_json','run_summary_markdown','csv_export')",
            name="ck_artifact_record_type",
        ),
        sa.CheckConstraint(
            "lifecycle_state IN ('planned','available','missing','corrupt','expired',"
            "'deleted','retained')",
            name="ck_artifact_record_lifecycle",
        ),
        sa.CheckConstraint(
            "integrity_state IN ('unverified','verified','missing','size_mismatch',"
            "'hash_mismatch','type_mismatch','unsafe_path','read_failed','manifest_mismatch')",
            name="ck_artifact_record_integrity",
        ),
        sa.CheckConstraint(
            "retention_state IN ('normal','retained','expired','cleanup_pending','deleted')",
            name="ck_artifact_record_retention",
        ),
    )
    op.create_index("ix_artifact_records_job", "artifact_records", ["job_id"])
    op.create_index("ix_artifact_records_run", "artifact_records", ["run_id"])
    op.create_index("ix_artifact_records_lifecycle", "artifact_records", ["lifecycle_state"])
    op.create_index(
        "ix_artifact_records_expiration", "artifact_records", ["retention_state", "expires_at"]
    )
    op.create_index("ix_artifact_records_type", "artifact_records", ["artifact_type"])
    op.create_index("ix_artifact_records_integrity", "artifact_records", ["integrity_state"])
    op.create_table(
        "artifact_integrity_checks",
        sa.Column("check_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "artifact_id",
            sa.String(64),
            sa.ForeignKey("artifact_records.artifact_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("integrity_state", sa.String(32), nullable=False),
        sa.Column("observed_byte_count", sa.Integer()),
        sa.Column("observed_sha256", sa.String(64)),
        sa.Column("reason_code", sa.String(128)),
    )
    op.create_index(
        "ix_artifact_integrity_history", "artifact_integrity_checks", ["artifact_id", "check_id"]
    )
    op.create_table(
        "artifact_lifecycle_events",
        sa.Column("event_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "artifact_id",
            sa.String(64),
            sa.ForeignKey("artifact_records.artifact_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("from_state", sa.String(32)),
        sa.Column("to_state", sa.String(32), nullable=False),
        sa.Column("reason_code", sa.String(128)),
    )
    op.create_index(
        "ix_artifact_lifecycle_history", "artifact_lifecycle_events", ["artifact_id", "event_id"]
    )
    op.create_table(
        "artifact_cleanup_events",
        sa.Column("cleanup_event_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "artifact_id",
            sa.String(64),
            sa.ForeignKey("artifact_records.artifact_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("reason_code", sa.String(128)),
    )
    op.create_index(
        "ix_artifact_cleanup_history",
        "artifact_cleanup_events",
        ["artifact_id", "cleanup_event_id"],
    )
    op.create_table(
        "artifact_reconciliation_events",
        sa.Column("reconciliation_event_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "root_id",
            sa.String(64),
            sa.ForeignKey("artifact_storage_roots.root_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "artifact_id",
            sa.String(64),
            sa.ForeignKey("artifact_records.artifact_id", ondelete="SET NULL"),
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_code", sa.String(128), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
    )
    op.create_index(
        "ix_artifact_reconciliation_history",
        "artifact_reconciliation_events",
        ["root_id", "reconciliation_event_id"],
    )


def downgrade() -> None:
    op.drop_table("artifact_reconciliation_events")
    op.drop_table("artifact_cleanup_events")
    op.drop_table("artifact_lifecycle_events")
    op.drop_table("artifact_integrity_checks")
    op.drop_table("artifact_records")
    op.drop_table("artifact_storage_roots")
