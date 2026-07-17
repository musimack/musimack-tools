"""add durable broken-link and redirect analysis

Revision ID: 0009_broken_link_redirect_analysis
Revises: 0008_sitemap_audit
"""

# ruff: noqa: E501, TC003

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_broken_link_redirect_analysis"
down_revision: str | None = "0008_sitemap_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "crawl_link_evidence",
        sa.Column("link_id", sa.String(64), primary_key=True),
        sa.Column(
            "job_id",
            sa.String(64),
            sa.ForeignKey("jobs.job_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.String(64),
            sa.ForeignKey("runs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_evidence_id",
            sa.String(64),
            sa.ForeignKey("crawl_page_evidence.evidence_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_requested_url", sa.Text(), nullable=False),
        sa.Column("source_final_url", sa.Text()),
        sa.Column("source_url_identity", sa.String(64), nullable=False),
        sa.Column("source_discovery_sequence", sa.Integer(), nullable=False),
        sa.Column("source_crawl_depth", sa.Integer(), nullable=False),
        sa.Column("link_sequence", sa.Integer(), nullable=False),
        sa.Column("discovery_sequence", sa.Integer(), nullable=False),
        sa.Column("element_type", sa.String(16), nullable=False),
        sa.Column("raw_href", sa.Text()),
        sa.Column("resolved_url", sa.Text()),
        sa.Column("target_url_identity", sa.String(64)),
        sa.Column("target_scheme", sa.String(32)),
        sa.Column("target_host", sa.String(255)),
        sa.Column("internal", sa.Boolean()),
        sa.Column("in_scope", sa.Boolean()),
        sa.Column("scope_reason_code", sa.String(64)),
        sa.Column("anchor_text", sa.String(512)),
        sa.Column("rel_values_json", sa.Text(), nullable=False),
        sa.Column("nofollow", sa.Boolean(), nullable=False),
        sa.Column("fragment", sa.String(512)),
        sa.Column("link_type", sa.String(32), nullable=False),
        sa.Column("resolution_warning", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_version", sa.String(64), nullable=False),
        sa.UniqueConstraint(
            "source_evidence_id", "link_sequence", name="uq_crawl_link_source_sequence"
        ),
        sa.UniqueConstraint("run_id", "discovery_sequence", name="uq_crawl_link_run_sequence"),
        sa.CheckConstraint(
            "source_discovery_sequence >= 0 and source_crawl_depth >= 0 and link_sequence >= 0 and discovery_sequence >= 0",
            name="ck_crawl_link_sequences",
        ),
        sa.CheckConstraint(
            "link_type in ('http','mailto','tel','javascript','data','fragment','invalid','unsupported')",
            name="ck_crawl_link_type",
        ),
    )
    op.create_index(
        "ix_crawl_link_run_order",
        "crawl_link_evidence",
        ["run_id", "discovery_sequence", "link_id"],
    )
    op.create_index(
        "ix_crawl_link_source", "crawl_link_evidence", ["source_evidence_id", "link_sequence"]
    )
    op.create_index(
        "ix_crawl_link_target",
        "crawl_link_evidence",
        ["run_id", "target_url_identity", "discovery_sequence"],
    )
    op.create_index(
        "ix_crawl_link_scope",
        "crawl_link_evidence",
        ["run_id", "internal", "in_scope", "link_type"],
    )

    op.create_table(
        "link_audits",
        sa.Column("audit_id", sa.String(64), primary_key=True),
        sa.Column(
            "job_id",
            sa.String(64),
            sa.ForeignKey("jobs.job_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.String(64),
            sa.ForeignKey("runs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seed_url", sa.Text(), nullable=False),
        sa.Column("configuration_json", sa.Text(), nullable=False),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("failure_code", sa.String(128)),
        sa.Column("warning_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("link_occurrence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_target_pair_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("target_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("working_target_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("broken_target_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("redirect_target_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unverified_target_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("redirect_chain_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("redirect_loop_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recommendation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("audit_version", sa.String(64), nullable=False),
        sa.Column("link_evidence_version", sa.String(64), nullable=False),
        sa.Column("page_evidence_version", sa.String(64), nullable=False),
        sa.Column("link_policy_version", sa.String(64), nullable=False),
        sa.Column("redirect_policy_version", sa.String(64), nullable=False),
        sa.CheckConstraint(
            "state in ('accepted','claiming','building_graph','classifying_links','expanding_redirects','detecting_loops','building_recommendations','completed','completed_with_warnings','failed','cancelled')",
            name="ck_link_audits_state",
        ),
        sa.CheckConstraint(
            "warning_count >= 0 and link_occurrence_count >= 0 and source_target_pair_count >= 0 and target_count >= 0 and working_target_count >= 0 and broken_target_count >= 0 and redirect_target_count >= 0 and unverified_target_count >= 0 and redirect_chain_count >= 0 and redirect_loop_count >= 0 and recommendation_count >= 0",
            name="ck_link_audits_counts",
        ),
    )
    op.create_index(
        "ix_link_audits_run_created", "link_audits", ["run_id", "created_at", "audit_id"]
    )
    op.create_index(
        "ix_link_audits_state_created", "link_audits", ["state", "created_at", "audit_id"]
    )

    op.create_table(
        "link_audit_targets",
        sa.Column("target_id", sa.String(64), primary_key=True),
        sa.Column(
            "audit_id",
            sa.String(64),
            sa.ForeignKey("link_audits.audit_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_url", sa.Text(), nullable=False),
        sa.Column("target_url_identity", sa.String(64), nullable=False),
        sa.Column(
            "representative_link_id",
            sa.String(64),
            sa.ForeignKey("crawl_link_evidence.link_id", ondelete="SET NULL"),
        ),
        sa.Column(
            "page_evidence_id",
            sa.String(64),
            sa.ForeignKey("crawl_page_evidence.evidence_id", ondelete="SET NULL"),
        ),
        sa.Column("internal", sa.Boolean()),
        sa.Column("in_scope", sa.Boolean()),
        sa.Column("http_status", sa.Integer()),
        sa.Column("fetch_state", sa.String(32)),
        sa.Column("content_type", sa.String(256)),
        sa.Column("broken_state", sa.String(48), nullable=False),
        sa.Column("redirect_state", sa.String(48), nullable=False),
        sa.Column("primary_reason", sa.String(64), nullable=False),
        sa.Column("redirect_reason", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("action", sa.String(48), nullable=False),
        sa.Column("confidence", sa.String(16), nullable=False),
        sa.Column("final_target", sa.Text()),
        sa.Column("redirect_hop_count", sa.Integer(), nullable=False),
        sa.Column("unique_source_page_count", sa.Integer(), nullable=False),
        sa.Column("total_occurrence_count", sa.Integer(), nullable=False),
        sa.Column("unique_anchor_count", sa.Integer(), nullable=False),
        sa.Column("minimum_source_depth", sa.Integer(), nullable=False),
        sa.Column("maximum_source_depth", sa.Integer(), nullable=False),
        sa.Column("sitewide_candidate", sa.Boolean(), nullable=False),
        sa.Column("target_sequence", sa.Integer(), nullable=False),
        sa.Column("analysis_version", sa.String(64), nullable=False),
        sa.UniqueConstraint(
            "audit_id", "target_url_identity", name="uq_link_audit_target_identity"
        ),
        sa.UniqueConstraint("audit_id", "target_sequence", name="uq_link_audit_target_sequence"),
        sa.CheckConstraint(
            "redirect_hop_count >= 0 and unique_source_page_count >= 0 and total_occurrence_count >= 0 and unique_anchor_count >= 0 and minimum_source_depth >= 0 and maximum_source_depth >= minimum_source_depth and target_sequence >= 0",
            name="ck_link_audit_target_metrics",
        ),
    )
    op.create_index(
        "ix_link_target_order", "link_audit_targets", ["audit_id", "target_sequence", "target_id"]
    )
    op.create_index(
        "ix_link_target_state", "link_audit_targets", ["audit_id", "broken_state", "redirect_state"]
    )
    op.create_index(
        "ix_link_target_filter",
        "link_audit_targets",
        ["audit_id", "severity", "action", "primary_reason"],
    )
    op.create_index(
        "ix_link_target_impact",
        "link_audit_targets",
        ["audit_id", "sitewide_candidate", "unique_source_page_count"],
    )

    op.create_table(
        "link_audit_redirect_chains",
        sa.Column("chain_id", sa.String(64), primary_key=True),
        sa.Column(
            "audit_id",
            sa.String(64),
            sa.ForeignKey("link_audits.audit_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_id",
            sa.String(64),
            sa.ForeignKey("link_audit_targets.target_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entry_url", sa.Text(), nullable=False),
        sa.Column("final_url", sa.Text()),
        sa.Column("chain_state", sa.String(48), nullable=False),
        sa.Column("hop_count", sa.Integer(), nullable=False),
        sa.Column("loop", sa.Boolean(), nullable=False),
        sa.Column("nodes_json", sa.Text(), nullable=False),
        sa.Column("edges_json", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("source_occurrence_count", sa.Integer(), nullable=False),
        sa.Column("chain_sequence", sa.Integer(), nullable=False),
        sa.Column("chain_version", sa.String(64), nullable=False),
        sa.UniqueConstraint("audit_id", "target_id", name="uq_link_chain_target"),
        sa.UniqueConstraint("audit_id", "chain_sequence", name="uq_link_chain_sequence"),
        sa.CheckConstraint(
            "hop_count >= 0 and source_occurrence_count >= 0 and chain_sequence >= 0",
            name="ck_link_chain_metrics",
        ),
    )
    op.create_index(
        "ix_link_chain_order",
        "link_audit_redirect_chains",
        ["audit_id", "chain_sequence", "chain_id"],
    )
    op.create_index(
        "ix_link_chain_loop", "link_audit_redirect_chains", ["audit_id", "loop", "severity"]
    )

    op.create_table(
        "link_audit_findings",
        sa.Column("finding_id", sa.String(64), primary_key=True),
        sa.Column(
            "audit_id",
            sa.String(64),
            sa.ForeignKey("link_audits.audit_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_id",
            sa.String(64),
            sa.ForeignKey("link_audit_targets.target_id", ondelete="CASCADE"),
        ),
        sa.Column(
            "chain_id",
            sa.String(64),
            sa.ForeignKey("link_audit_redirect_chains.chain_id", ondelete="CASCADE"),
        ),
        sa.Column("stable_code", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("safe_message", sa.String(512), nullable=False),
        sa.Column("context_json", sa.Text(), nullable=False),
        sa.Column("finding_sequence", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("audit_id", "finding_sequence", name="uq_link_finding_sequence"),
    )
    op.create_index(
        "ix_link_finding_order",
        "link_audit_findings",
        ["audit_id", "finding_sequence", "finding_id"],
    )
    op.create_index(
        "ix_link_finding_filter", "link_audit_findings", ["audit_id", "severity", "stable_code"]
    )

    op.create_table(
        "link_audit_recommendations",
        sa.Column("recommendation_id", sa.String(64), primary_key=True),
        sa.Column(
            "audit_id",
            sa.String(64),
            sa.ForeignKey("link_audits.audit_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_id",
            sa.String(64),
            sa.ForeignKey("link_audit_targets.target_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("suggested_destination", sa.Text()),
        sa.Column("action", sa.String(48), nullable=False),
        sa.Column("confidence", sa.String(16), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("human_review_required", sa.Boolean(), nullable=False),
        sa.Column("supporting_evidence_json", sa.Text(), nullable=False),
        sa.Column("unique_source_page_count", sa.Integer(), nullable=False),
        sa.Column("total_occurrence_count", sa.Integer(), nullable=False),
        sa.Column("recommendation_sequence", sa.Integer(), nullable=False),
        sa.UniqueConstraint("audit_id", "target_id", name="uq_link_recommendation_target"),
        sa.UniqueConstraint(
            "audit_id", "recommendation_sequence", name="uq_link_recommendation_sequence"
        ),
    )
    op.create_index(
        "ix_link_recommendation_order",
        "link_audit_recommendations",
        ["audit_id", "recommendation_sequence", "recommendation_id"],
    )
    op.create_index(
        "ix_link_recommendation_filter",
        "link_audit_recommendations",
        ["audit_id", "action", "confidence", "severity"],
    )

    op.create_table(
        "link_audit_exports",
        sa.Column("export_id", sa.String(64), primary_key=True),
        sa.Column(
            "audit_id",
            sa.String(64),
            sa.ForeignKey("link_audits.audit_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("export_format", sa.String(32), nullable=False),
        sa.Column(
            "artifact_id",
            sa.String(64),
            sa.ForeignKey("artifact_records.artifact_id", ondelete="SET NULL"),
        ),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("export_version", sa.String(64), nullable=False),
        sa.UniqueConstraint("audit_id", "export_format", name="uq_link_audit_export_format"),
    )
    op.create_index(
        "ix_link_export_audit", "link_audit_exports", ["audit_id", "created_at", "export_id"]
    )
    op.create_index("ix_link_export_artifact", "link_audit_exports", ["artifact_id"])

    op.create_table(
        "link_audit_events",
        sa.Column("event_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "audit_id",
            sa.String(64),
            sa.ForeignKey("link_audits.audit_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("safe_code", sa.String(128)),
        sa.Column("counts_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("audit_id", "sequence", name="uq_link_audit_event_sequence"),
    )
    op.create_index("ix_link_event_order", "link_audit_events", ["audit_id", "sequence"])


def downgrade() -> None:
    op.drop_index("ix_link_event_order", table_name="link_audit_events")
    op.drop_table("link_audit_events")
    op.drop_index("ix_link_export_artifact", table_name="link_audit_exports")
    op.drop_index("ix_link_export_audit", table_name="link_audit_exports")
    op.drop_table("link_audit_exports")
    op.drop_index("ix_link_recommendation_filter", table_name="link_audit_recommendations")
    op.drop_index("ix_link_recommendation_order", table_name="link_audit_recommendations")
    op.drop_table("link_audit_recommendations")
    op.drop_index("ix_link_finding_filter", table_name="link_audit_findings")
    op.drop_index("ix_link_finding_order", table_name="link_audit_findings")
    op.drop_table("link_audit_findings")
    op.drop_index("ix_link_chain_loop", table_name="link_audit_redirect_chains")
    op.drop_index("ix_link_chain_order", table_name="link_audit_redirect_chains")
    op.drop_table("link_audit_redirect_chains")
    op.drop_index("ix_link_target_impact", table_name="link_audit_targets")
    op.drop_index("ix_link_target_filter", table_name="link_audit_targets")
    op.drop_index("ix_link_target_state", table_name="link_audit_targets")
    op.drop_index("ix_link_target_order", table_name="link_audit_targets")
    op.drop_table("link_audit_targets")
    op.drop_index("ix_link_audits_state_created", table_name="link_audits")
    op.drop_index("ix_link_audits_run_created", table_name="link_audits")
    op.drop_table("link_audits")
    op.drop_index("ix_crawl_link_scope", table_name="crawl_link_evidence")
    op.drop_index("ix_crawl_link_target", table_name="crawl_link_evidence")
    op.drop_index("ix_crawl_link_source", table_name="crawl_link_evidence")
    op.drop_index("ix_crawl_link_run_order", table_name="crawl_link_evidence")
    op.drop_table("crawl_link_evidence")
