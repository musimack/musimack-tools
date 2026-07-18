"""add website migration qa

Revision ID: 0013_website_migration_qa
Revises: 0012_structured_data_audit
"""

# ruff: noqa: E501, TC003

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013_website_migration_qa"
down_revision: str | Sequence[str] | None = "0012_structured_data_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _child_columns() -> list[sa.Column[object]]:
    return [
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(64),
            sa.ForeignKey("migration_qa_projects.project_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "migration_qa_projects",
        sa.Column("project_id", sa.String(64), primary_key=True),
        sa.Column(
            "job_id",
            sa.String(40),
            sa.ForeignKey("jobs.job_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "destination_run_id",
            sa.String(32),
            sa.ForeignKey("runs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_run_id", sa.String(32), sa.ForeignKey("runs.run_id", ondelete="SET NULL")
        ),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("migration_type", sa.String(64), nullable=False),
        sa.Column("source_origin", sa.Text()),
        sa.Column("destination_origin", sa.Text(), nullable=False),
        sa.Column("configuration_json", sa.Text(), nullable=False),
        sa.Column("state", sa.String(64), nullable=False),
        sa.Column("readiness", sa.String(64), nullable=False),
        sa.Column("total_sources", sa.Integer(), nullable=False),
        sa.Column("total_mappings", sa.Integer(), nullable=False),
        sa.Column("total_findings", sa.Integer(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("failure_code", sa.String(128)),
        sa.CheckConstraint(
            "mode IN ('pre_launch','post_launch')", name="ck_migration_project_mode"
        ),
        sa.CheckConstraint(
            "state IN ('draft','ready','running','completed','completed_with_warnings','failed','cancelled')",
            name="ck_migration_project_state",
        ),
    )
    op.create_table(
        "migration_source_rows",
        *_child_columns(),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("raw_url", sa.Text(), nullable=False),
        sa.Column("normalized_url", sa.Text()),
        sa.Column("comparison_url", sa.Text()),
        sa.Column("proposed_destination_url", sa.Text()),
        sa.Column("source_kind", sa.String(64), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("diagnostics_json", sa.Text(), nullable=False),
        sa.UniqueConstraint("project_id", "sequence", name="uq_migration_source_sequence"),
    )
    op.create_table(
        "migration_redirect_map_rows",
        *_child_columns(),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("raw_source_url", sa.Text(), nullable=False),
        sa.Column("raw_destination_url", sa.Text(), nullable=False),
        sa.Column("normalized_source_url", sa.Text()),
        sa.Column("normalized_destination_url", sa.Text()),
        sa.Column("expected_status", sa.Integer()),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("diagnostics_json", sa.Text(), nullable=False),
        sa.UniqueConstraint("project_id", "sequence", name="uq_migration_redirect_sequence"),
    )
    op.create_table(
        "migration_url_mappings",
        *_child_columns(),
        sa.Column(
            "source_row_id",
            sa.String(64),
            sa.ForeignKey("migration_source_rows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("destination_url", sa.Text()),
        sa.Column("mapping_method", sa.String(64), nullable=False),
        sa.Column("cardinality", sa.String(32), nullable=False),
        sa.Column("confidence", sa.String(32), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("bounded_evidence_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "migration_redirect_observations",
        *_child_columns(),
        sa.Column(
            "mapping_id",
            sa.String(64),
            sa.ForeignKey("migration_url_mappings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("planned_destination_url", sa.Text()),
        sa.Column("observed_final_url", sa.Text()),
        sa.Column("observed_status", sa.Integer()),
        sa.Column("chain_json", sa.Text(), nullable=False),
        sa.Column("chain_identity", sa.String(64)),
        sa.Column("loop_identity", sa.String(64)),
        sa.Column("hop_count", sa.Integer(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column("evidence_source", sa.String(64), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "migration_page_comparisons",
        *_child_columns(),
        sa.Column(
            "mapping_id",
            sa.String(64),
            sa.ForeignKey("migration_url_mappings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("destination_url", sa.Text()),
        *[
            sa.Column(name, sa.String(32), nullable=False)
            for name in (
                "status_state",
                "metadata_state",
                "content_state",
                "canonical_state",
                "indexability_state",
            )
        ],
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("similarity_score", sa.String(32)),
        sa.Column("comparison_basis_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "migration_findings",
        sa.Column("stable_id", sa.String(64), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(64),
            sa.ForeignKey("migration_qa_projects.project_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "mapping_id",
            sa.String(64),
            sa.ForeignKey("migration_url_mappings.id", ondelete="CASCADE"),
        ),
        sa.Column("source_url", sa.Text()),
        sa.Column("destination_url", sa.Text()),
        sa.Column("source_evidence_ids_json", sa.Text(), nullable=False),
        sa.Column("destination_evidence_ids_json", sa.Text(), nullable=False),
        sa.Column("code", sa.String(128), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("confidence", sa.String(32), nullable=False),
        sa.Column("requires_human_review", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("bounded_evidence_json", sa.Text(), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("affected_page_count", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "confidence IN ('high','medium','low','indeterminate')",
            name="ck_migration_finding_confidence",
        ),
        sa.UniqueConstraint("project_id", "sequence", name="uq_migration_finding_sequence"),
    )
    op.create_table(
        "migration_recommendations",
        sa.Column("stable_id", sa.String(64), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(64),
            sa.ForeignKey("migration_qa_projects.project_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("confidence", sa.String(32), nullable=False),
        sa.Column("requires_human_review", sa.Boolean(), nullable=False),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("source_url", sa.Text()),
        sa.Column("destination_url", sa.Text()),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("affected_page_count", sa.Integer(), nullable=False),
        sa.Column("supporting_finding_ids_json", sa.Text(), nullable=False),
        sa.Column("supporting_evidence_json", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "sequence", name="uq_migration_recommendation_sequence"),
    )
    op.create_table(
        "migration_sitewide_summaries",
        *_child_columns(),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("metric_name", sa.String(128), nullable=False),
        sa.Column("numerator", sa.Integer(), nullable=False),
        sa.Column("denominator", sa.Integer(), nullable=False),
        sa.Column("ratio", sa.String(32), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "migration_exports",
        *_child_columns(),
        sa.Column("export_format", sa.String(64), nullable=False),
        sa.Column("media_type", sa.String(128), nullable=False),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column(
            "artifact_id",
            sa.String(64),
            sa.ForeignKey("artifact_records.artifact_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.UniqueConstraint("project_id", "export_format", name="uq_migration_project_export"),
    )
    op.create_table(
        "migration_events",
        sa.Column("event_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "project_id",
            sa.String(64),
            sa.ForeignKey("migration_qa_projects.project_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("state", sa.String(64), nullable=False),
        sa.Column("affected_count", sa.Integer(), nullable=False),
        sa.Column("detail", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for table in (
        "migration_source_rows",
        "migration_redirect_map_rows",
        "migration_url_mappings",
        "migration_redirect_observations",
        "migration_page_comparisons",
        "migration_sitewide_summaries",
        "migration_exports",
    ):
        op.create_index(f"ix_{table}_project", table, ["project_id"])
    op.create_index(
        "ix_migration_mapping_project_state",
        "migration_url_mappings",
        ["project_id", "state", "id"],
    )
    op.create_index(
        "ix_migration_mapping_project_method",
        "migration_url_mappings",
        ["project_id", "mapping_method", "id"],
    )
    op.create_index(
        "ix_migration_finding_project_mapping",
        "migration_findings",
        ["project_id", "mapping_id", "sequence"],
    )
    for suffix, column in (
        ("code", "code"),
        ("category", "category"),
        ("severity", "severity"),
        ("confidence", "confidence"),
    ):
        op.create_index(
            f"ix_migration_finding_project_{suffix}",
            "migration_findings",
            ["project_id", column, "sequence"],
        )
    op.create_index(
        "ix_migration_recommendation_project_action",
        "migration_recommendations",
        ["project_id", "action", "sequence"],
    )
    op.create_index(
        "ix_migration_recommendation_project_filter",
        "migration_recommendations",
        ["project_id", "severity", "confidence", "sequence"],
    )
    op.create_index(
        "ix_migration_event_project_order",
        "migration_events",
        ["project_id", "event_id"],
    )


def downgrade() -> None:
    for table in (
        "migration_events",
        "migration_exports",
        "migration_sitewide_summaries",
        "migration_recommendations",
        "migration_findings",
        "migration_page_comparisons",
        "migration_redirect_observations",
        "migration_url_mappings",
        "migration_redirect_map_rows",
        "migration_source_rows",
        "migration_qa_projects",
    ):
        op.drop_table(table)
