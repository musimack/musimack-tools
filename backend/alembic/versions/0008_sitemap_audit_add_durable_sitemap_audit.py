"""add durable sitemap audit

Revision ID: 0008_sitemap_audit
Revises: 0007_metadata_audit
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0008_sitemap_audit"
down_revision = "0007_metadata_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sitemap_audits",
        sa.Column("audit_id", sa.String(64), primary_key=True),
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
        sa.Column("seed_url", sa.Text(), nullable=False),
        sa.Column("explicit_sitemap_url", sa.Text()),
        sa.Column("discovery_settings_json", sa.Text(), nullable=False),
        sa.Column("configuration_json", sa.Text(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("failure_code", sa.String(128)),
        sa.Column("warning_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("document_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unique_url_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("comparison_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("add_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("remove_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("review_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unchanged_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("audit_version", sa.String(64), nullable=False),
        sa.Column("parser_version", sa.String(64), nullable=False),
        sa.Column("comparison_version", sa.String(64), nullable=False),
        sa.Column("normalization_version", sa.String(64), nullable=False),
        sa.Column("page_evidence_version", sa.String(64), nullable=False),
        sa.Column("recommendation_version", sa.String(64), nullable=False),
        sa.CheckConstraint(
            "state in ('accepted','discovering','fetching','parsing','comparing','completed',"
            "'completed_with_warnings','partially_completed','failed','cancelled')",
            name="ck_sitemap_audits_state",
        ),
        sa.CheckConstraint(
            "warning_count >= 0 and document_count >= 0 and unique_url_count >= 0 "
            "and comparison_count >= 0 and add_count >= 0 and remove_count >= 0 "
            "and review_count >= 0 and unchanged_count >= 0",
            name="ck_sitemap_audits_counts",
        ),
    )
    op.create_index(
        "ix_sitemap_audits_run_created", "sitemap_audits", ["run_id", "created_at", "audit_id"]
    )
    op.create_index(
        "ix_sitemap_audits_state_created", "sitemap_audits", ["state", "created_at", "audit_id"]
    )
    op.create_table(
        "sitemap_audit_documents",
        sa.Column("document_id", sa.String(64), primary_key=True),
        sa.Column(
            "audit_id",
            sa.String(64),
            sa.ForeignKey("sitemap_audits.audit_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_document_id",
            sa.String(64),
            sa.ForeignKey("sitemap_audit_documents.document_id", ondelete="CASCADE"),
        ),
        sa.Column("discovery_source", sa.String(32), nullable=False),
        sa.Column("requested_url", sa.Text(), nullable=False),
        sa.Column("final_url", sa.Text()),
        sa.Column("normalized_identity", sa.Text(), nullable=False),
        sa.Column("provenance_json", sa.Text(), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("discovery_sequence", sa.Integer(), nullable=False),
        sa.Column("fetch_state", sa.String(32), nullable=False),
        sa.Column("http_status", sa.Integer()),
        sa.Column("content_type", sa.String(256)),
        sa.Column("payload_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload_sha256", sa.String(64)),
        sa.Column("redirect_json", sa.Text(), nullable=False),
        sa.Column("root_type", sa.String(32)),
        sa.Column("entry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("child_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("parse_state", sa.String(32), nullable=False),
        sa.Column("validation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("audit_id", "normalized_identity", name="uq_sitemap_document_identity"),
        sa.CheckConstraint(
            "depth >= 0 and discovery_sequence >= 0", name="ck_sitemap_document_order"
        ),
        sa.CheckConstraint(
            "payload_size >= 0 and entry_count >= 0 and child_count >= 0 and validation_count >= 0",
            name="ck_sitemap_document_counts",
        ),
    )
    op.create_index(
        "ix_sitemap_documents_audit_order",
        "sitemap_audit_documents",
        ["audit_id", "discovery_sequence", "document_id"],
    )
    op.create_index(
        "ix_sitemap_documents_parent",
        "sitemap_audit_documents",
        ["parent_document_id", "discovery_sequence"],
    )
    op.create_index(
        "ix_sitemap_documents_parse",
        "sitemap_audit_documents",
        ["audit_id", "parse_state", "depth"],
    )
    op.create_table(
        "sitemap_audit_entries",
        sa.Column("entry_id", sa.String(64), primary_key=True),
        sa.Column(
            "audit_id",
            sa.String(64),
            sa.ForeignKey("sitemap_audits.audit_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.String(64),
            sa.ForeignKey("sitemap_audit_documents.document_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("raw_location", sa.Text()),
        sa.Column("normalized_identity", sa.Text()),
        sa.Column("entry_sequence", sa.Integer(), nullable=False),
        sa.Column("in_scope", sa.Boolean()),
        sa.Column("validation_state", sa.String(32), nullable=False),
        sa.Column("duplicate", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("duplicate_identity", sa.Text()),
        sa.Column("is_child_reference", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("document_id", "entry_sequence", name="uq_sitemap_entry_sequence"),
        sa.CheckConstraint("entry_sequence >= 0", name="ck_sitemap_entry_sequence"),
    )
    op.create_index(
        "ix_sitemap_entries_audit_identity",
        "sitemap_audit_entries",
        ["audit_id", "normalized_identity"],
    )
    op.create_index(
        "ix_sitemap_entries_document_order",
        "sitemap_audit_entries",
        ["document_id", "entry_sequence", "entry_id"],
    )
    op.create_index(
        "ix_sitemap_entries_validation",
        "sitemap_audit_entries",
        ["audit_id", "validation_state", "duplicate"],
    )
    op.create_table(
        "sitemap_audit_findings",
        sa.Column("finding_id", sa.String(64), primary_key=True),
        sa.Column(
            "audit_id",
            sa.String(64),
            sa.ForeignKey("sitemap_audits.audit_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.String(64),
            sa.ForeignKey("sitemap_audit_documents.document_id", ondelete="CASCADE"),
        ),
        sa.Column(
            "entry_id",
            sa.String(64),
            sa.ForeignKey("sitemap_audit_entries.entry_id", ondelete="CASCADE"),
        ),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("safe_message", sa.String(512), nullable=False),
        sa.Column("raw_url", sa.Text()),
        sa.Column("normalized_identity", sa.Text()),
        sa.Column("context_json", sa.Text(), nullable=False),
        sa.Column("finding_sequence", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("audit_id", "finding_sequence", name="uq_sitemap_finding_sequence"),
        sa.CheckConstraint("finding_sequence >= 0", name="ck_sitemap_finding_sequence"),
    )
    op.create_index(
        "ix_sitemap_findings_audit_order",
        "sitemap_audit_findings",
        ["audit_id", "finding_sequence", "finding_id"],
    )
    op.create_index(
        "ix_sitemap_findings_filter", "sitemap_audit_findings", ["audit_id", "severity", "code"]
    )
    op.create_index(
        "ix_sitemap_findings_document",
        "sitemap_audit_findings",
        ["document_id", "finding_sequence"],
    )
    op.create_table(
        "sitemap_audit_comparisons",
        sa.Column("comparison_id", sa.String(64), primary_key=True),
        sa.Column(
            "audit_id",
            sa.String(64),
            sa.ForeignKey("sitemap_audits.audit_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("normalized_identity", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("in_sitemap", sa.Boolean(), nullable=False),
        sa.Column(
            "representative_entry_id",
            sa.String(64),
            sa.ForeignKey("sitemap_audit_entries.entry_id", ondelete="SET NULL"),
        ),
        sa.Column(
            "evidence_id",
            sa.String(64),
            sa.ForeignKey("crawl_page_evidence.evidence_id", ondelete="SET NULL"),
        ),
        sa.Column("recommendation_state", sa.String(32)),
        sa.Column("comparison_state", sa.String(64), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("http_status", sa.Integer()),
        sa.Column("redirect_target", sa.Text()),
        sa.Column("canonical_target", sa.Text()),
        sa.Column("indexability_state", sa.String(32)),
        sa.Column("content_type", sa.String(256)),
        sa.Column("crawl_evidence_state", sa.String(32)),
        sa.Column("record_sequence", sa.Integer(), nullable=False),
        sa.Column("comparison_version", sa.String(64), nullable=False),
        sa.UniqueConstraint(
            "audit_id", "normalized_identity", name="uq_sitemap_comparison_identity"
        ),
        sa.UniqueConstraint("audit_id", "record_sequence", name="uq_sitemap_comparison_sequence"),
        sa.CheckConstraint(
            "action in ('add','remove','review','unchanged')", name="ck_sitemap_comparison_action"
        ),
        sa.CheckConstraint("record_sequence >= 0", name="ck_sitemap_comparison_sequence"),
    )
    op.create_index(
        "ix_sitemap_comparison_order",
        "sitemap_audit_comparisons",
        ["audit_id", "action", "record_sequence"],
    )
    op.create_index(
        "ix_sitemap_comparison_state",
        "sitemap_audit_comparisons",
        ["audit_id", "comparison_state", "reason_code"],
    )
    op.create_index(
        "ix_sitemap_comparison_entry",
        "sitemap_audit_comparisons",
        ["representative_entry_id", "record_sequence"],
    )
    op.create_table(
        "sitemap_audit_exports",
        sa.Column("export_id", sa.String(64), primary_key=True),
        sa.Column(
            "audit_id",
            sa.String(64),
            sa.ForeignKey("sitemap_audits.audit_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("export_format", sa.String(16), nullable=False),
        sa.Column(
            "artifact_id",
            sa.String(64),
            sa.ForeignKey("artifact_records.artifact_id", ondelete="SET NULL"),
        ),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("export_version", sa.String(64), nullable=False),
        sa.UniqueConstraint("audit_id", "export_format", name="uq_sitemap_audit_export_format"),
        sa.CheckConstraint("row_count >= 0", name="ck_sitemap_audit_export_rows"),
    )
    op.create_index(
        "ix_sitemap_audit_exports_audit", "sitemap_audit_exports", ["audit_id", "created_at"]
    )
    op.create_index("ix_sitemap_audit_exports_artifact", "sitemap_audit_exports", ["artifact_id"])
    op.create_table(
        "sitemap_audit_events",
        sa.Column("event_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "audit_id",
            sa.String(64),
            sa.ForeignKey("sitemap_audits.audit_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("safe_code", sa.String(128)),
        sa.Column("counts_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("audit_id", "sequence", name="uq_sitemap_audit_event_sequence"),
    )
    op.create_index(
        "ix_sitemap_audit_events_audit_sequence", "sitemap_audit_events", ["audit_id", "sequence"]
    )


def downgrade() -> None:
    op.drop_index("ix_sitemap_audit_events_audit_sequence", table_name="sitemap_audit_events")
    op.drop_table("sitemap_audit_events")
    op.drop_index("ix_sitemap_audit_exports_artifact", table_name="sitemap_audit_exports")
    op.drop_index("ix_sitemap_audit_exports_audit", table_name="sitemap_audit_exports")
    op.drop_table("sitemap_audit_exports")
    op.drop_index("ix_sitemap_comparison_entry", table_name="sitemap_audit_comparisons")
    op.drop_index("ix_sitemap_comparison_state", table_name="sitemap_audit_comparisons")
    op.drop_index("ix_sitemap_comparison_order", table_name="sitemap_audit_comparisons")
    op.drop_table("sitemap_audit_comparisons")
    op.drop_index("ix_sitemap_findings_document", table_name="sitemap_audit_findings")
    op.drop_index("ix_sitemap_findings_filter", table_name="sitemap_audit_findings")
    op.drop_index("ix_sitemap_findings_audit_order", table_name="sitemap_audit_findings")
    op.drop_table("sitemap_audit_findings")
    op.drop_index("ix_sitemap_entries_validation", table_name="sitemap_audit_entries")
    op.drop_index("ix_sitemap_entries_document_order", table_name="sitemap_audit_entries")
    op.drop_index("ix_sitemap_entries_audit_identity", table_name="sitemap_audit_entries")
    op.drop_table("sitemap_audit_entries")
    op.drop_index("ix_sitemap_documents_parse", table_name="sitemap_audit_documents")
    op.drop_index("ix_sitemap_documents_parent", table_name="sitemap_audit_documents")
    op.drop_index("ix_sitemap_documents_audit_order", table_name="sitemap_audit_documents")
    op.drop_table("sitemap_audit_documents")
    op.drop_index("ix_sitemap_audits_state_created", table_name="sitemap_audits")
    op.drop_index("ix_sitemap_audits_run_created", table_name="sitemap_audits")
    op.drop_table("sitemap_audits")
