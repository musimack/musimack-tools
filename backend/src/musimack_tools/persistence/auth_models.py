"""SQLAlchemy models for internal users, sessions, and authentication evidence."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from musimack_tools.persistence.base import Base


class UserModel(Base):
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    normalized_email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    credential_state: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    password_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_successful_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failed_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lockout_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    session_revocation_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        CheckConstraint("state IN ('active','inactive','disabled')", name="ck_users_state"),
        CheckConstraint("role IN ('administrator','operator','viewer')", name="ck_users_role"),
        CheckConstraint("failed_login_count >= 0", name="ck_users_failed_login_count"),
        CheckConstraint(
            "session_revocation_generation >= 0", name="ck_users_revocation_generation"
        ),
        Index("ix_users_state", "state", "user_id"),
        Index("ix_users_role", "role", "user_id"),
    )


class UserCredentialModel(Base):
    __tablename__ = "user_credentials"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True
    )
    password_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    password_salt: Mapped[str] = mapped_column(String(32), nullable=False)
    password_algorithm: Mapped[str] = mapped_column(String(32), nullable=False)
    password_iterations: Mapped[int] = mapped_column(Integer, nullable=False)
    password_version: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (
        CheckConstraint("length(password_hash) = 64", name="ck_credentials_hash_length"),
        CheckConstraint("length(password_salt) = 32", name="ck_credentials_salt_length"),
        CheckConstraint("password_iterations > 0", name="ck_credentials_iterations"),
    )


class AuthenticationSessionModel(Base):
    __tablename__ = "authentication_sessions"

    session_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    token_algorithm: Mapped[str] = mapped_column(String(16), nullable=False)
    token_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rotated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revocation_reason: Mapped[str | None] = mapped_column(String(64))
    user_revocation_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    authentication_method: Mapped[str] = mapped_column(String(32), nullable=False)
    principal_role_at_issue: Mapped[str] = mapped_column(String(32), nullable=False)
    client_label: Mapped[str | None] = mapped_column(String(128))
    session_version: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        CheckConstraint("length(token_hash) = 64", name="ck_sessions_token_hash_length"),
        Index("ix_sessions_user", "user_id", "created_at", "session_id"),
        Index("ix_sessions_expiry", "expires_at", "session_id"),
        Index("ix_sessions_revoked", "revoked_at", "session_id"),
    )


class AuthenticationAuditEventModel(Base):
    __tablename__ = "authentication_audit_events"

    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_principal_type: Mapped[str | None] = mapped_column(String(32))
    actor_user_id: Mapped[str | None] = mapped_column(String(32))
    target_user_id: Mapped[str | None] = mapped_column(String(32))
    session_id: Mapped[str | None] = mapped_column(String(32))
    role: Mapped[str | None] = mapped_column(String(32))
    permission: Mapped[str | None] = mapped_column(String(64))
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64))
    correlation_id: Mapped[str | None] = mapped_column(String(128))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    audit_version: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        Index("ix_auth_audit_occurred", "occurred_at", "sequence"),
        Index("ix_auth_audit_actor", "actor_user_id", "sequence"),
        Index("ix_auth_audit_target", "target_user_id", "sequence"),
        Index("ix_auth_audit_type", "event_type", "sequence"),
    )


class LoginAttemptModel(Base):
    __tablename__ = "login_attempts"

    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    normalized_account: Mapped[str] = mapped_column(String(320), nullable=False)
    client_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    succeeded: Mapped[bool] = mapped_column(Boolean, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_login_attempt_account", "normalized_account", "occurred_at", "sequence"),
        Index("ix_login_attempt_client", "client_key_hash", "occurred_at", "sequence"),
    )
