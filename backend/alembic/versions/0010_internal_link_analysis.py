"""Add durable internal-link analysis.

Revision ID: 0010_internal_link_analysis
Revises: 0009_broken_link_redirect_analysis
"""

# ruff: noqa: E501, I001, TC003

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_internal_link_analysis"
down_revision: str | None = "0009_broken_link_redirect_analysis"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "internal_link_audits",
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
        sa.Column("scope_snapshot_json", sa.Text(), nullable=False),
        sa.Column("seed_snapshot_json", sa.Text(), nullable=False),
        sa.Column("configuration_json", sa.Text(), nullable=False),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("failure_code", sa.String(128)),
        *[
            sa.Column(name, sa.Integer(), nullable=False, server_default="0")
            for name in (
                "warning_count",
                "node_count",
                "eligible_page_count",
                "edge_occurrence_count",
                "unique_edge_count",
                "reachable_count",
                "orphan_candidate_count",
                "deep_page_count",
                "hub_candidate_count",
                "authority_candidate_count",
                "anchor_finding_count",
                "opportunity_count",
            )
        ],
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("audit_version", sa.String(64), nullable=False),
        sa.Column("graph_version", sa.String(64), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("page_evidence_version", sa.String(64), nullable=False),
        sa.Column("link_evidence_version", sa.String(64), nullable=False),
        sa.CheckConstraint(
            "state in ('accepted','claiming','building_graph','computing_metrics','analyzing_reachability','analyzing_anchors','building_opportunities','completed','completed_with_warnings','failed','cancelled')",
            name="ck_internal_link_audit_state",
        ),
        sa.CheckConstraint(
            "warning_count >= 0 and node_count >= 0 and eligible_page_count >= 0 and edge_occurrence_count >= 0 and unique_edge_count >= 0 and reachable_count >= 0 and orphan_candidate_count >= 0 and deep_page_count >= 0 and hub_candidate_count >= 0 and authority_candidate_count >= 0 and anchor_finding_count >= 0 and opportunity_count >= 0",
            name="ck_internal_link_audit_counts",
        ),
    )
    op.create_index(
        "ix_internal_link_audit_run", "internal_link_audits", ["run_id", "created_at", "audit_id"]
    )
    op.create_index(
        "ix_internal_link_audit_state", "internal_link_audits", ["state", "created_at", "audit_id"]
    )
    op.create_table(
        "internal_link_page_metrics",
        sa.Column("metric_id", sa.String(64), primary_key=True),
        sa.Column(
            "audit_id",
            sa.String(64),
            sa.ForeignKey("internal_link_audits.audit_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "page_evidence_id",
            sa.String(64),
            sa.ForeignKey("crawl_page_evidence.evidence_id", ondelete="SET NULL"),
        ),
        sa.Column("requested_url", sa.Text(), nullable=False),
        sa.Column("final_url", sa.Text()),
        sa.Column("page_identity", sa.String(64), nullable=False),
        sa.Column("canonical_identity", sa.String(64)),
        sa.Column("eligibility", sa.String(40), nullable=False),
        sa.Column("exclusion_reason", sa.String(64)),
        sa.Column("primary_state", sa.String(40), nullable=False),
        sa.Column("orphan_state", sa.String(48), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        *[
            sa.Column(name, sa.Integer(), nullable=False, server_default="0")
            for name in (
                "inbound_occurrences",
                "unique_referring_pages",
                "outbound_occurrences",
                "unique_destination_pages",
                "direct_inlinks",
                "redirect_adjusted_inlinks",
                "nofollow_inlinks",
                "nofollow_outlinks",
                "redirecting_outlinks",
                "broken_outlinks",
                "external_outlinks",
                "sitewide_inlinks",
                "non_sitewide_inlinks",
                "crawl_depth",
                "distinct_seed_paths",
                "unique_anchor_count",
                "url_anchor_count",
                "discovery_sequence",
                "page_sequence",
            )
        ],
        sa.Column("graph_depth", sa.Integer()),
        sa.Column("reachable", sa.Boolean(), nullable=False),
        sa.Column("dominant_anchor", sa.String(512)),
        sa.Column("dominant_anchor_share", sa.Float(), nullable=False, server_default="0"),
        sa.Column("hub_state", sa.String(32), nullable=False),
        sa.Column("authority_state", sa.String(32), nullable=False),
        sa.UniqueConstraint("audit_id", "page_identity", name="uq_internal_link_page_identity"),
        sa.UniqueConstraint("audit_id", "page_sequence", name="uq_internal_link_page_sequence"),
        sa.CheckConstraint(
            "inbound_occurrences >= 0 and unique_referring_pages >= 0 and outbound_occurrences >= 0 and unique_destination_pages >= 0 and direct_inlinks >= 0 and redirect_adjusted_inlinks >= 0 and nofollow_inlinks >= 0 and nofollow_outlinks >= 0 and redirecting_outlinks >= 0 and broken_outlinks >= 0 and external_outlinks >= 0 and sitewide_inlinks >= 0 and non_sitewide_inlinks >= 0 and crawl_depth >= 0 and (graph_depth is null or graph_depth >= 0) and distinct_seed_paths >= 0 and unique_anchor_count >= 0 and dominant_anchor_share >= 0 and dominant_anchor_share <= 1 and url_anchor_count >= 0 and discovery_sequence >= 0 and page_sequence >= 0",
            name="ck_internal_link_page_metrics",
        ),
    )
    op.create_index(
        "ix_internal_link_page_order",
        "internal_link_page_metrics",
        ["audit_id", "page_sequence", "metric_id"],
    )
    op.create_index(
        "ix_internal_link_page_states",
        "internal_link_page_metrics",
        ["audit_id", "eligibility", "primary_state", "orphan_state"],
    )
    op.create_index(
        "ix_internal_link_page_candidates",
        "internal_link_page_metrics",
        ["audit_id", "hub_state", "authority_state", "severity"],
    )
    op.create_table(
        "internal_link_edges",
        sa.Column("edge_id", sa.String(64), primary_key=True),
        sa.Column(
            "audit_id",
            sa.String(64),
            sa.ForeignKey("internal_link_audits.audit_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_identity", sa.String(64), nullable=False),
        sa.Column("target_identity", sa.String(64), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("target_url", sa.Text(), nullable=False),
        sa.Column("redirect_adjusted_identity", sa.String(64)),
        sa.Column("canonical_adjusted_identity", sa.String(64)),
        sa.Column("raw_occurrence_count", sa.Integer(), nullable=False),
        sa.Column("nofollow_occurrence_count", sa.Integer(), nullable=False),
        sa.Column("sitewide", sa.Boolean(), nullable=False),
        sa.Column("edge_state", sa.String(40), nullable=False),
        sa.Column("anchor_summary_json", sa.Text(), nullable=False),
        sa.Column("edge_sequence", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "audit_id", "source_identity", "target_identity", name="uq_internal_link_edge_pair"
        ),
        sa.UniqueConstraint("audit_id", "edge_sequence", name="uq_internal_link_edge_sequence"),
        sa.CheckConstraint(
            "raw_occurrence_count > 0 and nofollow_occurrence_count >= 0 and edge_sequence >= 0",
            name="ck_internal_link_edge_counts",
        ),
    )
    op.create_index(
        "ix_internal_link_edge_order",
        "internal_link_edges",
        ["audit_id", "edge_sequence", "edge_id"],
    )
    op.create_index(
        "ix_internal_link_edge_source_target",
        "internal_link_edges",
        ["audit_id", "source_identity", "target_identity"],
    )
    op.create_table(
        "internal_link_reachability",
        sa.Column("reachability_id", sa.String(64), primary_key=True),
        sa.Column(
            "audit_id",
            sa.String(64),
            sa.ForeignKey("internal_link_audits.audit_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_identity", sa.String(64), nullable=False),
        sa.Column("seed_identity", sa.String(64)),
        sa.Column("predecessor_identity", sa.String(64)),
        sa.Column("distance", sa.Integer()),
        sa.Column("reachable", sa.Boolean(), nullable=False),
        sa.Column("redirect_dependent", sa.Boolean(), nullable=False),
        sa.Column("nofollow_only", sa.Boolean(), nullable=False),
        sa.Column("path_json", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.UniqueConstraint("audit_id", "page_identity", name="uq_internal_link_reachability_page"),
        sa.UniqueConstraint("audit_id", "sequence", name="uq_internal_link_reachability_sequence"),
    )
    op.create_index(
        "ix_internal_link_reachability_order",
        "internal_link_reachability",
        ["audit_id", "sequence"],
    )
    op.create_index(
        "ix_internal_link_reachability_state",
        "internal_link_reachability",
        ["audit_id", "reachable", "distance"],
    )
    op.create_table(
        "internal_link_findings",
        sa.Column("finding_id", sa.String(64), primary_key=True),
        sa.Column(
            "audit_id",
            sa.String(64),
            sa.ForeignKey("internal_link_audits.audit_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_identity", sa.String(64)),
        sa.Column(
            "edge_id",
            sa.String(64),
            sa.ForeignKey("internal_link_edges.edge_id", ondelete="CASCADE"),
        ),
        sa.Column("stable_code", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("safe_message", sa.String(512), nullable=False),
        sa.Column("context_json", sa.Text(), nullable=False),
        sa.Column("finding_sequence", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "audit_id", "finding_sequence", name="uq_internal_link_finding_sequence"
        ),
    )
    op.create_index(
        "ix_internal_link_finding_order", "internal_link_findings", ["audit_id", "finding_sequence"]
    )
    op.create_index(
        "ix_internal_link_finding_filter",
        "internal_link_findings",
        ["audit_id", "severity", "stable_code"],
    )
    op.create_table(
        "internal_link_anchor_aggregates",
        sa.Column("anchor_id", sa.String(64), primary_key=True),
        sa.Column(
            "audit_id",
            sa.String(64),
            sa.ForeignKey("internal_link_audits.audit_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_identity", sa.String(64), nullable=False),
        sa.Column("target_url", sa.Text(), nullable=False),
        sa.Column("normalized_anchor", sa.String(512), nullable=False),
        sa.Column("representative_anchor", sa.String(512)),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("source_page_count", sa.Integer(), nullable=False),
        sa.Column("share", sa.Float(), nullable=False),
        sa.Column("anchor_state", sa.String(48), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("sample_sources_json", sa.Text(), nullable=False),
        sa.Column("anchor_sequence", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "audit_id", "target_identity", "normalized_anchor", name="uq_internal_link_anchor_group"
        ),
        sa.UniqueConstraint("audit_id", "anchor_sequence", name="uq_internal_link_anchor_sequence"),
        sa.CheckConstraint(
            "occurrence_count > 0 and source_page_count > 0 and share >= 0 and share <= 1 and anchor_sequence >= 0",
            name="ck_internal_link_anchor_metrics",
        ),
    )
    op.create_index(
        "ix_internal_link_anchor_order",
        "internal_link_anchor_aggregates",
        ["audit_id", "anchor_sequence"],
    )
    op.create_index(
        "ix_internal_link_anchor_filter",
        "internal_link_anchor_aggregates",
        ["audit_id", "anchor_state", "severity"],
    )
    op.create_table(
        "internal_link_opportunities",
        sa.Column("opportunity_id", sa.String(64), primary_key=True),
        sa.Column(
            "audit_id",
            sa.String(64),
            sa.ForeignKey("internal_link_audits.audit_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_identity", sa.String(64)),
        sa.Column("source_url", sa.Text()),
        sa.Column("target_identity", sa.String(64), nullable=False),
        sa.Column("target_url", sa.Text(), nullable=False),
        sa.Column("opportunity_type", sa.String(48), nullable=False),
        sa.Column("action", sa.String(48), nullable=False),
        sa.Column("confidence", sa.String(16), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("human_review_required", sa.Boolean(), nullable=False),
        sa.Column("supporting_metrics_json", sa.Text(), nullable=False),
        sa.Column("opportunity_sequence", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "audit_id", "opportunity_sequence", name="uq_internal_link_opportunity_sequence"
        ),
    )
    op.create_index(
        "ix_internal_link_opportunity_order",
        "internal_link_opportunities",
        ["audit_id", "opportunity_sequence"],
    )
    op.create_index(
        "ix_internal_link_opportunity_filter",
        "internal_link_opportunities",
        ["audit_id", "opportunity_type", "action", "confidence", "severity"],
    )
    op.create_table(
        "internal_link_exports",
        sa.Column("export_id", sa.String(64), primary_key=True),
        sa.Column(
            "audit_id",
            sa.String(64),
            sa.ForeignKey("internal_link_audits.audit_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("export_format", sa.String(40), nullable=False),
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
        sa.UniqueConstraint("audit_id", "export_format", name="uq_internal_link_export_format"),
    )
    op.create_index(
        "ix_internal_link_export_audit",
        "internal_link_exports",
        ["audit_id", "created_at", "export_id"],
    )
    op.create_index("ix_internal_link_export_artifact", "internal_link_exports", ["artifact_id"])
    op.create_table(
        "internal_link_events",
        sa.Column("event_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "audit_id",
            sa.String(64),
            sa.ForeignKey("internal_link_audits.audit_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("safe_code", sa.String(128)),
        sa.Column("counts_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("audit_id", "sequence", name="uq_internal_link_event_sequence"),
    )
    op.create_index(
        "ix_internal_link_event_order", "internal_link_events", ["audit_id", "sequence"]
    )


def downgrade() -> None:
    for table in (
        "internal_link_events",
        "internal_link_exports",
        "internal_link_opportunities",
        "internal_link_anchor_aggregates",
        "internal_link_findings",
        "internal_link_reachability",
        "internal_link_edges",
        "internal_link_page_metrics",
        "internal_link_audits",
    ):
        op.drop_table(table)
