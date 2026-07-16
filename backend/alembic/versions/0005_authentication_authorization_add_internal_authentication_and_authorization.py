"""add internal authentication and authorization

Revision ID: 0005_authentication_authorization
Revises: 0004_history_api
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0005_authentication_authorization"
down_revision = "0004_history_api"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("user_id", sa.String(32), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("normalized_email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("credential_state", sa.String(32), nullable=False),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True)),
        sa.Column("last_successful_login_at", sa.DateTime(timezone=True)),
        sa.Column("last_failed_login_at", sa.DateTime(timezone=True)),
        sa.Column("failed_login_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("lockout_until", sa.DateTime(timezone=True)),
        sa.Column("session_revocation_generation", sa.Integer, nullable=False, server_default="0"),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.CheckConstraint("state IN ('active','inactive','disabled')", name="ck_users_state"),
        sa.CheckConstraint("role IN ('administrator','operator','viewer')", name="ck_users_role"),
        sa.CheckConstraint("failed_login_count >= 0", name="ck_users_failed_login_count"),
        sa.CheckConstraint(
            "session_revocation_generation >= 0", name="ck_users_revocation_generation"
        ),
        sa.UniqueConstraint("normalized_email", name="uq_users_normalized_email"),
    )
    op.create_index("ix_users_state", "users", ["state", "user_id"])
    op.create_index("ix_users_role", "users", ["role", "user_id"])
    op.create_table(
        "user_credentials",
        sa.Column(
            "user_id",
            sa.String(32),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("password_hash", sa.String(64), nullable=False),
        sa.Column("password_salt", sa.String(32), nullable=False),
        sa.Column("password_algorithm", sa.String(32), nullable=False),
        sa.Column("password_iterations", sa.Integer, nullable=False),
        sa.Column("password_version", sa.String(32), nullable=False),
        sa.CheckConstraint("length(password_hash) = 64", name="ck_credentials_hash_length"),
        sa.CheckConstraint("length(password_salt) = 32", name="ck_credentials_salt_length"),
        sa.CheckConstraint("password_iterations > 0", name="ck_credentials_iterations"),
    )
    op.create_table(
        "authentication_sessions",
        sa.Column("session_id", sa.String(32), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(32),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("token_algorithm", sa.String(16), nullable=False),
        sa.Column("token_version", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revocation_reason", sa.String(64)),
        sa.Column("user_revocation_generation", sa.Integer, nullable=False),
        sa.Column("authentication_method", sa.String(32), nullable=False),
        sa.Column("principal_role_at_issue", sa.String(32), nullable=False),
        sa.Column("client_label", sa.String(128)),
        sa.Column("session_version", sa.String(64), nullable=False),
        sa.CheckConstraint("length(token_hash) = 64", name="ck_sessions_token_hash_length"),
        sa.UniqueConstraint("token_hash", name="uq_authentication_sessions_token_hash"),
    )
    op.create_index(
        "ix_sessions_user", "authentication_sessions", ["user_id", "created_at", "session_id"]
    )
    op.create_index("ix_sessions_expiry", "authentication_sessions", ["expires_at", "session_id"])
    op.create_index("ix_sessions_revoked", "authentication_sessions", ["revoked_at", "session_id"])
    op.create_table(
        "authentication_audit_events",
        sa.Column("sequence", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(32), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("actor_principal_type", sa.String(32)),
        sa.Column("actor_user_id", sa.String(32)),
        sa.Column("target_user_id", sa.String(32)),
        sa.Column("session_id", sa.String(32)),
        sa.Column("role", sa.String(32)),
        sa.Column("permission", sa.String(64)),
        sa.Column("success", sa.Boolean, nullable=False),
        sa.Column("reason_code", sa.String(64)),
        sa.Column("correlation_id", sa.String(128)),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("audit_version", sa.String(64), nullable=False),
        sa.UniqueConstraint("event_id", name="uq_auth_audit_event_id"),
    )
    op.create_index(
        "ix_auth_audit_occurred", "authentication_audit_events", ["occurred_at", "sequence"]
    )
    op.create_index(
        "ix_auth_audit_actor", "authentication_audit_events", ["actor_user_id", "sequence"]
    )
    op.create_index(
        "ix_auth_audit_target", "authentication_audit_events", ["target_user_id", "sequence"]
    )
    op.create_index("ix_auth_audit_type", "authentication_audit_events", ["event_type", "sequence"])
    op.create_table(
        "login_attempts",
        sa.Column("sequence", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("normalized_account", sa.String(320), nullable=False),
        sa.Column("client_key_hash", sa.String(64), nullable=False),
        sa.Column("succeeded", sa.Boolean, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_login_attempt_account",
        "login_attempts",
        ["normalized_account", "occurred_at", "sequence"],
    )
    op.create_index(
        "ix_login_attempt_client", "login_attempts", ["client_key_hash", "occurred_at", "sequence"]
    )


def downgrade() -> None:
    op.drop_table("login_attempts")
    op.drop_table("authentication_audit_events")
    op.drop_table("authentication_sessions")
    op.drop_table("user_credentials")
    op.drop_table("users")
