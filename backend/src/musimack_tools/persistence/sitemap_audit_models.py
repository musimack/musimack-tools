"""Normalized SQLAlchemy models for durable existing-sitemap audits."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - SQLAlchemy resolves annotations at runtime.

from sqlalchemy import (
    Boolean,
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


class SitemapAuditModel(Base):
    __tablename__ = "sitemap_audits"

    audit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.job_id", ondelete="CASCADE"))
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id", ondelete="CASCADE"))
    seed_url: Mapped[str] = mapped_column(Text, nullable=False)
    explicit_sitemap_url: Mapped[str | None] = mapped_column(Text)
    discovery_settings_json: Mapped[str] = mapped_column(Text, nullable=False)
    configuration_json: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(128))
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    document_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unique_url_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    comparison_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    add_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    remove_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unchanged_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retention_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    audit_version: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    comparison_version: Mapped[str] = mapped_column(String(64), nullable=False)
    normalization_version: Mapped[str] = mapped_column(String(64), nullable=False)
    page_evidence_version: Mapped[str] = mapped_column(String(64), nullable=False)
    recommendation_version: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "state in ('accepted','discovering','fetching','parsing','comparing',"
            "'completed','completed_with_warnings','partially_completed','failed','cancelled')",
            name="ck_sitemap_audits_state",
        ),
        CheckConstraint(
            "warning_count >= 0 and document_count >= 0 and unique_url_count >= 0 "
            "and comparison_count >= 0 and add_count >= 0 and remove_count >= 0 "
            "and review_count >= 0 and unchanged_count >= 0",
            name="ck_sitemap_audits_counts",
        ),
        Index("ix_sitemap_audits_run_created", "run_id", "created_at", "audit_id"),
        Index("ix_sitemap_audits_state_created", "state", "created_at", "audit_id"),
    )


class SitemapAuditDocumentModel(Base):
    __tablename__ = "sitemap_audit_documents"

    document_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audit_id: Mapped[str] = mapped_column(ForeignKey("sitemap_audits.audit_id", ondelete="CASCADE"))
    parent_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("sitemap_audit_documents.document_id", ondelete="CASCADE")
    )
    discovery_source: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_url: Mapped[str] = mapped_column(Text, nullable=False)
    final_url: Mapped[str | None] = mapped_column(Text)
    normalized_identity: Mapped[str] = mapped_column(Text, nullable=False)
    provenance_json: Mapped[str] = mapped_column(Text, nullable=False)
    depth: Mapped[int] = mapped_column(Integer, nullable=False)
    discovery_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    fetch_state: Mapped[str] = mapped_column(String(32), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    content_type: Mapped[str | None] = mapped_column(String(256))
    payload_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload_sha256: Mapped[str | None] = mapped_column(String(64))
    redirect_json: Mapped[str] = mapped_column(Text, nullable=False)
    root_type: Mapped[str | None] = mapped_column(String(32))
    entry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    child_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parse_state: Mapped[str] = mapped_column(String(32), nullable=False)
    validation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("audit_id", "normalized_identity", name="uq_sitemap_document_identity"),
        CheckConstraint("depth >= 0 and discovery_sequence >= 0", name="ck_sitemap_document_order"),
        CheckConstraint(
            "payload_size >= 0 and entry_count >= 0 and child_count >= 0 and validation_count >= 0",
            name="ck_sitemap_document_counts",
        ),
        Index("ix_sitemap_documents_audit_order", "audit_id", "discovery_sequence", "document_id"),
        Index("ix_sitemap_documents_parent", "parent_document_id", "discovery_sequence"),
        Index("ix_sitemap_documents_parse", "audit_id", "parse_state", "depth"),
    )


class SitemapAuditEntryModel(Base):
    __tablename__ = "sitemap_audit_entries"

    entry_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audit_id: Mapped[str] = mapped_column(ForeignKey("sitemap_audits.audit_id", ondelete="CASCADE"))
    document_id: Mapped[str] = mapped_column(
        ForeignKey("sitemap_audit_documents.document_id", ondelete="CASCADE")
    )
    raw_location: Mapped[str | None] = mapped_column(Text)
    normalized_identity: Mapped[str | None] = mapped_column(Text)
    entry_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    in_scope: Mapped[bool | None] = mapped_column(Boolean)
    validation_state: Mapped[str] = mapped_column(String(32), nullable=False)
    duplicate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    duplicate_identity: Mapped[str | None] = mapped_column(Text)
    is_child_reference: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("document_id", "entry_sequence", name="uq_sitemap_entry_sequence"),
        CheckConstraint("entry_sequence >= 0", name="ck_sitemap_entry_sequence"),
        Index("ix_sitemap_entries_audit_identity", "audit_id", "normalized_identity"),
        Index("ix_sitemap_entries_document_order", "document_id", "entry_sequence", "entry_id"),
        Index("ix_sitemap_entries_validation", "audit_id", "validation_state", "duplicate"),
    )


class SitemapAuditFindingModel(Base):
    __tablename__ = "sitemap_audit_findings"

    finding_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audit_id: Mapped[str] = mapped_column(ForeignKey("sitemap_audits.audit_id", ondelete="CASCADE"))
    document_id: Mapped[str | None] = mapped_column(
        ForeignKey("sitemap_audit_documents.document_id", ondelete="CASCADE")
    )
    entry_id: Mapped[str | None] = mapped_column(
        ForeignKey("sitemap_audit_entries.entry_id", ondelete="CASCADE")
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    safe_message: Mapped[str] = mapped_column(String(512), nullable=False)
    raw_url: Mapped[str | None] = mapped_column(Text)
    normalized_identity: Mapped[str | None] = mapped_column(Text)
    context_json: Mapped[str] = mapped_column(Text, nullable=False)
    finding_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("audit_id", "finding_sequence", name="uq_sitemap_finding_sequence"),
        CheckConstraint("finding_sequence >= 0", name="ck_sitemap_finding_sequence"),
        Index("ix_sitemap_findings_audit_order", "audit_id", "finding_sequence", "finding_id"),
        Index("ix_sitemap_findings_filter", "audit_id", "severity", "code"),
        Index("ix_sitemap_findings_document", "document_id", "finding_sequence"),
    )


class SitemapAuditComparisonModel(Base):
    __tablename__ = "sitemap_audit_comparisons"

    comparison_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audit_id: Mapped[str] = mapped_column(ForeignKey("sitemap_audits.audit_id", ondelete="CASCADE"))
    normalized_identity: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    in_sitemap: Mapped[bool] = mapped_column(Boolean, nullable=False)
    representative_entry_id: Mapped[str | None] = mapped_column(
        ForeignKey("sitemap_audit_entries.entry_id", ondelete="SET NULL")
    )
    evidence_id: Mapped[str | None] = mapped_column(
        ForeignKey("crawl_page_evidence.evidence_id", ondelete="SET NULL")
    )
    recommendation_state: Mapped[str | None] = mapped_column(String(32))
    comparison_state: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    redirect_target: Mapped[str | None] = mapped_column(Text)
    canonical_target: Mapped[str | None] = mapped_column(Text)
    indexability_state: Mapped[str | None] = mapped_column(String(32))
    content_type: Mapped[str | None] = mapped_column(String(256))
    crawl_evidence_state: Mapped[str | None] = mapped_column(String(32))
    record_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    comparison_version: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("audit_id", "normalized_identity", name="uq_sitemap_comparison_identity"),
        UniqueConstraint("audit_id", "record_sequence", name="uq_sitemap_comparison_sequence"),
        CheckConstraint(
            "action in ('add','remove','review','unchanged')", name="ck_sitemap_comparison_action"
        ),
        CheckConstraint("record_sequence >= 0", name="ck_sitemap_comparison_sequence"),
        Index("ix_sitemap_comparison_order", "audit_id", "action", "record_sequence"),
        Index("ix_sitemap_comparison_state", "audit_id", "comparison_state", "reason_code"),
        Index("ix_sitemap_comparison_entry", "representative_entry_id", "record_sequence"),
    )


class SitemapAuditExportModel(Base):
    __tablename__ = "sitemap_audit_exports"

    export_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audit_id: Mapped[str] = mapped_column(ForeignKey("sitemap_audits.audit_id", ondelete="CASCADE"))
    export_format: Mapped[str] = mapped_column(String(16), nullable=False)
    artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifact_records.artifact_id", ondelete="SET NULL")
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    export_version: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("audit_id", "export_format", name="uq_sitemap_audit_export_format"),
        CheckConstraint("row_count >= 0", name="ck_sitemap_audit_export_rows"),
        Index("ix_sitemap_audit_exports_audit", "audit_id", "created_at"),
        Index("ix_sitemap_audit_exports_artifact", "artifact_id"),
    )


class SitemapAuditEventModel(Base):
    __tablename__ = "sitemap_audit_events"

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    audit_id: Mapped[str] = mapped_column(ForeignKey("sitemap_audits.audit_id", ondelete="CASCADE"))
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    safe_code: Mapped[str | None] = mapped_column(String(128))
    counts_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("audit_id", "sequence", name="uq_sitemap_audit_event_sequence"),
        Index("ix_sitemap_audit_events_audit_sequence", "audit_id", "sequence"),
    )
