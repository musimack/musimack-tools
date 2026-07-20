"""add Combined Site Audit orchestration

Revision ID: 0018_combined_site_audit_orchestration
Revises: 0017_combined_site_audit_persistence
"""

from collections.abc import Sequence  # noqa: TC003

import sqlalchemy as sa

from alembic import op

revision: str = "0018_combined_site_audit_orchestration"
down_revision: str | Sequence[str] | None = "0017_combined_site_audit_persistence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "site_audit_orchestrations",
        sa.Column("audit_id", sa.String(length=64), nullable=False),
        sa.Column("snapshot_id", sa.String(length=64), nullable=False),
        sa.Column("snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("current_stage", sa.String(length=64), nullable=True),
        sa.Column("crawl_job_id", sa.String(length=40), nullable=True),
        sa.Column("crawl_run_id", sa.String(length=32), nullable=True),
        sa.Column("cancellation_requested", sa.Boolean(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("recovery_count", sa.Integer(), nullable=False),
        sa.Column("projection_version", sa.String(length=64), nullable=False),
        sa.Column("failure_code", sa.String(length=128), nullable=True),
        sa.Column("failure_explanation", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint("retry_count >= 0", name="ck_site_audit_orchestration_retries"),
        sa.CheckConstraint("recovery_count >= 0", name="ck_site_audit_orchestration_recoveries"),
        sa.CheckConstraint("revision > 0", name="ck_site_audit_orchestration_revision"),
        sa.CheckConstraint(
            "state in ('queued','running','cancel_requested','cancelled','completed',"
            "'completed_with_warnings','partially_completed','failed','recovery_required')",
            name="ck_site_audit_orchestration_state",
        ),
        sa.ForeignKeyConstraint(["audit_id"], ["site_audits.audit_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["snapshot_id"], ["site_audit_snapshots.snapshot_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["crawl_job_id"], ["jobs.job_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["crawl_run_id"], ["runs.run_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("audit_id"),
        sa.UniqueConstraint("snapshot_id", name="uq_site_audit_orchestration_snapshot"),
    )
    with op.batch_alter_table("site_audit_orchestrations") as batch_op:
        batch_op.create_index(
            "ix_site_audit_orchestration_state", ["state", "updated_at", "audit_id"]
        )
        batch_op.create_index("ix_site_audit_orchestration_job", ["crawl_job_id", "crawl_run_id"])

    op.create_table(
        "site_audit_orchestration_stages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("audit_id", sa.String(length=64), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("stable_order", sa.Integer(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("dependencies_json", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("checkpoint", sa.Integer(), nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=False),
        sa.Column("projected_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=128), nullable=True),
        sa.Column("failure_explanation", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempt_count >= 0", name="ck_site_audit_stage_attempts"),
        sa.CheckConstraint("checkpoint >= 0", name="ck_site_audit_stage_checkpoint"),
        sa.CheckConstraint(
            "source_count >= 0 and projected_count >= 0", name="ck_site_audit_stage_counts"
        ),
        sa.CheckConstraint(
            "state in ('pending','running','completed','partial','unavailable','failed',"
            "'cancelled','blocked')",
            name="ck_site_audit_stage_state",
        ),
        sa.ForeignKeyConstraint(
            ["audit_id"], ["site_audit_orchestrations.audit_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("audit_id", "stage", name="uq_site_audit_orchestration_stage"),
        sa.UniqueConstraint("audit_id", "stable_order", name="uq_site_audit_stage_order"),
    )
    with op.batch_alter_table("site_audit_orchestration_stages") as batch_op:
        batch_op.create_index("ix_site_audit_stage_state", ["audit_id", "state", "stable_order"])
        batch_op.create_index("ix_site_audit_stage_lease", ["lease_expires_at", "state"])

    op.create_table(
        "site_audit_specialist_associations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("audit_id", sa.String(length=64), nullable=False),
        sa.Column("module", sa.String(length=64), nullable=False),
        sa.Column("specialist_audit_id", sa.String(length=64), nullable=True),
        sa.Column("source_run_id", sa.String(length=64), nullable=True),
        sa.Column("execution_source", sa.String(length=32), nullable=False),
        sa.Column("eligibility_state", sa.String(length=32), nullable=False),
        sa.Column("eligibility_reason", sa.String(length=128), nullable=False),
        sa.Column("freshness_state", sa.String(length=32), nullable=False),
        sa.Column("partial", sa.Boolean(), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column("associated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("evidence_count >= 0", name="ck_site_audit_specialist_evidence"),
        sa.ForeignKeyConstraint(
            ["audit_id"], ["site_audit_orchestrations.audit_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("audit_id", "module", name="uq_site_audit_specialist_module"),
    )
    with op.batch_alter_table("site_audit_specialist_associations") as batch_op:
        batch_op.create_index(
            "ix_site_audit_specialist_source", ["specialist_audit_id", "source_run_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("site_audit_specialist_associations") as batch_op:
        batch_op.drop_index("ix_site_audit_specialist_source")
    op.drop_table("site_audit_specialist_associations")
    with op.batch_alter_table("site_audit_orchestration_stages") as batch_op:
        batch_op.drop_index("ix_site_audit_stage_lease")
        batch_op.drop_index("ix_site_audit_stage_state")
    op.drop_table("site_audit_orchestration_stages")
    with op.batch_alter_table("site_audit_orchestrations") as batch_op:
        batch_op.drop_index("ix_site_audit_orchestration_job")
        batch_op.drop_index("ix_site_audit_orchestration_state")
    op.drop_table("site_audit_orchestrations")
