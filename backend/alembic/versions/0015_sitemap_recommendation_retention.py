"""retain URL-level sitemap recommendations

Revision ID: 0015_sitemap_recommendation_retention
Revises: 0014_durable_result_projection
"""

# ruff: noqa: TC003

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015_sitemap_recommendation_retention"
down_revision: str | Sequence[str] | None = "0014_durable_result_projection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column(
            "recommendations_retained",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "runs", sa.Column("recommendation_rule_set_version", sa.String(64), nullable=True)
    )
    op.create_table(
        "sitemap_recommendations",
        sa.Column("recommendation_id", sa.String(64), primary_key=True),
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
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("evaluated_url", sa.Text(), nullable=False),
        sa.Column("evaluated_url_search", sa.Text(), nullable=False),
        sa.Column("requested_url", sa.Text(), nullable=False),
        sa.Column("final_url", sa.Text()),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("determinacy", sa.String(32), nullable=False),
        sa.Column("primary_reason", sa.String(64), nullable=False),
        sa.Column("reason_codes_json", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("http_status", sa.Integer()),
        sa.Column("content_type", sa.String(256)),
        sa.Column("fetch_failure_code", sa.String(128)),
        sa.Column("canonical_url", sa.Text()),
        sa.Column("canonical_conflicting", sa.Boolean(), nullable=False),
        sa.Column("redirect_source", sa.Boolean(), nullable=False),
        sa.Column("redirect_hops", sa.Integer(), nullable=False),
        sa.Column("redirect_final_url", sa.Text()),
        sa.Column("robots_available", sa.Boolean(), nullable=False),
        sa.Column("robots_allowed", sa.Boolean()),
        sa.Column("robots_reason_code", sa.String(128)),
        sa.Column("generic_directives_json", sa.Text(), nullable=False),
        sa.Column("crawler_specific_directives_json", sa.Text(), nullable=False),
        sa.Column("indexability_conflict", sa.Boolean(), nullable=False),
        sa.Column("configured_exclusions_json", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("warning_details_json", sa.Text(), nullable=False),
        sa.UniqueConstraint("job_id", "sequence", name="uq_sitemap_recommendation_job_sequence"),
    )
    op.create_index(
        "ix_sitemap_recommendation_job_state",
        "sitemap_recommendations",
        ["job_id", "state", "sequence"],
    )
    op.create_index(
        "ix_sitemap_recommendation_job_reason",
        "sitemap_recommendations",
        ["job_id", "primary_reason", "sequence"],
    )
    op.create_index(
        "ix_sitemap_recommendation_run",
        "sitemap_recommendations",
        ["run_id", "sequence"],
    )


def downgrade() -> None:
    op.drop_table("sitemap_recommendations")
    op.drop_column("runs", "recommendation_rule_set_version")
    op.drop_column("runs", "recommendations_retained")
