"""add durable metadata audit

Revision ID: 0007_metadata_audit
Revises: 0006_page_crawl_evidence
"""

# ruff: noqa: E501 - check-constraint SQL is intentionally explicit and auditable.

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0007_metadata_audit"
down_revision = "0006_page_crawl_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "metadata_audits",
        sa.Column("audit_id", sa.String(40), primary_key=True),
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
        sa.Column("seed_url", sa.Text, nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("configuration_json", sa.Text, nullable=False),
        sa.Column("configuration_hash", sa.String(64), nullable=False),
        sa.Column("audit_version", sa.String(64), nullable=False),
        sa.Column("taxonomy_version", sa.String(64), nullable=False),
        sa.Column("severity_version", sa.String(64), nullable=False),
        sa.Column("duplicate_version", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("page_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("issue_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("partial", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("failure_code", sa.String(128)),
        sa.Column("export_available", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("run_id", "configuration_hash", name="uq_metadata_audit_identity"),
        sa.CheckConstraint(
            "state IN ('planned','running','completed','completed_with_warnings','partially_completed','failed','cancelled')",
            name="ck_metadata_audit_state",
        ),
    )
    op.create_index("ix_metadata_audits_run", "metadata_audits", ["run_id", "created_at"])
    op.create_index("ix_metadata_audits_job", "metadata_audits", ["job_id", "created_at"])
    op.create_index("ix_metadata_audits_order", "metadata_audits", ["created_at", "audit_id"])
    op.create_table(
        "metadata_audit_pages",
        sa.Column("audit_page_id", sa.String(40), primary_key=True),
        sa.Column(
            "audit_id",
            sa.String(40),
            sa.ForeignKey("metadata_audits.audit_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "evidence_id",
            sa.String(64),
            sa.ForeignKey("crawl_page_evidence.evidence_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("url_identity", sa.String(64), nullable=False),
        sa.Column("final_url", sa.Text),
        sa.Column("fetch_outcome", sa.String(32), nullable=False),
        sa.Column("http_status", sa.Integer),
        sa.Column("content_type", sa.String(256)),
        sa.Column("content_type_category", sa.String(16), nullable=False),
        sa.Column("title_value", sa.Text),
        sa.Column("title_presence", sa.String(16), nullable=False),
        sa.Column("title_count", sa.Integer, nullable=False),
        sa.Column("title_length", sa.Integer),
        sa.Column("description_value", sa.Text),
        sa.Column("description_presence", sa.String(16), nullable=False),
        sa.Column("description_count", sa.Integer, nullable=False),
        sa.Column("description_length", sa.Integer),
        sa.Column("canonical_value", sa.Text),
        sa.Column("canonical_state", sa.String(16), nullable=False),
        sa.Column("robots_allowed", sa.Boolean),
        sa.Column("indexability_state", sa.String(16), nullable=False),
        sa.Column("recommendation_state", sa.String(32)),
        sa.Column("issue_count", sa.Integer, nullable=False),
        sa.Column("highest_severity", sa.String(16)),
        sa.Column("partial", sa.Boolean, nullable=False),
        sa.Column("audit_page_version", sa.String(64), nullable=False),
        sa.UniqueConstraint("audit_id", "evidence_id", name="uq_metadata_audit_page_evidence"),
    )
    op.create_index(
        "ix_metadata_audit_pages_order",
        "metadata_audit_pages",
        ["audit_id", "highest_severity", "url_identity"],
    )
    op.create_index(
        "ix_metadata_audit_pages_status",
        "metadata_audit_pages",
        ["audit_id", "http_status", "url_identity"],
    )
    op.create_index(
        "ix_metadata_audit_pages_content",
        "metadata_audit_pages",
        ["audit_id", "content_type_category"],
    )
    op.create_index(
        "ix_metadata_audit_pages_indexability",
        "metadata_audit_pages",
        ["audit_id", "indexability_state"],
    )
    op.create_table(
        "metadata_audit_issues",
        sa.Column("issue_id", sa.String(40), primary_key=True),
        sa.Column(
            "audit_id",
            sa.String(40),
            sa.ForeignKey("metadata_audits.audit_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "audit_page_id",
            sa.String(40),
            sa.ForeignKey("metadata_audit_pages.audit_page_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("safe_summary", sa.String(256), nullable=False),
        sa.Column("safe_detail", sa.String(512), nullable=False),
        sa.Column("determinacy", sa.String(16), nullable=False),
        sa.Column("evidence_json", sa.Text, nullable=False),
        sa.Column("duplicate_group_id", sa.String(40)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("taxonomy_version", sa.String(64), nullable=False),
        sa.Column("severity_version", sa.String(64), nullable=False),
        sa.UniqueConstraint("audit_page_id", "code", name="uq_metadata_audit_issue_code"),
        sa.CheckConstraint(
            "category IN ('title','meta_description','canonical','robots','indexability','status','content_type')",
            name="ck_metadata_audit_issue_category",
        ),
        sa.CheckConstraint(
            "severity IN ('critical','high','medium','low','information')",
            name="ck_metadata_audit_issue_severity",
        ),
    )
    op.create_index(
        "ix_metadata_audit_issues_order",
        "metadata_audit_issues",
        ["audit_id", "severity", "category", "code", "audit_page_id"],
    )
    op.create_index(
        "ix_metadata_audit_issues_group",
        "metadata_audit_issues",
        ["duplicate_group_id", "issue_id"],
    )
    op.create_table(
        "metadata_duplicate_groups",
        sa.Column("group_id", sa.String(40), primary_key=True),
        sa.Column(
            "audit_id",
            sa.String(40),
            sa.ForeignKey("metadata_audits.audit_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("duplicate_type", sa.String(32), nullable=False),
        sa.Column("normalized_value_hash", sa.String(64), nullable=False),
        sa.Column("sample_value", sa.Text, nullable=False),
        sa.Column("member_count", sa.Integer, nullable=False),
        sa.Column("sample_members_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.UniqueConstraint(
            "audit_id",
            "duplicate_type",
            "normalized_value_hash",
            name="uq_metadata_duplicate_value",
        ),
        sa.CheckConstraint(
            "duplicate_type IN ('title','meta_description')", name="ck_metadata_duplicate_type"
        ),
    )
    op.create_index(
        "ix_metadata_duplicate_order",
        "metadata_duplicate_groups",
        ["audit_id", "member_count", "group_id"],
    )
    op.create_table(
        "metadata_duplicate_group_members",
        sa.Column(
            "group_id",
            sa.String(40),
            sa.ForeignKey("metadata_duplicate_groups.group_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "audit_page_id",
            sa.String(40),
            sa.ForeignKey("metadata_audit_pages.audit_page_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("url_identity", sa.String(64), nullable=False),
    )
    op.create_index(
        "ix_metadata_duplicate_members_order",
        "metadata_duplicate_group_members",
        ["group_id", "url_identity", "audit_page_id"],
    )
    op.create_table(
        "metadata_audit_summaries",
        sa.Column(
            "audit_id",
            sa.String(40),
            sa.ForeignKey("metadata_audits.audit_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("summary_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
    )
    op.create_table(
        "metadata_audit_exports",
        sa.Column("export_id", sa.String(64), primary_key=True),
        sa.Column(
            "audit_id",
            sa.String(40),
            sa.ForeignKey("metadata_audits.audit_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("export_format", sa.String(16), nullable=False),
        sa.Column(
            "artifact_id",
            sa.String(64),
            sa.ForeignKey("artifact_records.artifact_id", ondelete="SET NULL"),
        ),
        sa.Column("row_count", sa.Integer, nullable=False),
        sa.Column("truncated", sa.Boolean, nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("failure_code", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("audit_id", "export_format", name="uq_metadata_audit_export"),
    )
    op.create_table(
        "metadata_audit_events",
        sa.Column("event_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "audit_id",
            sa.String(40),
            sa.ForeignKey("metadata_audits.audit_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("safe_reason_code", sa.String(128)),
        sa.Column("affected_count", sa.Integer, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
    )
    op.create_index("ix_metadata_audit_events", "metadata_audit_events", ["audit_id", "event_id"])


def downgrade() -> None:
    op.drop_index("ix_metadata_audit_events", table_name="metadata_audit_events")
    for table in ("metadata_audit_events", "metadata_audit_exports", "metadata_audit_summaries"):
        op.drop_table(table)
    op.drop_index(
        "ix_metadata_duplicate_members_order", table_name="metadata_duplicate_group_members"
    )
    op.drop_table("metadata_duplicate_group_members")
    op.drop_index("ix_metadata_duplicate_order", table_name="metadata_duplicate_groups")
    op.drop_table("metadata_duplicate_groups")
    for name in ("ix_metadata_audit_issues_group", "ix_metadata_audit_issues_order"):
        op.drop_index(name, table_name="metadata_audit_issues")
    op.drop_table("metadata_audit_issues")
    for name in (
        "ix_metadata_audit_pages_indexability",
        "ix_metadata_audit_pages_content",
        "ix_metadata_audit_pages_status",
        "ix_metadata_audit_pages_order",
    ):
        op.drop_index(name, table_name="metadata_audit_pages")
    op.drop_table("metadata_audit_pages")
    for name in ("ix_metadata_audits_order", "ix_metadata_audits_job", "ix_metadata_audits_run"):
        op.drop_index(name, table_name="metadata_audits")
    op.drop_table("metadata_audits")
