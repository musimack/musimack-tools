"""Add the isolated Blog Strategy BS-01 persistence foundation.

Revision ID: 0011_blog_strategy
Revises: 0010_internal_link_analysis
"""

# ruff: noqa: TC003 - Alembic revision annotations are runtime metadata.

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011_blog_strategy"
down_revision: str | None = "0010_internal_link_analysis"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "blog_strategy_projects",
        sa.Column("project_id", sa.String(40), primary_key=True),
        sa.Column("client_name", sa.String(200), nullable=False),
        sa.Column("primary_website", sa.Text(), nullable=False),
        sa.Column("normalized_origin", sa.Text(), nullable=False),
        sa.Column("primary_market", sa.String(200), nullable=False),
        sa.Column("service_area_notes", sa.Text(), nullable=False),
        sa.Column("core_services_json", sa.Text(), nullable=False),
        sa.Column("important_pages_json", sa.Text(), nullable=False),
        sa.Column("compliance_notes", sa.Text(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "blog_strategy_topic_families",
        sa.Column("family_id", sa.String(40), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(40),
            sa.ForeignKey("blog_strategy_projects.project_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("primary_guide_page_id", sa.String(40)),
        sa.Column("supported_page", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("merged_into_family_id", sa.String(40)),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "name"),
    )
    op.create_index(
        "ix_blog_strategy_families_project", "blog_strategy_topic_families", ["project_id"]
    )
    op.create_table(
        "blog_strategy_pages",
        sa.Column("page_id", sa.String(40), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(40),
            sa.ForeignKey("blog_strategy_projects.project_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("original_url", sa.Text(), nullable=False),
        sa.Column("normalized_url", sa.Text(), nullable=False),
        sa.Column("canonical_url", sa.Text()),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("source_reference", sa.String(128)),
        sa.Column("provenance_json", sa.Text(), nullable=False),
        sa.Column("inclusion_state", sa.String(20), nullable=False),
        sa.Column("title", sa.Text()),
        sa.Column("meta_description", sa.Text()),
        sa.Column("h1", sa.Text()),
        sa.Column("publication_date", sa.DateTime(timezone=True)),
        sa.Column("modified_date", sa.DateTime(timezone=True)),
        sa.Column("author", sa.String(200)),
        sa.Column("http_status", sa.Integer()),
        sa.Column("indexability", sa.String(40)),
        sa.Column("word_count", sa.Integer()),
        sa.Column("primary_topic", sa.String(300), nullable=False),
        sa.Column("secondary_topics_json", sa.Text(), nullable=False),
        sa.Column("search_intent", sa.String(40), nullable=False),
        sa.Column("audience_question", sa.Text(), nullable=False),
        sa.Column("content_role", sa.String(40), nullable=False),
        sa.Column("funnel_stage", sa.String(40), nullable=False),
        sa.Column("geographic_intent", sa.String(200), nullable=False),
        sa.Column("supported_page", sa.Text(), nullable=False),
        sa.Column("supported_area", sa.String(300), nullable=False),
        sa.Column("time_sensitivity", sa.String(30), nullable=False),
        sa.Column("claim_risk", sa.String(40), nullable=False),
        sa.Column("classification_source", sa.String(20), nullable=False),
        sa.Column("human_reviewed", sa.Boolean(), nullable=False),
        sa.Column(
            "family_id",
            sa.String(40),
            sa.ForeignKey("blog_strategy_topic_families.family_id", ondelete="SET NULL"),
        ),
        sa.Column("membership_role", sa.String(20), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("priority", sa.String(30), nullable=False),
        sa.Column("destination_page", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False),
        sa.Column("approved_by", sa.String(128)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "normalized_url"),
    )
    op.create_index("ix_blog_strategy_pages_project", "blog_strategy_pages", ["project_id"])
    op.create_table(
        "blog_strategy_overlap_notes",
        sa.Column("overlap_id", sa.String(40), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(40),
            sa.ForeignKey("blog_strategy_projects.project_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_ids_json", sa.Text(), nullable=False),
        sa.Column("concern_type", sa.String(40), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("preferred_page_id", sa.String(40)),
        sa.Column("review_state", sa.String(20), nullable=False),
        sa.Column("resolution_notes", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_blog_strategy_overlaps_project", "blog_strategy_overlap_notes", ["project_id"]
    )
    op.create_table(
        "blog_strategy_events",
        sa.Column("event_id", sa.String(40), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(40),
            sa.ForeignKey("blog_strategy_projects.project_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("entity_id", sa.String(40)),
        sa.Column("actor", sa.String(128)),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_blog_strategy_events_project", "blog_strategy_events", ["project_id", "occurred_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_blog_strategy_events_project", table_name="blog_strategy_events")
    op.drop_table("blog_strategy_events")
    op.drop_index("ix_blog_strategy_overlaps_project", table_name="blog_strategy_overlap_notes")
    op.drop_table("blog_strategy_overlap_notes")
    op.drop_index("ix_blog_strategy_pages_project", table_name="blog_strategy_pages")
    op.drop_table("blog_strategy_pages")
    op.drop_index("ix_blog_strategy_families_project", table_name="blog_strategy_topic_families")
    op.drop_table("blog_strategy_topic_families")
    op.drop_table("blog_strategy_projects")
