"""Durable CSA-02 global-setting and site-profile version records."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from musimack_tools.persistence.base import Base


class SiteAuditGlobalSettingsVersionModel(Base):
    __tablename__ = "site_audit_global_settings_versions"

    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    configuration_json: Mapped[str] = mapped_column(Text, nullable=False)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    settings_version: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        CheckConstraint("version > 0", name="ck_site_audit_global_version_positive"),
        CheckConstraint("length(configuration_hash) = 64", name="ck_site_audit_global_hash_length"),
        Index("ix_site_audit_global_created", "created_at", "version"),
        Index("ix_site_audit_global_hash", "configuration_hash", "version"),
    )


class SiteAuditProfileModel(Base):
    __tablename__ = "site_audit_profiles"

    profile_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    site_label: Mapped[str] = mapped_column(String(200), nullable=False)
    authorized_seed: Mapped[str] = mapped_column(Text, nullable=False)
    seed_host: Mapped[str] = mapped_column(String(253), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "state in ('enabled','disabled','archived')", name="ck_site_audit_profile_state"
        ),
        CheckConstraint("current_version > 0", name="ck_site_audit_profile_version_positive"),
        Index("ix_site_audit_profile_state_label", "state", "site_label", "profile_id"),
        Index("ix_site_audit_profile_seed_host", "seed_host", "state", "profile_id"),
    )


class SiteAuditProfileVersionModel(Base):
    __tablename__ = "site_audit_profile_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("site_audit_profiles.profile_id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    configuration_json: Mapped[str] = mapped_column(Text, nullable=False)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    profile_version: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("profile_id", "version", name="uq_site_audit_profile_version"),
        CheckConstraint("version > 0", name="ck_site_audit_profile_revision_positive"),
        CheckConstraint(
            "length(configuration_hash) = 64", name="ck_site_audit_profile_hash_length"
        ),
        Index("ix_site_audit_profile_version", "profile_id", "version"),
        Index("ix_site_audit_profile_hash", "profile_id", "configuration_hash"),
    )
