"""add durable page crawl evidence

Revision ID: 0006_page_crawl_evidence
Revises: 0005_authentication_authorization
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0006_page_crawl_evidence"
down_revision = "0005_authentication_authorization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crawl_page_evidence",
        sa.Column("evidence_id", sa.String(64), primary_key=True),
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
        sa.Column("requested_url", sa.Text, nullable=False),
        sa.Column("requested_url_identity", sa.String(64), nullable=False),
        sa.Column("final_url", sa.Text),
        sa.Column("final_url_identity", sa.String(64)),
        sa.Column("discovery_sequence", sa.Integer, nullable=False),
        sa.Column("crawl_depth", sa.Integer, nullable=False),
        sa.Column("referrer_url", sa.Text),
        sa.Column("frontier_state", sa.String(16), nullable=False),
        sa.Column("fetch_outcome", sa.String(32), nullable=False),
        sa.Column("http_status", sa.Integer),
        sa.Column("status_class", sa.Integer),
        sa.Column("fetch_failed", sa.Boolean, nullable=False),
        sa.Column("redirect_count", sa.Integer, nullable=False),
        sa.Column("redirect_truncated", sa.Boolean, nullable=False),
        sa.Column("redirect_loop", sa.Boolean, nullable=False),
        sa.Column("content_type", sa.String(256)),
        sa.Column("content_type_category", sa.String(16), nullable=False),
        sa.Column("charset", sa.String(64)),
        sa.Column("parsed_as_html", sa.Boolean, nullable=False),
        sa.Column("parse_outcome", sa.String(16)),
        sa.Column("title_presence", sa.String(16), nullable=False),
        sa.Column("title_value", sa.Text),
        sa.Column("title_normalized_hash", sa.String(64)),
        sa.Column("title_count", sa.Integer, nullable=False),
        sa.Column("title_length", sa.Integer),
        sa.Column("title_truncated", sa.Boolean, nullable=False),
        sa.Column("description_presence", sa.String(16), nullable=False),
        sa.Column("description_value", sa.Text),
        sa.Column("description_normalized_hash", sa.String(64)),
        sa.Column("description_count", sa.Integer, nullable=False),
        sa.Column("description_length", sa.Integer),
        sa.Column("description_truncated", sa.Boolean, nullable=False),
        sa.Column("canonical_presence", sa.String(16), nullable=False),
        sa.Column("canonical_url", sa.Text),
        sa.Column("canonical_url_identity", sa.String(64)),
        sa.Column("canonical_count", sa.Integer, nullable=False),
        sa.Column("canonical_conflicting", sa.Boolean, nullable=False),
        sa.Column("canonical_cross_host", sa.Boolean, nullable=False),
        sa.Column("canonical_cross_scheme", sa.Boolean, nullable=False),
        sa.Column("canonical_cross_port", sa.Boolean, nullable=False),
        sa.Column("canonical_truncated", sa.Boolean, nullable=False),
        sa.Column("meta_robots_json", sa.Text, nullable=False),
        sa.Column("x_robots_json", sa.Text, nullable=False),
        sa.Column("robots_allowed", sa.Boolean),
        sa.Column("robots_reason_code", sa.String(64)),
        sa.Column("robots_evidence_json", sa.Text, nullable=False),
        sa.Column("indexability_evidence_json", sa.Text, nullable=False),
        sa.Column("indexability_state", sa.String(16), nullable=False),
        sa.Column("parse_warning_count", sa.Integer, nullable=False),
        sa.Column("parse_warnings_truncated", sa.Boolean, nullable=False),
        sa.Column("evidence_state", sa.String(16), nullable=False),
        sa.Column("failure_code", sa.String(64)),
        sa.Column("value_truncated", sa.Boolean, nullable=False),
        sa.Column("retention_state", sa.String(24), nullable=False),
        sa.Column("retention_hold", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("persisted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_version", sa.String(64), nullable=False),
        sa.Column("persistence_version", sa.String(64), nullable=False),
        sa.Column("projection_version", sa.String(64), nullable=False),
        sa.UniqueConstraint("run_id", "discovery_sequence", name="uq_page_evidence_run_sequence"),
        sa.UniqueConstraint("run_id", "requested_url_identity", name="uq_page_evidence_run_url"),
        sa.CheckConstraint("discovery_sequence >= 0", name="ck_page_evidence_sequence"),
        sa.CheckConstraint("crawl_depth >= 0", name="ck_page_evidence_depth"),
        sa.CheckConstraint("redirect_count >= 0", name="ck_page_evidence_redirect_count"),
        sa.CheckConstraint(
            "http_status IS NULL OR (http_status >= 100 AND http_status <= 599)",
            name="ck_page_evidence_http_status",
        ),
        sa.CheckConstraint(
            "status_class IS NULL OR (status_class >= 1 AND status_class <= 5)",
            name="ck_page_evidence_status_class",
        ),
        sa.CheckConstraint(
            "content_type_category IN "
            "('html','pdf','image','json','plain_text','xml','other','ambiguous','missing')",
            name="ck_page_evidence_content_category",
        ),
        sa.CheckConstraint(
            "title_presence IN ('missing','empty','single','multiple','unavailable')",
            name="ck_page_evidence_title_presence",
        ),
        sa.CheckConstraint(
            "description_presence IN ('missing','empty','single','multiple','unavailable')",
            name="ck_page_evidence_description_presence",
        ),
        sa.CheckConstraint(
            "canonical_presence IN ('missing','empty','single','multiple','unavailable')",
            name="ck_page_evidence_canonical_presence",
        ),
        sa.CheckConstraint(
            "evidence_state IN "
            "('complete','partial','fetch_failed','not_html','cancelled','truncated','unavailable')",
            name="ck_page_evidence_state",
        ),
        sa.CheckConstraint(
            "indexability_state IN ('available','conflicting','unavailable')",
            name="ck_page_evidence_indexability_state",
        ),
        sa.CheckConstraint(
            "retention_state IN "
            "('active','retained','expired','cleanup_pending','deleted','metadata_only')",
            name="ck_page_evidence_retention_state",
        ),
    )
    for name, columns in (
        ("ix_page_evidence_run_order", ["run_id", "discovery_sequence", "requested_url_identity"]),
        ("ix_page_evidence_job_order", ["job_id", "discovery_sequence"]),
        ("ix_page_evidence_requested_url", ["requested_url_identity"]),
        ("ix_page_evidence_final_url", ["final_url_identity"]),
        ("ix_page_evidence_status", ["http_status", "discovery_sequence"]),
        ("ix_page_evidence_content_type", ["content_type_category", "discovery_sequence"]),
        ("ix_page_evidence_robots", ["robots_allowed", "discovery_sequence"]),
        ("ix_page_evidence_indexability", ["indexability_state", "discovery_sequence"]),
        ("ix_page_evidence_state", ["evidence_state", "discovery_sequence"]),
        ("ix_page_evidence_depth", ["crawl_depth", "discovery_sequence"]),
        ("ix_page_evidence_expiry", ["retention_state", "expires_at"]),
    ):
        op.create_index(name, "crawl_page_evidence", columns)
    op.create_table(
        "crawl_page_redirect_hops",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "evidence_id",
            sa.String(64),
            sa.ForeignKey("crawl_page_evidence.evidence_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("source_url", sa.Text, nullable=False),
        sa.Column("target_url", sa.Text),
        sa.Column("status_code", sa.Integer, nullable=False),
        sa.Column("cross_host", sa.Boolean, nullable=False),
        sa.Column("terminal", sa.Boolean, nullable=False),
        sa.Column("loop", sa.Boolean, nullable=False),
        sa.Column("failure_code", sa.String(64)),
        sa.UniqueConstraint("evidence_id", "sequence", name="uq_page_redirect_evidence_sequence"),
        sa.CheckConstraint("sequence > 0", name="ck_page_redirect_sequence"),
    )
    op.create_index(
        "ix_page_redirect_evidence", "crawl_page_redirect_hops", ["evidence_id", "sequence"]
    )
    op.create_table(
        "crawl_page_parse_warnings",
        sa.Column("warning_id", sa.String(64), primary_key=True),
        sa.Column(
            "evidence_id",
            sa.String(64),
            sa.ForeignKey("crawl_page_evidence.evidence_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("stable_code", sa.String(128), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("safe_summary", sa.String(512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("warning_version", sa.String(64), nullable=False),
        sa.UniqueConstraint("evidence_id", "sequence", name="uq_page_warning_evidence_sequence"),
    )
    op.create_index(
        "ix_page_warning_evidence", "crawl_page_parse_warnings", ["evidence_id", "sequence"]
    )
    op.create_index(
        "ix_page_warning_code", "crawl_page_parse_warnings", ["stable_code", "warning_id"]
    )
    op.create_table(
        "crawl_page_evidence_summaries",
        sa.Column(
            "run_id",
            sa.String(32),
            sa.ForeignKey("runs.run_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "job_id",
            sa.String(40),
            sa.ForeignKey("jobs.job_id", ondelete="CASCADE"),
            nullable=False,
        ),
        *[
            sa.Column(name, sa.Integer, nullable=False)
            for name in (
                "total_records",
                "completed_records",
                "partial_records",
                "failed_records",
                "html_records",
                "non_html_records",
                "redirect_records",
                "parse_warning_count",
                "truncated_records",
                "title_evidence_count",
                "description_evidence_count",
                "canonical_evidence_count",
                "source_page_count",
            )
        ],
        sa.Column("status_class_counts_json", sa.Text, nullable=False),
        sa.Column("content_type_counts_json", sa.Text, nullable=False),
        sa.Column("robots_permission_counts_json", sa.Text, nullable=False),
        sa.Column("indexability_counts_json", sa.Text, nullable=False),
        sa.Column("projection_truncated", sa.Boolean, nullable=False),
        sa.Column("persisted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retention_state", sa.String(24), nullable=False),
        sa.Column("evidence_version", sa.String(64), nullable=False),
        sa.Column("persistence_version", sa.String(64), nullable=False),
        sa.Column("ordering_version", sa.String(64), nullable=False),
    )
    op.create_index("ix_page_summary_job", "crawl_page_evidence_summaries", ["job_id", "run_id"])
    op.create_table(
        "crawl_page_evidence_events",
        sa.Column("event_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.String(32),
            sa.ForeignKey("runs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.String(40),
            sa.ForeignKey("jobs.job_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("safe_reason_code", sa.String(64)),
        sa.Column("affected_count", sa.Integer, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_version", sa.String(64), nullable=False),
    )
    op.create_index(
        "ix_page_evidence_events_run", "crawl_page_evidence_events", ["run_id", "event_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_page_evidence_events_run", table_name="crawl_page_evidence_events")
    op.drop_table("crawl_page_evidence_events")
    op.drop_index("ix_page_summary_job", table_name="crawl_page_evidence_summaries")
    op.drop_table("crawl_page_evidence_summaries")
    op.drop_index("ix_page_warning_code", table_name="crawl_page_parse_warnings")
    op.drop_index("ix_page_warning_evidence", table_name="crawl_page_parse_warnings")
    op.drop_table("crawl_page_parse_warnings")
    op.drop_index("ix_page_redirect_evidence", table_name="crawl_page_redirect_hops")
    op.drop_table("crawl_page_redirect_hops")
    for name in (
        "ix_page_evidence_expiry",
        "ix_page_evidence_depth",
        "ix_page_evidence_state",
        "ix_page_evidence_robots",
        "ix_page_evidence_indexability",
        "ix_page_evidence_content_type",
        "ix_page_evidence_status",
        "ix_page_evidence_final_url",
        "ix_page_evidence_requested_url",
        "ix_page_evidence_job_order",
        "ix_page_evidence_run_order",
    ):
        op.drop_index(name, table_name="crawl_page_evidence")
    op.drop_table("crawl_page_evidence")
