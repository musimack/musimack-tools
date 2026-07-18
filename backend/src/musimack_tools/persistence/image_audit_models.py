"""SQLAlchemy models for durable image evidence and private image audits."""

# ruff: noqa: E501

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


class CrawlImageEvidenceModel(Base):
    __tablename__ = "crawl_image_evidence"
    image_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.job_id", ondelete="CASCADE"))
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id", ondelete="CASCADE"))
    source_evidence_id: Mapped[str] = mapped_column(
        ForeignKey("crawl_page_evidence.evidence_id", ondelete="CASCADE")
    )
    source_requested_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_final_url: Mapped[str | None] = mapped_column(Text)
    source_url_identity: Mapped[str] = mapped_column(String(64), nullable=False)
    source_discovery_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    source_crawl_depth: Mapped[int] = mapped_column(Integer, nullable=False)
    element_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    occurrence_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    element_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_src: Mapped[str | None] = mapped_column(Text)
    resolved_src: Mapped[str | None] = mapped_column(Text)
    image_identity: Mapped[str | None] = mapped_column(String(64))
    raw_srcset: Mapped[str | None] = mapped_column(Text)
    srcset_candidates_json: Mapped[str] = mapped_column(Text, nullable=False)
    primary_candidate: Mapped[str | None] = mapped_column(Text)
    sizes: Mapped[str | None] = mapped_column(Text)
    alt_present: Mapped[bool] = mapped_column(Boolean, nullable=False)
    alt_raw: Mapped[str | None] = mapped_column(Text)
    alt_normalized: Mapped[str | None] = mapped_column(Text)
    title_value: Mapped[str | None] = mapped_column(Text)
    width_value: Mapped[str | None] = mapped_column(String(64))
    height_value: Mapped[str | None] = mapped_column(String(64))
    loading_value: Mapped[str | None] = mapped_column(String(32))
    decoding_value: Mapped[str | None] = mapped_column(String(32))
    fetch_priority: Mapped[str | None] = mapped_column(String(32))
    linked: Mapped[bool] = mapped_column(Boolean, nullable=False)
    parent_link_url: Mapped[str | None] = mapped_column(Text)
    decorative_explicit: Mapped[bool] = mapped_column(Boolean, nullable=False)
    role_value: Mapped[str | None] = mapped_column(String(64))
    aria_hidden_value: Mapped[str | None] = mapped_column(String(16))
    in_scope: Mapped[bool | None] = mapped_column(Boolean)
    scope_reason_code: Mapped[str | None] = mapped_column(String(64))
    source_scheme: Mapped[str | None] = mapped_column(String(32))
    data_media_type: Mapped[str | None] = mapped_column(String(128))
    data_byte_length_estimate: Mapped[int | None] = mapped_column(Integer)
    data_fingerprint: Mapped[str | None] = mapped_column(String(24))
    unsupported_scheme: Mapped[bool] = mapped_column(Boolean, nullable=False)
    parse_warning: Mapped[str | None] = mapped_column(String(64))
    value_truncated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_version: Mapped[str] = mapped_column(String(64), nullable=False)
    __table_args__ = (
        UniqueConstraint(
            "source_evidence_id", "element_sequence", name="uq_crawl_image_source_sequence"
        ),
        UniqueConstraint("run_id", "occurrence_sequence", name="uq_crawl_image_run_sequence"),
        CheckConstraint(
            "source_discovery_sequence >= 0 and source_crawl_depth >= 0 and element_sequence >= 0 and occurrence_sequence >= 0",
            name="ck_crawl_image_sequences",
        ),
        CheckConstraint(
            "data_byte_length_estimate is null or data_byte_length_estimate >= 0",
            name="ck_crawl_image_data_length",
        ),
        Index("ix_crawl_image_run_order", "run_id", "occurrence_sequence", "image_id"),
        Index("ix_crawl_image_source", "source_evidence_id", "element_sequence"),
        Index("ix_crawl_image_identity", "run_id", "image_identity", "occurrence_sequence"),
        Index("ix_crawl_image_scope", "run_id", "in_scope", "source_scheme"),
    )


class ImageAuditModel(Base):
    __tablename__ = "image_audits"
    audit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.job_id", ondelete="CASCADE"))
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id", ondelete="CASCADE"))
    scope_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    configuration_json: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(128))
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    image_occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unique_image_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_image_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    broken_image_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    redirecting_image_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unverified_image_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    missing_alt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    empty_alt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    generic_alt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    filename_alt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_alt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    missing_dimensions_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    loading_review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recommendation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retention_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    audit_version: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_version: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    __table_args__ = (
        UniqueConstraint("run_id", "configuration_json", name="uq_image_audit_run_configuration"),
        CheckConstraint(
            "state in ('accepted','claiming','building_inventory','resolving_resources','classifying_alt_text','analyzing_reuse','building_recommendations','completed','completed_with_warnings','failed','cancelled')",
            name="ck_image_audit_state",
        ),
        CheckConstraint(
            "warning_count >= 0 and image_occurrence_count >= 0 and unique_image_count >= 0 and valid_image_count >= 0 and broken_image_count >= 0 and redirecting_image_count >= 0 and unverified_image_count >= 0 and missing_alt_count >= 0 and empty_alt_count >= 0 and generic_alt_count >= 0 and filename_alt_count >= 0 and duplicate_alt_count >= 0 and missing_dimensions_count >= 0 and loading_review_count >= 0 and recommendation_count >= 0",
            name="ck_image_audit_counts",
        ),
        Index("ix_image_audit_run", "run_id", "created_at", "audit_id"),
        Index("ix_image_audit_state", "state", "created_at", "audit_id"),
    )


class ImageAuditResourceModel(Base):
    __tablename__ = "image_audit_resources"
    resource_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audit_id: Mapped[str] = mapped_column(ForeignKey("image_audits.audit_id", ondelete="CASCADE"))
    image_identity: Mapped[str] = mapped_column(String(64), nullable=False)
    representative_url: Mapped[str | None] = mapped_column(Text)
    scope_state: Mapped[str] = mapped_column(String(32), nullable=False)
    fetch_state: Mapped[str] = mapped_column(String(32), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    status_class: Mapped[int | None] = mapped_column(Integer)
    content_type: Mapped[str | None] = mapped_column(String(256))
    redirect_state: Mapped[str] = mapped_column(String(32), nullable=False)
    final_image_url: Mapped[str | None] = mapped_column(Text)
    response_byte_count: Mapped[int | None] = mapped_column(Integer)
    resource_state: Mapped[str] = mapped_column(String(40), nullable=False)
    unique_source_page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    unique_alt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    missing_alt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    empty_alt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    linked_occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    broken_occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    redirecting_occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    width_consistent: Mapped[bool] = mapped_column(Boolean, nullable=False)
    height_consistent: Mapped[bool] = mapped_column(Boolean, nullable=False)
    loading_distribution_json: Mapped[str] = mapped_column(Text, nullable=False)
    earliest_discovery_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_source_depth: Mapped[int] = mapped_column(Integer, nullable=False)
    maximum_source_depth: Mapped[int] = mapped_column(Integer, nullable=False)
    sitewide_state: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    resource_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (
        UniqueConstraint("audit_id", "image_identity", name="uq_image_resource_identity"),
        UniqueConstraint("audit_id", "resource_sequence", name="uq_image_resource_sequence"),
        CheckConstraint(
            "unique_source_page_count >= 0 and total_occurrence_count > 0 and unique_alt_count >= 0 and missing_alt_count >= 0 and empty_alt_count >= 0 and linked_occurrence_count >= 0 and broken_occurrence_count >= 0 and redirecting_occurrence_count >= 0 and earliest_discovery_sequence >= 0 and minimum_source_depth >= 0 and maximum_source_depth >= minimum_source_depth and resource_sequence >= 0",
            name="ck_image_resource_counts",
        ),
        CheckConstraint(
            "http_status is null or (http_status >= 100 and http_status <= 599)",
            name="ck_image_resource_http_status",
        ),
        Index("ix_image_resource_order", "audit_id", "resource_sequence", "resource_id"),
        Index(
            "ix_image_resource_filter", "audit_id", "resource_state", "severity", "sitewide_state"
        ),
    )


class ImageOccurrenceAnalysisModel(Base):
    __tablename__ = "image_occurrence_analyses"
    analysis_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audit_id: Mapped[str] = mapped_column(ForeignKey("image_audits.audit_id", ondelete="CASCADE"))
    image_evidence_id: Mapped[str] = mapped_column(
        ForeignKey("crawl_image_evidence.image_id", ondelete="CASCADE")
    )
    source_evidence_id: Mapped[str] = mapped_column(
        ForeignKey("crawl_page_evidence.evidence_id", ondelete="CASCADE")
    )
    resource_id: Mapped[str] = mapped_column(
        ForeignKey("image_audit_resources.resource_id", ondelete="CASCADE")
    )
    source_page_url: Mapped[str] = mapped_column(Text, nullable=False)
    image_url: Mapped[str | None] = mapped_column(Text)
    raw_src: Mapped[str | None] = mapped_column(Text)
    primary_candidate: Mapped[str | None] = mapped_column(Text)
    element_type: Mapped[str] = mapped_column(String(32), nullable=False)
    alt_raw: Mapped[str | None] = mapped_column(Text)
    alt_normalized: Mapped[str | None] = mapped_column(Text)
    width_value: Mapped[str | None] = mapped_column(String(64))
    height_value: Mapped[str | None] = mapped_column(String(64))
    loading_value: Mapped[str | None] = mapped_column(String(32))
    decoding_value: Mapped[str | None] = mapped_column(String(32))
    fetch_priority: Mapped[str | None] = mapped_column(String(32))
    alt_state: Mapped[str] = mapped_column(String(48), nullable=False)
    dimension_state: Mapped[str] = mapped_column(String(40), nullable=False)
    loading_state: Mapped[str] = mapped_column(String(40), nullable=False)
    linked_image: Mapped[bool] = mapped_column(Boolean, nullable=False)
    decorative: Mapped[bool] = mapped_column(Boolean, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    primary_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    occurrence_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (
        UniqueConstraint("audit_id", "image_evidence_id", name="uq_image_occurrence_evidence"),
        UniqueConstraint("audit_id", "occurrence_sequence", name="uq_image_occurrence_sequence"),
        CheckConstraint("occurrence_sequence >= 0", name="ck_image_occurrence_sequence"),
        Index("ix_image_occurrence_order", "audit_id", "occurrence_sequence", "analysis_id"),
        Index(
            "ix_image_occurrence_filter",
            "audit_id",
            "alt_state",
            "dimension_state",
            "loading_state",
            "severity",
        ),
        Index("ix_image_occurrence_page", "audit_id", "source_evidence_id", "occurrence_sequence"),
    )


class ImageDuplicateGroupModel(Base):
    __tablename__ = "image_duplicate_groups"
    group_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audit_id: Mapped[str] = mapped_column(ForeignKey("image_audits.audit_id", ondelete="CASCADE"))
    group_type: Mapped[str] = mapped_column(String(48), nullable=False)
    group_identity: Mapped[str] = mapped_column(String(64), nullable=False)
    representative_alt: Mapped[str | None] = mapped_column(Text)
    image_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    sample_images_json: Mapped[str] = mapped_column(Text, nullable=False)
    sample_pages_json: Mapped[str] = mapped_column(Text, nullable=False)
    group_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (
        UniqueConstraint(
            "audit_id", "group_type", "group_identity", name="uq_image_duplicate_group"
        ),
        UniqueConstraint("audit_id", "group_sequence", name="uq_image_duplicate_sequence"),
        CheckConstraint(
            "image_count > 0 and source_page_count > 0 and occurrence_count > 0 and group_sequence >= 0",
            name="ck_image_duplicate_counts",
        ),
        Index("ix_image_duplicate_order", "audit_id", "group_sequence", "group_id"),
        Index("ix_image_duplicate_filter", "audit_id", "group_type", "severity"),
    )


class ImagePageSummaryModel(Base):
    __tablename__ = "image_page_summaries"
    page_summary_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audit_id: Mapped[str] = mapped_column(ForeignKey("image_audits.audit_id", ondelete="CASCADE"))
    source_evidence_id: Mapped[str] = mapped_column(
        ForeignKey("crawl_page_evidence.evidence_id", ondelete="CASCADE")
    )
    source_page_url: Mapped[str] = mapped_column(Text, nullable=False)
    image_occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    unique_image_count: Mapped[int] = mapped_column(Integer, nullable=False)
    missing_alt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    empty_alt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    broken_image_count: Mapped[int] = mapped_column(Integer, nullable=False)
    redirecting_image_count: Mapped[int] = mapped_column(Integer, nullable=False)
    missing_dimensions_count: Mapped[int] = mapped_column(Integer, nullable=False)
    loading_review_count: Mapped[int] = mapped_column(Integer, nullable=False)
    generic_alt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    filename_alt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    duplicate_alt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    external_image_count: Mapped[int] = mapped_column(Integer, nullable=False)
    data_image_count: Mapped[int] = mapped_column(Integer, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    page_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (
        UniqueConstraint("audit_id", "source_evidence_id", name="uq_image_page_summary"),
        UniqueConstraint("audit_id", "page_sequence", name="uq_image_page_sequence"),
        CheckConstraint(
            "image_occurrence_count >= 0 and unique_image_count >= 0 and missing_alt_count >= 0 and empty_alt_count >= 0 and broken_image_count >= 0 and redirecting_image_count >= 0 and missing_dimensions_count >= 0 and loading_review_count >= 0 and generic_alt_count >= 0 and filename_alt_count >= 0 and duplicate_alt_count >= 0 and external_image_count >= 0 and data_image_count >= 0 and page_sequence >= 0",
            name="ck_image_page_counts",
        ),
        Index("ix_image_page_order", "audit_id", "page_sequence", "page_summary_id"),
        Index(
            "ix_image_page_filter",
            "audit_id",
            "severity",
            "missing_alt_count",
            "broken_image_count",
        ),
    )


class ImageFindingModel(Base):
    __tablename__ = "image_findings"
    finding_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audit_id: Mapped[str] = mapped_column(ForeignKey("image_audits.audit_id", ondelete="CASCADE"))
    resource_id: Mapped[str | None] = mapped_column(
        ForeignKey("image_audit_resources.resource_id", ondelete="CASCADE")
    )
    analysis_id: Mapped[str | None] = mapped_column(
        ForeignKey("image_occurrence_analyses.analysis_id", ondelete="CASCADE")
    )
    page_summary_id: Mapped[str | None] = mapped_column(
        ForeignKey("image_page_summaries.page_summary_id", ondelete="CASCADE")
    )
    duplicate_group_id: Mapped[str | None] = mapped_column(
        ForeignKey("image_duplicate_groups.group_id", ondelete="CASCADE")
    )
    stable_code: Mapped[str] = mapped_column(String(64), nullable=False)
    finding_type: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    safe_message: Mapped[str] = mapped_column(String(512), nullable=False)
    context_json: Mapped[str] = mapped_column(Text, nullable=False)
    finding_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (
        UniqueConstraint("audit_id", "finding_sequence", name="uq_image_finding_sequence"),
        Index("ix_image_finding_order", "audit_id", "finding_sequence", "finding_id"),
        Index("ix_image_finding_filter", "audit_id", "finding_type", "severity", "stable_code"),
    )


class ImageRecommendationModel(Base):
    __tablename__ = "image_recommendations"
    recommendation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audit_id: Mapped[str] = mapped_column(ForeignKey("image_audits.audit_id", ondelete="CASCADE"))
    analysis_id: Mapped[str | None] = mapped_column(
        ForeignKey("image_occurrence_analyses.analysis_id", ondelete="CASCADE")
    )
    resource_id: Mapped[str | None] = mapped_column(
        ForeignKey("image_audit_resources.resource_id", ondelete="CASCADE")
    )
    source_page_url: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    image_identity: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(48), nullable=False)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    human_review_state: Mapped[str] = mapped_column(String(32), nullable=False)
    supporting_metrics_json: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (
        UniqueConstraint(
            "audit_id", "recommendation_sequence", name="uq_image_recommendation_sequence"
        ),
        Index(
            "ix_image_recommendation_order",
            "audit_id",
            "recommendation_sequence",
            "recommendation_id",
        ),
        Index(
            "ix_image_recommendation_filter",
            "audit_id",
            "action",
            "confidence",
            "severity",
            "human_review_state",
        ),
    )


class ImageAuditExportModel(Base):
    __tablename__ = "image_audit_exports"
    export_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audit_id: Mapped[str] = mapped_column(ForeignKey("image_audits.audit_id", ondelete="CASCADE"))
    export_format: Mapped[str] = mapped_column(String(48), nullable=False)
    artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifact_records.artifact_id", ondelete="SET NULL")
    )
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (UniqueConstraint("audit_id", "export_format", name="uq_image_audit_export"),)


class ImageAuditEventModel(Base):
    __tablename__ = "image_audit_events"
    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    audit_id: Mapped[str] = mapped_column(ForeignKey("image_audits.audit_id", ondelete="CASCADE"))
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    safe_reason_code: Mapped[str | None] = mapped_column(String(128))
    affected_count: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    __table_args__ = (
        CheckConstraint("affected_count >= 0", name="ck_image_audit_event_count"),
        Index("ix_image_audit_event_order", "audit_id", "event_id"),
    )
