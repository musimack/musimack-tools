"""Typed storage representations for bounded durable evidence."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - SQLAlchemy resolves annotations at runtime.

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from musimack_tools.persistence.base import Base


class PersistenceMetadataModel(Base):
    __tablename__ = "persistence_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    persistence_version: Mapped[str] = mapped_column(String(64), nullable=False)
    creation_revision: Mapped[str] = mapped_column(String(32), nullable=False)
    application_compatibility_version: Mapped[str] = mapped_column(String(64), nullable=False)


class ConfigurationSnapshotModel(Base):
    __tablename__ = "configuration_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_type: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_json: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    __table_args__ = (CheckConstraint("length(sha256) = 64", name="ck_snapshot_sha256"),)


class RunModel(Base):
    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    orchestration_version: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_seed_url: Mapped[str] = mapped_column(Text, nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_stages_json: Mapped[str] = mapped_column(Text, nullable=False)
    stage_states_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    result_projection_json: Mapped[str | None] = mapped_column(Text)
    recommendations_retained: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    recommendation_rule_set_version: Mapped[str | None] = mapped_column(String(64))
    crawl_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recommendation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    xml_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    publication_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    final_result_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    summary_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    configuration_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("configuration_snapshots.snapshot_id", ondelete="RESTRICT"), nullable=False
    )

    __table_args__ = (
        Index("ix_runs_lifecycle", "lifecycle"),
        Index("ix_runs_seed", "normalized_seed_url"),
        Index("ix_runs_started", "started_at", "run_id"),
        Index("ix_runs_terminal", "terminal_at", "run_id"),
    )


class JobModel(Base):
    __tablename__ = "jobs"

    job_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    queue_position: Mapped[int | None] = mapped_column(Integer)
    run_lifecycle: Mapped[str | None] = mapped_column(String(32))
    active_stage: Mapped[str | None] = mapped_column(String(32))
    cancellation_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    terminal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    result_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    payload_retention_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    registry_version: Mapped[str] = mapped_column(String(64), nullable=False)
    application_service_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    started_sequence: Mapped[int | None] = mapped_column(Integer)
    terminal_sequence: Mapped[int | None] = mapped_column(Integer)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    eviction_state: Mapped[str] = mapped_column(String(32), nullable=False, default="retained")
    safe_caller_label: Mapped[str | None] = mapped_column(String(128))
    configuration_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("configuration_snapshots.snapshot_id", ondelete="RESTRICT"), nullable=False
    )
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("run_id", "attempt_number", name="uq_jobs_run_attempt"),
        Index("ix_jobs_state_sequence", "state", "created_sequence"),
        Index("ix_jobs_run", "run_id", "created_sequence"),
        Index("ix_jobs_submitted", "submitted_at", "job_id"),
        Index("ix_jobs_terminal_at", "terminal_at", "job_id"),
    )


class RunStageModel(Base):
    __tablename__ = "run_stages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    stable_order: Mapped[int] = mapped_column(Integer, nullable=False)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    safe_code: Mapped[str | None] = mapped_column(String(128))
    started_sequence: Mapped[int | None] = mapped_column(Integer)
    completed_sequence: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("run_id", "stage", name="uq_run_stages_run_stage"),
        Index("ix_run_stages_run_order", "run_id", "stable_order"),
    )


class SitemapRecommendationModel(Base):
    """Bounded restart-safe URL recommendation projection."""

    __tablename__ = "sitemap_recommendations"

    recommendation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    evaluated_url: Mapped[str] = mapped_column(Text, nullable=False)
    evaluated_url_search: Mapped[str] = mapped_column(Text, nullable=False)
    requested_url: Mapped[str] = mapped_column(Text, nullable=False)
    final_url: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    determinacy: Mapped[str] = mapped_column(String(32), nullable=False)
    primary_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_codes_json: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    content_type: Mapped[str | None] = mapped_column(String(256))
    fetch_failure_code: Mapped[str | None] = mapped_column(String(128))
    canonical_url: Mapped[str | None] = mapped_column(Text)
    canonical_conflicting: Mapped[bool] = mapped_column(Boolean, nullable=False)
    redirect_source: Mapped[bool] = mapped_column(Boolean, nullable=False)
    redirect_hops: Mapped[int] = mapped_column(Integer, nullable=False)
    redirect_final_url: Mapped[str | None] = mapped_column(Text)
    robots_available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    robots_allowed: Mapped[bool | None] = mapped_column(Boolean)
    robots_reason_code: Mapped[str | None] = mapped_column(String(128))
    generic_directives_json: Mapped[str] = mapped_column(Text, nullable=False)
    crawler_specific_directives_json: Mapped[str] = mapped_column(Text, nullable=False)
    indexability_conflict: Mapped[bool] = mapped_column(Boolean, nullable=False)
    configured_exclusions_json: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False)
    warning_details_json: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("job_id", "sequence", name="uq_sitemap_recommendation_job_sequence"),
        Index("ix_sitemap_recommendation_job_state", "job_id", "state", "sequence"),
        Index(
            "ix_sitemap_recommendation_job_reason",
            "job_id",
            "primary_reason",
            "sequence",
        ),
        Index("ix_sitemap_recommendation_run", "run_id", "sequence"),
    )


class ProgressSnapshotModel(Base):
    __tablename__ = "progress_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_code: Mapped[str] = mapped_column(String(64), nullable=False)
    active_stage: Mapped[str | None] = mapped_column(String(32))
    crawl_state: Mapped[str | None] = mapped_column(String(32))
    discovered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    queued_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fetched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parsed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    byte_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    queue_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active_fetch_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_depth: Mapped[int | None] = mapped_column(Integer)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cancellation_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    recent_safe_error_code: Mapped[str | None] = mapped_column(String(128))
    elapsed_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    __table_args__ = (
        UniqueConstraint("job_id", "sequence", name="uq_progress_job_sequence"),
        Index("ix_progress_job_sequence", "job_id", "sequence"),
    )


class CrawlPageEvidenceModel(Base):
    """Restart-safe bounded projection of one accepted crawl URL record."""

    __tablename__ = "crawl_page_evidence"

    evidence_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.job_id", ondelete="CASCADE"))
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id", ondelete="CASCADE"))
    requested_url: Mapped[str] = mapped_column(Text, nullable=False)
    requested_url_identity: Mapped[str] = mapped_column(String(64), nullable=False)
    final_url: Mapped[str | None] = mapped_column(Text)
    final_url_identity: Mapped[str | None] = mapped_column(String(64))
    discovery_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    crawl_depth: Mapped[int] = mapped_column(Integer, nullable=False)
    referrer_url: Mapped[str | None] = mapped_column(Text)
    frontier_state: Mapped[str] = mapped_column(String(16), nullable=False)
    fetch_outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    status_class: Mapped[int | None] = mapped_column(Integer)
    fetch_failed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    redirect_count: Mapped[int] = mapped_column(Integer, nullable=False)
    redirect_truncated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    redirect_loop: Mapped[bool] = mapped_column(Boolean, nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(256))
    content_type_category: Mapped[str] = mapped_column(String(16), nullable=False)
    charset: Mapped[str | None] = mapped_column(String(64))
    parsed_as_html: Mapped[bool] = mapped_column(Boolean, nullable=False)
    parse_outcome: Mapped[str | None] = mapped_column(String(16))
    title_presence: Mapped[str] = mapped_column(String(16), nullable=False)
    title_value: Mapped[str | None] = mapped_column(Text)
    title_normalized_hash: Mapped[str | None] = mapped_column(String(64))
    title_count: Mapped[int] = mapped_column(Integer, nullable=False)
    title_length: Mapped[int | None] = mapped_column(Integer)
    title_truncated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    description_presence: Mapped[str] = mapped_column(String(16), nullable=False)
    description_value: Mapped[str | None] = mapped_column(Text)
    description_normalized_hash: Mapped[str | None] = mapped_column(String(64))
    description_count: Mapped[int] = mapped_column(Integer, nullable=False)
    description_length: Mapped[int | None] = mapped_column(Integer)
    description_truncated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    canonical_presence: Mapped[str] = mapped_column(String(16), nullable=False)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    canonical_url_identity: Mapped[str | None] = mapped_column(String(64))
    canonical_count: Mapped[int] = mapped_column(Integer, nullable=False)
    canonical_conflicting: Mapped[bool] = mapped_column(Boolean, nullable=False)
    canonical_cross_host: Mapped[bool] = mapped_column(Boolean, nullable=False)
    canonical_cross_scheme: Mapped[bool] = mapped_column(Boolean, nullable=False)
    canonical_cross_port: Mapped[bool] = mapped_column(Boolean, nullable=False)
    canonical_truncated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    meta_robots_json: Mapped[str] = mapped_column(Text, nullable=False)
    x_robots_json: Mapped[str] = mapped_column(Text, nullable=False)
    robots_allowed: Mapped[bool | None] = mapped_column(Boolean)
    robots_reason_code: Mapped[str | None] = mapped_column(String(64))
    robots_evidence_json: Mapped[str] = mapped_column(Text, nullable=False)
    indexability_evidence_json: Mapped[str] = mapped_column(Text, nullable=False)
    indexability_state: Mapped[str] = mapped_column(String(16), nullable=False)
    parse_warning_count: Mapped[int] = mapped_column(Integer, nullable=False)
    parse_warnings_truncated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    evidence_state: Mapped[str] = mapped_column(String(16), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(64))
    value_truncated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    retention_state: Mapped[str] = mapped_column(String(24), nullable=False)
    retention_hold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    persisted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_version: Mapped[str] = mapped_column(String(64), nullable=False)
    persistence_version: Mapped[str] = mapped_column(String(64), nullable=False)
    projection_version: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "discovery_sequence", name="uq_page_evidence_run_sequence"),
        UniqueConstraint("run_id", "requested_url_identity", name="uq_page_evidence_run_url"),
        CheckConstraint("discovery_sequence >= 0", name="ck_page_evidence_sequence"),
        CheckConstraint("crawl_depth >= 0", name="ck_page_evidence_depth"),
        CheckConstraint("redirect_count >= 0", name="ck_page_evidence_redirect_count"),
        CheckConstraint(
            "http_status IS NULL OR (http_status >= 100 AND http_status <= 599)",
            name="ck_page_evidence_http_status",
        ),
        CheckConstraint(
            "status_class IS NULL OR (status_class >= 1 AND status_class <= 5)",
            name="ck_page_evidence_status_class",
        ),
        CheckConstraint(
            "content_type_category IN "
            "('html','pdf','image','json','plain_text','xml','other','ambiguous','missing')",
            name="ck_page_evidence_content_category",
        ),
        CheckConstraint(
            "title_presence IN ('missing','empty','single','multiple','unavailable')",
            name="ck_page_evidence_title_presence",
        ),
        CheckConstraint(
            "description_presence IN ('missing','empty','single','multiple','unavailable')",
            name="ck_page_evidence_description_presence",
        ),
        CheckConstraint(
            "canonical_presence IN ('missing','empty','single','multiple','unavailable')",
            name="ck_page_evidence_canonical_presence",
        ),
        CheckConstraint(
            "evidence_state IN "
            "('complete','partial','fetch_failed','not_html','cancelled','truncated','unavailable')",
            name="ck_page_evidence_state",
        ),
        CheckConstraint(
            "indexability_state IN ('available','conflicting','unavailable')",
            name="ck_page_evidence_indexability_state",
        ),
        CheckConstraint(
            "retention_state IN "
            "('active','retained','expired','cleanup_pending','deleted','metadata_only')",
            name="ck_page_evidence_retention_state",
        ),
        Index(
            "ix_page_evidence_run_order", "run_id", "discovery_sequence", "requested_url_identity"
        ),
        Index("ix_page_evidence_job_order", "job_id", "discovery_sequence"),
        Index("ix_page_evidence_requested_url", "requested_url_identity"),
        Index("ix_page_evidence_final_url", "final_url_identity"),
        Index("ix_page_evidence_status", "http_status", "discovery_sequence"),
        Index("ix_page_evidence_content_type", "content_type_category", "discovery_sequence"),
        Index("ix_page_evidence_robots", "robots_allowed", "discovery_sequence"),
        Index("ix_page_evidence_indexability", "indexability_state", "discovery_sequence"),
        Index("ix_page_evidence_state", "evidence_state", "discovery_sequence"),
        Index("ix_page_evidence_depth", "crawl_depth", "discovery_sequence"),
        Index("ix_page_evidence_expiry", "retention_state", "expires_at"),
    )


class CrawlPageRedirectHopModel(Base):
    __tablename__ = "crawl_page_redirect_hops"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("crawl_page_evidence.evidence_id", ondelete="CASCADE")
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    target_url: Mapped[str | None] = mapped_column(Text)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    cross_host: Mapped[bool] = mapped_column(Boolean, nullable=False)
    terminal: Mapped[bool] = mapped_column(Boolean, nullable=False)
    loop: Mapped[bool] = mapped_column(Boolean, nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        UniqueConstraint("evidence_id", "sequence", name="uq_page_redirect_evidence_sequence"),
        CheckConstraint("sequence > 0", name="ck_page_redirect_sequence"),
        Index("ix_page_redirect_evidence", "evidence_id", "sequence"),
    )


class CrawlPageParseWarningModel(Base):
    __tablename__ = "crawl_page_parse_warnings"

    warning_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("crawl_page_evidence.evidence_id", ondelete="CASCADE")
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    stable_code: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    safe_summary: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    warning_version: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("evidence_id", "sequence", name="uq_page_warning_evidence_sequence"),
        Index("ix_page_warning_evidence", "evidence_id", "sequence"),
        Index("ix_page_warning_code", "stable_code", "warning_id"),
    )


class CrawlPageEvidenceSummaryModel(Base):
    __tablename__ = "crawl_page_evidence_summaries"

    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"), primary_key=True
    )
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False
    )
    total_records: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_records: Mapped[int] = mapped_column(Integer, nullable=False)
    partial_records: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_records: Mapped[int] = mapped_column(Integer, nullable=False)
    html_records: Mapped[int] = mapped_column(Integer, nullable=False)
    non_html_records: Mapped[int] = mapped_column(Integer, nullable=False)
    redirect_records: Mapped[int] = mapped_column(Integer, nullable=False)
    parse_warning_count: Mapped[int] = mapped_column(Integer, nullable=False)
    truncated_records: Mapped[int] = mapped_column(Integer, nullable=False)
    title_evidence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    description_evidence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    canonical_evidence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status_class_counts_json: Mapped[str] = mapped_column(Text, nullable=False)
    content_type_counts_json: Mapped[str] = mapped_column(Text, nullable=False)
    robots_permission_counts_json: Mapped[str] = mapped_column(Text, nullable=False)
    indexability_counts_json: Mapped[str] = mapped_column(Text, nullable=False)
    source_page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    projection_truncated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    persisted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retention_state: Mapped[str] = mapped_column(String(24), nullable=False)
    evidence_version: Mapped[str] = mapped_column(String(64), nullable=False)
    persistence_version: Mapped[str] = mapped_column(String(64), nullable=False)
    ordering_version: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (Index("ix_page_summary_job", "job_id", "run_id"),)


class CrawlPageEvidenceEventModel(Base):
    __tablename__ = "crawl_page_evidence_events"

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    safe_reason_code: Mapped[str | None] = mapped_column(String(64))
    affected_count: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_version: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (Index("ix_page_evidence_events_run", "run_id", "event_id"),)


class MetadataAuditModel(Base):
    __tablename__ = "metadata_audits"

    audit_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.job_id", ondelete="CASCADE"))
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id", ondelete="CASCADE"))
    seed_url: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    configuration_json: Mapped[str] = mapped_column(Text, nullable=False)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    audit_version: Mapped[str] = mapped_column(String(64), nullable=False)
    taxonomy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    severity_version: Mapped[str] = mapped_column(String(64), nullable=False)
    duplicate_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    issue_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    partial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    failure_code: Mapped[str | None] = mapped_column(String(128))
    export_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("run_id", "configuration_hash", name="uq_metadata_audit_identity"),
        CheckConstraint(
            "state IN ('planned','running','completed','completed_with_warnings',"
            "'partially_completed','failed','cancelled')",
            name="ck_metadata_audit_state",
        ),
        Index("ix_metadata_audits_run", "run_id", "created_at"),
        Index("ix_metadata_audits_job", "job_id", "created_at"),
        Index("ix_metadata_audits_order", "created_at", "audit_id"),
    )


class MetadataAuditPageModel(Base):
    __tablename__ = "metadata_audit_pages"

    audit_page_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    audit_id: Mapped[str] = mapped_column(
        ForeignKey("metadata_audits.audit_id", ondelete="CASCADE")
    )
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("crawl_page_evidence.evidence_id", ondelete="RESTRICT")
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    url_identity: Mapped[str] = mapped_column(String(64), nullable=False)
    final_url: Mapped[str | None] = mapped_column(Text)
    fetch_outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    content_type: Mapped[str | None] = mapped_column(String(256))
    content_type_category: Mapped[str] = mapped_column(String(16), nullable=False)
    title_value: Mapped[str | None] = mapped_column(Text)
    title_presence: Mapped[str] = mapped_column(String(16), nullable=False)
    title_count: Mapped[int] = mapped_column(Integer, nullable=False)
    title_length: Mapped[int | None] = mapped_column(Integer)
    description_value: Mapped[str | None] = mapped_column(Text)
    description_presence: Mapped[str] = mapped_column(String(16), nullable=False)
    description_count: Mapped[int] = mapped_column(Integer, nullable=False)
    description_length: Mapped[int | None] = mapped_column(Integer)
    canonical_value: Mapped[str | None] = mapped_column(Text)
    canonical_state: Mapped[str] = mapped_column(String(16), nullable=False)
    robots_allowed: Mapped[bool | None] = mapped_column(Boolean)
    indexability_state: Mapped[str] = mapped_column(String(16), nullable=False)
    recommendation_state: Mapped[str | None] = mapped_column(String(32))
    issue_count: Mapped[int] = mapped_column(Integer, nullable=False)
    highest_severity: Mapped[str | None] = mapped_column(String(16))
    partial: Mapped[bool] = mapped_column(Boolean, nullable=False)
    audit_page_version: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("audit_id", "evidence_id", name="uq_metadata_audit_page_evidence"),
        Index("ix_metadata_audit_pages_order", "audit_id", "highest_severity", "url_identity"),
        Index("ix_metadata_audit_pages_status", "audit_id", "http_status", "url_identity"),
        Index("ix_metadata_audit_pages_content", "audit_id", "content_type_category"),
        Index("ix_metadata_audit_pages_indexability", "audit_id", "indexability_state"),
    )


class MetadataAuditIssueModel(Base):
    __tablename__ = "metadata_audit_issues"

    issue_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    audit_id: Mapped[str] = mapped_column(
        ForeignKey("metadata_audits.audit_id", ondelete="CASCADE")
    )
    audit_page_id: Mapped[str] = mapped_column(
        ForeignKey("metadata_audit_pages.audit_page_id", ondelete="CASCADE")
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    safe_summary: Mapped[str] = mapped_column(String(256), nullable=False)
    safe_detail: Mapped[str] = mapped_column(String(512), nullable=False)
    determinacy: Mapped[str] = mapped_column(String(16), nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False)
    duplicate_group_id: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    taxonomy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    severity_version: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("audit_page_id", "code", name="uq_metadata_audit_issue_code"),
        CheckConstraint(
            "category IN ('title','meta_description','canonical','robots','indexability',"
            "'status','content_type')",
            name="ck_metadata_audit_issue_category",
        ),
        CheckConstraint(
            "severity IN ('critical','high','medium','low','information')",
            name="ck_metadata_audit_issue_severity",
        ),
        Index(
            "ix_metadata_audit_issues_order",
            "audit_id",
            "severity",
            "category",
            "code",
            "audit_page_id",
        ),
        Index("ix_metadata_audit_issues_group", "duplicate_group_id", "issue_id"),
    )


class MetadataDuplicateGroupModel(Base):
    __tablename__ = "metadata_duplicate_groups"

    group_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    audit_id: Mapped[str] = mapped_column(
        ForeignKey("metadata_audits.audit_id", ondelete="CASCADE")
    )
    duplicate_type: Mapped[str] = mapped_column(String(32), nullable=False)
    normalized_value_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    sample_value: Mapped[str] = mapped_column(Text, nullable=False)
    member_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sample_members_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "audit_id",
            "duplicate_type",
            "normalized_value_hash",
            name="uq_metadata_duplicate_value",
        ),
        CheckConstraint(
            "duplicate_type IN ('title','meta_description')", name="ck_metadata_duplicate_type"
        ),
        Index("ix_metadata_duplicate_order", "audit_id", "member_count", "group_id"),
    )


class MetadataDuplicateGroupMemberModel(Base):
    __tablename__ = "metadata_duplicate_group_members"

    group_id: Mapped[str] = mapped_column(
        ForeignKey("metadata_duplicate_groups.group_id", ondelete="CASCADE"), primary_key=True
    )
    audit_page_id: Mapped[str] = mapped_column(
        ForeignKey("metadata_audit_pages.audit_page_id", ondelete="CASCADE"), primary_key=True
    )
    url_identity: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        Index("ix_metadata_duplicate_members_order", "group_id", "url_identity", "audit_page_id"),
    )


class MetadataAuditSummaryModel(Base):
    __tablename__ = "metadata_audit_summaries"

    audit_id: Mapped[str] = mapped_column(
        ForeignKey("metadata_audits.audit_id", ondelete="CASCADE"), primary_key=True
    )
    summary_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)


class MetadataAuditExportModel(Base):
    __tablename__ = "metadata_audit_exports"

    export_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audit_id: Mapped[str] = mapped_column(
        ForeignKey("metadata_audits.audit_id", ondelete="CASCADE")
    )
    export_format: Mapped[str] = mapped_column(String(16), nullable=False)
    artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifact_records.artifact_id", ondelete="SET NULL")
    )
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("audit_id", "export_format", name="uq_metadata_audit_export"),
    )


class MetadataAuditEventModel(Base):
    __tablename__ = "metadata_audit_events"

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    audit_id: Mapped[str] = mapped_column(
        ForeignKey("metadata_audits.audit_id", ondelete="CASCADE")
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    safe_reason_code: Mapped[str | None] = mapped_column(String(128))
    affected_count: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (Index("ix_metadata_audit_events", "audit_id", "event_id"),)


class WarningModel(Base):
    __tablename__ = "warnings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_type: Mapped[str] = mapped_column(String(16), nullable=False)
    parent_id: Mapped[str] = mapped_column(String(40), nullable=False)
    stage: Mapped[str | None] = mapped_column(String(32))
    stable_code: Mapped[str] = mapped_column(String(128), nullable=False)
    source_layer: Mapped[str] = mapped_column(String(32), nullable=False)
    source_code: Mapped[str] = mapped_column(String(128), nullable=False)
    safe_message: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_url: Mapped[str | None] = mapped_column(Text)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="warning")
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint(
            "parent_type",
            "parent_id",
            "stable_code",
            "stage",
            "safe_message",
            name="uq_warning_exact",
        ),
        Index("ix_warnings_parent_sequence", "parent_type", "parent_id", "sequence"),
    )


class FailureModel(Base):
    __tablename__ = "failures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_type: Mapped[str] = mapped_column(String(16), nullable=False)
    parent_id: Mapped[str] = mapped_column(String(40), nullable=False)
    stage: Mapped[str | None] = mapped_column(String(32))
    stable_code: Mapped[str] = mapped_column(String(128), nullable=False)
    source_layer: Mapped[str] = mapped_column(String(32), nullable=False)
    source_code: Mapped[str] = mapped_column(String(128), nullable=False)
    safe_message: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_url: Mapped[str | None] = mapped_column(Text)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="error")
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_failures_parent_sequence", "parent_type", "parent_id", "sequence"),)


class SummaryMetadataModel(Base):
    __tablename__ = "summary_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    summary_type: Mapped[str] = mapped_column(String(16), nullable=False)
    logical_filename: Mapped[str] = mapped_column(String(128), nullable=False)
    byte_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    availability: Mapped[bool] = mapped_column(Boolean, nullable=False)
    write_outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(128))
    retention_state: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "logical_filename", name="uq_summary_run_filename"),
        CheckConstraint("length(sha256) = 64", name="ck_summary_sha256"),
    )


class ArtifactMetadataModel(Base):
    __tablename__ = "artifact_metadata"

    artifact_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.job_id", ondelete="SET NULL"))
    artifact_type: Mapped[str] = mapped_column(String(32), nullable=False)
    logical_filename: Mapped[str] = mapped_column(String(128), nullable=False)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    byte_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_count: Mapped[int | None] = mapped_column(Integer)
    publication_state: Mapped[str] = mapped_column(String(32), nullable=False)
    retention_state: Mapped[str] = mapped_column(String(32), nullable=False)
    storage_root_identifier: Mapped[str | None] = mapped_column(String(64))
    relative_storage_reference: Mapped[str | None] = mapped_column(String(256))
    failure_code: Mapped[str | None] = mapped_column(String(128))
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "artifact_type", "logical_filename", name="uq_artifact_run"),
        CheckConstraint("length(sha256) = 64", name="ck_artifact_sha256"),
        Index("ix_artifacts_run_sequence", "run_id", "sequence"),
    )


class ArtifactStorageRootModel(Base):
    """Safe durable root identity; absolute paths remain runtime-only configuration."""

    __tablename__ = "artifact_storage_roots"

    root_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    readiness_state: Mapped[str] = mapped_column(String(32), nullable=False)
    readable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    writable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    last_checked_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(128))
    storage_version: Mapped[str] = mapped_column(String(64), nullable=False)


class ArtifactRecordModel(Base):
    __tablename__ = "artifact_records"

    artifact_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    artifact_type: Mapped[str] = mapped_column(String(32), nullable=False)
    root_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_storage_roots.root_id", ondelete="RESTRICT"), nullable=False
    )
    relative_path: Mapped[str] = mapped_column(String(512), nullable=False)
    safe_filename: Mapped[str] = mapped_column(String(128), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    lifecycle_state: Mapped[str] = mapped_column(String(32), nullable=False)
    integrity_state: Mapped[str] = mapped_column(String(32), nullable=False)
    expected_byte_count: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_byte_count: Mapped[int | None] = mapped_column(Integer)
    expected_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retention_state: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(128))
    storage_version: Mapped[str] = mapped_column(String(64), nullable=False)
    retrieval_version: Mapped[str] = mapped_column(String(64), nullable=False)
    reconciliation_version: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "run_id", "artifact_type", "root_id", "relative_path", name="uq_artifact_record"
        ),
        CheckConstraint("expected_byte_count >= 0", name="ck_artifact_record_expected_bytes"),
        CheckConstraint("length(expected_sha256) = 64", name="ck_artifact_record_sha256"),
        CheckConstraint(
            "artifact_type IN ('sitemap_xml','sitemap_index','publication_manifest',"
            "'run_summary_json','run_summary_markdown','csv_export')",
            name="ck_artifact_record_type",
        ),
        CheckConstraint(
            "lifecycle_state IN ('planned','available','missing','corrupt','expired',"
            "'deleted','retained')",
            name="ck_artifact_record_lifecycle",
        ),
        CheckConstraint(
            "integrity_state IN ('unverified','verified','missing','size_mismatch',"
            "'hash_mismatch','type_mismatch','unsafe_path','read_failed','manifest_mismatch')",
            name="ck_artifact_record_integrity",
        ),
        CheckConstraint(
            "retention_state IN ('normal','retained','expired','cleanup_pending','deleted')",
            name="ck_artifact_record_retention",
        ),
        Index("ix_artifact_records_job", "job_id"),
        Index("ix_artifact_records_run", "run_id"),
        Index("ix_artifact_records_lifecycle", "lifecycle_state"),
        Index("ix_artifact_records_expiration", "retention_state", "expires_at"),
        Index("ix_artifact_records_type", "artifact_type"),
        Index("ix_artifact_records_integrity", "integrity_state"),
    )


class ArtifactIntegrityCheckModel(Base):
    __tablename__ = "artifact_integrity_checks"

    check_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_records.artifact_id", ondelete="CASCADE"), nullable=False
    )
    checked_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    integrity_state: Mapped[str] = mapped_column(String(32), nullable=False)
    observed_byte_count: Mapped[int | None] = mapped_column(Integer)
    observed_sha256: Mapped[str | None] = mapped_column(String(64))
    reason_code: Mapped[str | None] = mapped_column(String(128))

    __table_args__ = (Index("ix_artifact_integrity_history", "artifact_id", "check_id"),)


class ArtifactLifecycleEventModel(Base):
    __tablename__ = "artifact_lifecycle_events"

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_records.artifact_id", ondelete="CASCADE"), nullable=False
    )
    occurred_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    from_state: Mapped[str | None] = mapped_column(String(32))
    to_state: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(128))

    __table_args__ = (Index("ix_artifact_lifecycle_history", "artifact_id", "event_id"),)


class ArtifactCleanupEventModel(Base):
    __tablename__ = "artifact_cleanup_events"

    cleanup_event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_records.artifact_id", ondelete="CASCADE"), nullable=False
    )
    occurred_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(128))

    __table_args__ = (Index("ix_artifact_cleanup_history", "artifact_id", "cleanup_event_id"),)


class ArtifactReconciliationEventModel(Base):
    __tablename__ = "artifact_reconciliation_events"

    reconciliation_event_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    root_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_storage_roots.root_id", ondelete="CASCADE"), nullable=False
    )
    artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifact_records.artifact_id", ondelete="SET NULL")
    )
    occurred_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    event_code: Mapped[str] = mapped_column(String(128), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (
        Index("ix_artifact_reconciliation_history", "root_id", "reconciliation_event_id"),
    )
