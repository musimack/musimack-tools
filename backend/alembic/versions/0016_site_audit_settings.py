"""add Combined Site Audit settings and site profiles

Revision ID: 0016_site_audit_settings
Revises: 0015_sitemap_recommendation_retention
"""

# ruff: noqa: TC003

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0016_site_audit_settings"
down_revision: str | Sequence[str] | None = "0015_sitemap_recommendation_retention"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "site_audit_global_settings_versions",
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("configuration_json", sa.Text(), nullable=False),
        sa.Column("configuration_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settings_version", sa.String(64), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_site_audit_global_version_positive"),
        sa.CheckConstraint(
            "length(configuration_hash) = 64", name="ck_site_audit_global_hash_length"
        ),
    )
    op.create_index(
        "ix_site_audit_global_created",
        "site_audit_global_settings_versions",
        ["created_at", "version"],
    )
    op.create_index(
        "ix_site_audit_global_hash",
        "site_audit_global_settings_versions",
        ["configuration_hash", "version"],
    )
    op.create_table(
        "site_audit_profiles",
        sa.Column("profile_id", sa.String(64), primary_key=True),
        sa.Column("site_label", sa.String(200), nullable=False),
        sa.Column("authorized_seed", sa.Text(), nullable=False),
        sa.Column("seed_host", sa.String(253), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state in ('enabled','disabled','archived')", name="ck_site_audit_profile_state"
        ),
        sa.CheckConstraint("current_version > 0", name="ck_site_audit_profile_version_positive"),
    )
    op.create_index(
        "ix_site_audit_profile_state_label",
        "site_audit_profiles",
        ["state", "site_label", "profile_id"],
    )
    op.create_index(
        "ix_site_audit_profile_seed_host",
        "site_audit_profiles",
        ["seed_host", "state", "profile_id"],
    )
    op.create_table(
        "site_audit_profile_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "profile_id",
            sa.String(64),
            sa.ForeignKey("site_audit_profiles.profile_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("configuration_json", sa.Text(), nullable=False),
        sa.Column("configuration_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("profile_version", sa.String(64), nullable=False),
        sa.UniqueConstraint("profile_id", "version", name="uq_site_audit_profile_version"),
        sa.CheckConstraint("version > 0", name="ck_site_audit_profile_revision_positive"),
        sa.CheckConstraint(
            "length(configuration_hash) = 64", name="ck_site_audit_profile_hash_length"
        ),
    )
    op.create_index(
        "ix_site_audit_profile_version",
        "site_audit_profile_versions",
        ["profile_id", "version"],
    )
    op.create_index(
        "ix_site_audit_profile_hash",
        "site_audit_profile_versions",
        ["profile_id", "configuration_hash"],
    )


def downgrade() -> None:
    op.drop_index("ix_site_audit_profile_version", table_name="site_audit_profile_versions")
    op.drop_table("site_audit_profile_versions")
    op.drop_index("ix_site_audit_profile_seed_host", table_name="site_audit_profiles")
    op.drop_index("ix_site_audit_profile_state_label", table_name="site_audit_profiles")
    op.drop_table("site_audit_profiles")
    op.drop_index("ix_site_audit_global_created", table_name="site_audit_global_settings_versions")
    op.drop_table("site_audit_global_settings_versions")
