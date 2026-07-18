"""SQLAlchemy models for retained structured-data evidence and audits."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003

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


class CrawlStructuredDataEvidenceModel(Base):
    __tablename__ = "crawl_structured_data_evidence"
    block_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.job_id", ondelete="CASCADE"))
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id", ondelete="CASCADE"))
    source_evidence_id: Mapped[str] = mapped_column(
        ForeignKey("crawl_page_evidence.evidence_id", ondelete="CASCADE")
    )
    source_requested_url: Mapped[str] = mapped_column(Text)
    source_final_url: Mapped[str | None] = mapped_column(Text)
    source_url_identity: Mapped[str] = mapped_column(String(64))
    source_discovery_sequence: Mapped[int] = mapped_column(Integer)
    source_crawl_depth: Mapped[int] = mapped_column(Integer)
    element_sequence: Mapped[int] = mapped_column(Integer)
    occurrence_sequence: Mapped[int] = mapped_column(Integer)
    format: Mapped[str] = mapped_column(String(32))
    source_locator: Mapped[str] = mapped_column(String(512))
    script_type: Mapped[str | None] = mapped_column(String(128))
    raw_value: Mapped[str] = mapped_column(Text)
    raw_length: Mapped[int] = mapped_column(Integer)
    parse_status: Mapped[str] = mapped_column(String(32))
    parse_error: Mapped[str | None] = mapped_column(String(512))
    contexts_json: Mapped[str] = mapped_column(Text)
    types_json: Mapped[str] = mapped_column(Text)
    identifiers_json: Mapped[str] = mapped_column(Text)
    properties_json: Mapped[str] = mapped_column(Text)
    references_json: Mapped[str] = mapped_column(Text)
    raw_fingerprint: Mapped[str] = mapped_column(String(64))
    normalized_fingerprint: Mapped[str | None] = mapped_column(String(64))
    duplicate_keys_json: Mapped[str] = mapped_column(Text)
    diagnostics_json: Mapped[str] = mapped_column(Text)
    value_truncated: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    evidence_version: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint(
            "source_evidence_id", "element_sequence", name="uq_structured_evidence_source_sequence"
        ),
        UniqueConstraint(
            "run_id", "occurrence_sequence", name="uq_structured_evidence_run_sequence"
        ),
        Index("ix_structured_evidence_run", "run_id", "occurrence_sequence"),
    )


class StructuredDataAuditModel(Base):
    __tablename__ = "structured_data_audits"
    audit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id", ondelete="CASCADE"))
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.job_id", ondelete="CASCADE"))
    configuration_json: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(64))
    total_pages: Mapped[int] = mapped_column(Integer, default=0)
    total_blocks: Mapped[int] = mapped_column(Integer, default=0)
    total_entities: Mapped[int] = mapped_column(Integer, default=0)
    total_findings: Mapped[int] = mapped_column(Integer, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retention_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(128))
    __table_args__ = (
        UniqueConstraint("run_id", "configuration_json", name="uq_structured_audit_run_config"),
    )


class _AuditChild:
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audit_id: Mapped[str] = mapped_column(
        ForeignKey("structured_data_audits.audit_id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StructuredDataBlockModel(_AuditChild, Base):
    __tablename__ = "structured_data_blocks"
    page_url: Mapped[str] = mapped_column(Text)
    format: Mapped[str] = mapped_column(String(32))
    parse_status: Mapped[str] = mapped_column(String(32))
    types_json: Mapped[str] = mapped_column(Text)
    identifiers_json: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(64))
    evidence_json: Mapped[str] = mapped_column(Text)


class StructuredDataEntityModel(_AuditChild, Base):
    __tablename__ = "structured_data_entities"
    block_id: Mapped[str] = mapped_column(String(64), index=True)
    page_url: Mapped[str] = mapped_column(Text)
    entity_identifier: Mapped[str | None] = mapped_column(Text)
    entity_type: Mapped[str | None] = mapped_column(String(256))
    properties_json: Mapped[str] = mapped_column(Text)


class StructuredDataPropertyModel(_AuditChild, Base):
    __tablename__ = "structured_data_properties"
    entity_id: Mapped[str] = mapped_column(String(64), index=True)
    page_url: Mapped[str] = mapped_column(Text)
    property_name: Mapped[str] = mapped_column(String(512))
    value_json: Mapped[str] = mapped_column(Text)
    value_state: Mapped[str] = mapped_column(String(32))


class StructuredDataReferenceModel(_AuditChild, Base):
    __tablename__ = "structured_data_references"
    page_url: Mapped[str] = mapped_column(Text)
    source_entity_id: Mapped[str | None] = mapped_column(String(64))
    target_identifier: Mapped[str] = mapped_column(Text)
    resolved: Mapped[bool] = mapped_column(Boolean)


class StructuredDataDuplicateGroupModel(_AuditChild, Base):
    __tablename__ = "structured_data_duplicate_groups"
    fingerprint: Mapped[str] = mapped_column(String(64))
    raw_fingerprint: Mapped[str | None] = mapped_column(String(64))
    normalized_fingerprint: Mapped[str | None] = mapped_column(String(64))
    comparison_basis: Mapped[str] = mapped_column(String(32))
    member_count: Mapped[int] = mapped_column(Integer)
    pages_json: Mapped[str] = mapped_column(Text)
    classification: Mapped[str] = mapped_column(String(64))


class StructuredDataPageSummaryModel(_AuditChild, Base):
    __tablename__ = "structured_data_page_summaries"
    page_url: Mapped[str] = mapped_column(Text)
    block_count: Mapped[int] = mapped_column(Integer)
    entity_count: Mapped[int] = mapped_column(Integer)
    finding_count: Mapped[int] = mapped_column(Integer)
    formats_json: Mapped[str] = mapped_column(Text)


class StructuredDataFindingModel(_AuditChild, Base):
    __tablename__ = "structured_data_findings"
    page_url: Mapped[str | None] = mapped_column(Text)
    block_id: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    code: Mapped[str] = mapped_column(String(128), index=True)
    severity: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[str] = mapped_column(String(32))
    requires_human_review: Mapped[bool] = mapped_column(Boolean)
    category: Mapped[str] = mapped_column(String(64), index=True)
    explanation: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint(
            "confidence IN ('high','medium','low','indeterminate')",
            name="ck_structured_finding_confidence",
        ),
    )


class StructuredDataProfileModel(_AuditChild, Base):
    __tablename__ = "structured_data_profiles"
    entity_id: Mapped[str] = mapped_column(String(64), index=True)
    profile_name: Mapped[str] = mapped_column(String(128))
    profile_version: Mapped[str] = mapped_column(String(64))
    property_name: Mapped[str] = mapped_column(String(512))
    observation_state: Mapped[str] = mapped_column(String(32))
    explanation: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint(
            "observation_state IN "
            "('present','missing','empty','invalid','conflicting','not_applicable','indeterminate')",
            name="ck_structured_profile_state",
        ),
    )


class StructuredDataRecommendationModel(_AuditChild, Base):
    __tablename__ = "structured_data_recommendations"
    action: Mapped[str] = mapped_column(String(128), index=True)
    priority: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[str] = mapped_column(String(32))
    requires_human_review: Mapped[bool] = mapped_column(Boolean)
    scope: Mapped[str] = mapped_column(String(32))
    occurrence_count: Mapped[int] = mapped_column(Integer)
    affected_page_count: Mapped[int] = mapped_column(Integer)
    supporting_finding_ids_json: Mapped[str] = mapped_column(Text)
    supporting_evidence_json: Mapped[str] = mapped_column(Text)
    page_url: Mapped[str | None] = mapped_column(Text)
    finding_code: Mapped[str | None] = mapped_column(String(128))
    explanation: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint(
            "confidence IN ('high','medium','low','indeterminate')",
            name="ck_structured_recommendation_confidence",
        ),
        CheckConstraint("occurrence_count >= 1", name="ck_structured_recommendation_occurrences"),
        CheckConstraint(
            "affected_page_count >= 0", name="ck_structured_recommendation_affected_pages"
        ),
    )


class StructuredDataExportModel(_AuditChild, Base):
    __tablename__ = "structured_data_exports"
    export_format: Mapped[str] = mapped_column(String(64))
    media_type: Mapped[str] = mapped_column(String(128))
    filename: Mapped[str] = mapped_column(String(512))
    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_records.artifact_id", ondelete="CASCADE"), index=True
    )
    row_count: Mapped[int] = mapped_column(Integer)
    truncated: Mapped[bool] = mapped_column(Boolean)
    state: Mapped[str] = mapped_column(String(32))
    __table_args__ = (
        UniqueConstraint("audit_id", "export_format", name="uq_structured_audit_export"),
    )


class StructuredDataEventModel(Base):
    __tablename__ = "structured_data_events"
    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    audit_id: Mapped[str] = mapped_column(
        ForeignKey("structured_data_audits.audit_id", ondelete="CASCADE"), index=True
    )
    state: Mapped[str] = mapped_column(String(64))
    affected_count: Mapped[int] = mapped_column(Integer)
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
