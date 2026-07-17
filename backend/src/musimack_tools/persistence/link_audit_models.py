"""SQLAlchemy models for durable source links and private link audits."""

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


class CrawlLinkEvidenceModel(Base):
    __tablename__ = "crawl_link_evidence"

    link_id: Mapped[str] = mapped_column(String(64), primary_key=True)
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
    link_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    discovery_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    element_type: Mapped[str] = mapped_column(String(16), nullable=False)
    raw_href: Mapped[str | None] = mapped_column(Text)
    resolved_url: Mapped[str | None] = mapped_column(Text)
    target_url_identity: Mapped[str | None] = mapped_column(String(64))
    target_scheme: Mapped[str | None] = mapped_column(String(32))
    target_host: Mapped[str | None] = mapped_column(String(255))
    internal: Mapped[bool | None] = mapped_column(Boolean)
    in_scope: Mapped[bool | None] = mapped_column(Boolean)
    scope_reason_code: Mapped[str | None] = mapped_column(String(64))
    anchor_text: Mapped[str | None] = mapped_column(String(512))
    rel_values_json: Mapped[str] = mapped_column(Text, nullable=False)
    nofollow: Mapped[bool] = mapped_column(Boolean, nullable=False)
    fragment: Mapped[str | None] = mapped_column(String(512))
    link_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resolution_warning: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_version: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "source_evidence_id", "link_sequence", name="uq_crawl_link_source_sequence"
        ),
        UniqueConstraint("run_id", "discovery_sequence", name="uq_crawl_link_run_sequence"),
        CheckConstraint(
            "source_discovery_sequence >= 0 and source_crawl_depth >= 0 "
            "and link_sequence >= 0 and discovery_sequence >= 0",
            name="ck_crawl_link_sequences",
        ),
        CheckConstraint(
            "link_type in ('http','mailto','tel','javascript','data','fragment','invalid','unsupported')",
            name="ck_crawl_link_type",
        ),
        Index("ix_crawl_link_run_order", "run_id", "discovery_sequence", "link_id"),
        Index("ix_crawl_link_source", "source_evidence_id", "link_sequence"),
        Index("ix_crawl_link_target", "run_id", "target_url_identity", "discovery_sequence"),
        Index("ix_crawl_link_scope", "run_id", "internal", "in_scope", "link_type"),
    )


class LinkAuditModel(Base):
    __tablename__ = "link_audits"

    audit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.job_id", ondelete="CASCADE"))
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id", ondelete="CASCADE"))
    seed_url: Mapped[str] = mapped_column(Text, nullable=False)
    configuration_json: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(128))
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    link_occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_target_pair_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    target_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    working_target_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    broken_target_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    redirect_target_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unverified_target_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    redirect_chain_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    redirect_loop_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recommendation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retention_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    audit_version: Mapped[str] = mapped_column(String(64), nullable=False)
    link_evidence_version: Mapped[str] = mapped_column(String(64), nullable=False)
    page_evidence_version: Mapped[str] = mapped_column(String(64), nullable=False)
    link_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    redirect_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "state in ('accepted','claiming','building_graph','classifying_links',"
            "'expanding_redirects','detecting_loops','building_recommendations',"
            "'completed','completed_with_warnings','failed','cancelled')",
            name="ck_link_audits_state",
        ),
        CheckConstraint(
            "warning_count >= 0 and link_occurrence_count >= 0 and source_target_pair_count >= 0 "
            "and target_count >= 0 and working_target_count >= 0 and broken_target_count >= 0 "
            "and redirect_target_count >= 0 and unverified_target_count >= 0 "
            "and redirect_chain_count >= 0 and redirect_loop_count >= 0 "
            "and recommendation_count >= 0",
            name="ck_link_audits_counts",
        ),
        Index("ix_link_audits_run_created", "run_id", "created_at", "audit_id"),
        Index("ix_link_audits_state_created", "state", "created_at", "audit_id"),
    )


class LinkAuditTargetModel(Base):
    __tablename__ = "link_audit_targets"

    target_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audit_id: Mapped[str] = mapped_column(ForeignKey("link_audits.audit_id", ondelete="CASCADE"))
    target_url: Mapped[str] = mapped_column(Text, nullable=False)
    target_url_identity: Mapped[str] = mapped_column(String(64), nullable=False)
    representative_link_id: Mapped[str | None] = mapped_column(
        ForeignKey("crawl_link_evidence.link_id", ondelete="SET NULL")
    )
    page_evidence_id: Mapped[str | None] = mapped_column(
        ForeignKey("crawl_page_evidence.evidence_id", ondelete="SET NULL")
    )
    internal: Mapped[bool | None] = mapped_column(Boolean)
    in_scope: Mapped[bool | None] = mapped_column(Boolean)
    http_status: Mapped[int | None] = mapped_column(Integer)
    fetch_state: Mapped[str | None] = mapped_column(String(32))
    content_type: Mapped[str | None] = mapped_column(String(256))
    broken_state: Mapped[str] = mapped_column(String(48), nullable=False)
    redirect_state: Mapped[str] = mapped_column(String(48), nullable=False)
    primary_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    redirect_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    action: Mapped[str] = mapped_column(String(48), nullable=False)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)
    final_target: Mapped[str | None] = mapped_column(Text)
    redirect_hop_count: Mapped[int] = mapped_column(Integer, nullable=False)
    unique_source_page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    unique_anchor_count: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_source_depth: Mapped[int] = mapped_column(Integer, nullable=False)
    maximum_source_depth: Mapped[int] = mapped_column(Integer, nullable=False)
    sitewide_candidate: Mapped[bool] = mapped_column(Boolean, nullable=False)
    target_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    analysis_version: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("audit_id", "target_url_identity", name="uq_link_audit_target_identity"),
        UniqueConstraint("audit_id", "target_sequence", name="uq_link_audit_target_sequence"),
        CheckConstraint(
            "redirect_hop_count >= 0 and unique_source_page_count >= 0 "
            "and total_occurrence_count >= 0 and unique_anchor_count >= 0 "
            "and minimum_source_depth >= 0 and maximum_source_depth >= minimum_source_depth "
            "and target_sequence >= 0",
            name="ck_link_audit_target_metrics",
        ),
        Index("ix_link_target_order", "audit_id", "target_sequence", "target_id"),
        Index("ix_link_target_state", "audit_id", "broken_state", "redirect_state"),
        Index("ix_link_target_filter", "audit_id", "severity", "action", "primary_reason"),
        Index(
            "ix_link_target_impact", "audit_id", "sitewide_candidate", "unique_source_page_count"
        ),
    )


class LinkAuditChainModel(Base):
    __tablename__ = "link_audit_redirect_chains"

    chain_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audit_id: Mapped[str] = mapped_column(ForeignKey("link_audits.audit_id", ondelete="CASCADE"))
    target_id: Mapped[str] = mapped_column(
        ForeignKey("link_audit_targets.target_id", ondelete="CASCADE")
    )
    entry_url: Mapped[str] = mapped_column(Text, nullable=False)
    final_url: Mapped[str | None] = mapped_column(Text)
    chain_state: Mapped[str] = mapped_column(String(48), nullable=False)
    hop_count: Mapped[int] = mapped_column(Integer, nullable=False)
    loop: Mapped[bool] = mapped_column(Boolean, nullable=False)
    nodes_json: Mapped[str] = mapped_column(Text, nullable=False)
    edges_json: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    source_occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    chain_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    chain_version: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("audit_id", "target_id", name="uq_link_chain_target"),
        UniqueConstraint("audit_id", "chain_sequence", name="uq_link_chain_sequence"),
        CheckConstraint(
            "hop_count >= 0 and source_occurrence_count >= 0 and chain_sequence >= 0",
            name="ck_link_chain_metrics",
        ),
        Index("ix_link_chain_order", "audit_id", "chain_sequence", "chain_id"),
        Index("ix_link_chain_loop", "audit_id", "loop", "severity"),
    )


class LinkAuditFindingModel(Base):
    __tablename__ = "link_audit_findings"

    finding_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audit_id: Mapped[str] = mapped_column(ForeignKey("link_audits.audit_id", ondelete="CASCADE"))
    target_id: Mapped[str | None] = mapped_column(
        ForeignKey("link_audit_targets.target_id", ondelete="CASCADE")
    )
    chain_id: Mapped[str | None] = mapped_column(
        ForeignKey("link_audit_redirect_chains.chain_id", ondelete="CASCADE")
    )
    stable_code: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    safe_message: Mapped[str] = mapped_column(String(512), nullable=False)
    context_json: Mapped[str] = mapped_column(Text, nullable=False)
    finding_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("audit_id", "finding_sequence", name="uq_link_finding_sequence"),
        Index("ix_link_finding_order", "audit_id", "finding_sequence", "finding_id"),
        Index("ix_link_finding_filter", "audit_id", "severity", "stable_code"),
    )


class LinkAuditRecommendationModel(Base):
    __tablename__ = "link_audit_recommendations"

    recommendation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audit_id: Mapped[str] = mapped_column(ForeignKey("link_audits.audit_id", ondelete="CASCADE"))
    target_id: Mapped[str] = mapped_column(
        ForeignKey("link_audit_targets.target_id", ondelete="CASCADE")
    )
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_destination: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(String(48), nullable=False)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    human_review_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    supporting_evidence_json: Mapped[str] = mapped_column(Text, nullable=False)
    unique_source_page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    recommendation_sequence: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("audit_id", "target_id", name="uq_link_recommendation_target"),
        UniqueConstraint(
            "audit_id", "recommendation_sequence", name="uq_link_recommendation_sequence"
        ),
        Index(
            "ix_link_recommendation_order",
            "audit_id",
            "recommendation_sequence",
            "recommendation_id",
        ),
        Index("ix_link_recommendation_filter", "audit_id", "action", "confidence", "severity"),
    )


class LinkAuditExportModel(Base):
    __tablename__ = "link_audit_exports"

    export_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audit_id: Mapped[str] = mapped_column(ForeignKey("link_audits.audit_id", ondelete="CASCADE"))
    export_format: Mapped[str] = mapped_column(String(32), nullable=False)
    artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifact_records.artifact_id", ondelete="SET NULL")
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    export_version: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("audit_id", "export_format", name="uq_link_audit_export_format"),
        Index("ix_link_export_audit", "audit_id", "created_at", "export_id"),
        Index("ix_link_export_artifact", "artifact_id"),
    )


class LinkAuditEventModel(Base):
    __tablename__ = "link_audit_events"

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    audit_id: Mapped[str] = mapped_column(ForeignKey("link_audits.audit_id", ondelete="CASCADE"))
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    safe_code: Mapped[str | None] = mapped_column(String(128))
    counts_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("audit_id", "sequence", name="uq_link_audit_event_sequence"),
        Index("ix_link_event_order", "audit_id", "sequence"),
    )
