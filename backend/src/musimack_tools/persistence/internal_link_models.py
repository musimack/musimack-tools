"""Normalized durable models for internal-link analysis."""

# ruff: noqa: E501

from __future__ import annotations

from datetime import datetime  # noqa: TC003

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


class InternalLinkAuditModel(Base):
    __tablename__ = "internal_link_audits"

    audit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.job_id", ondelete="CASCADE"))
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id", ondelete="CASCADE"))
    seed_url: Mapped[str] = mapped_column(Text, nullable=False)
    scope_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    seed_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    configuration_json: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(128))
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    node_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    eligible_page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    edge_occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unique_edge_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reachable_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    orphan_candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deep_page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hub_candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    authority_candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    anchor_finding_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    opportunity_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retention_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    audit_version: Mapped[str] = mapped_column(String(64), nullable=False)
    graph_version: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    page_evidence_version: Mapped[str] = mapped_column(String(64), nullable=False)
    link_evidence_version: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "state in ('accepted','claiming','building_graph','computing_metrics','analyzing_reachability','analyzing_anchors','building_opportunities','completed','completed_with_warnings','failed','cancelled')",
            name="ck_internal_link_audit_state",
        ),
        CheckConstraint(
            "warning_count >= 0 and node_count >= 0 and eligible_page_count >= 0 and edge_occurrence_count >= 0 and unique_edge_count >= 0 and reachable_count >= 0 and orphan_candidate_count >= 0 and deep_page_count >= 0 and hub_candidate_count >= 0 and authority_candidate_count >= 0 and anchor_finding_count >= 0 and opportunity_count >= 0",
            name="ck_internal_link_audit_counts",
        ),
        Index("ix_internal_link_audit_run", "run_id", "created_at", "audit_id"),
        Index("ix_internal_link_audit_state", "state", "created_at", "audit_id"),
    )


class InternalLinkPageMetricModel(Base):
    __tablename__ = "internal_link_page_metrics"

    metric_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audit_id: Mapped[str] = mapped_column(
        ForeignKey("internal_link_audits.audit_id", ondelete="CASCADE")
    )
    page_evidence_id: Mapped[str | None] = mapped_column(
        ForeignKey("crawl_page_evidence.evidence_id", ondelete="SET NULL")
    )
    requested_url: Mapped[str] = mapped_column(Text, nullable=False)
    final_url: Mapped[str | None] = mapped_column(Text)
    page_identity: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_identity: Mapped[str | None] = mapped_column(String(64))
    eligibility: Mapped[str] = mapped_column(String(40), nullable=False)
    exclusion_reason: Mapped[str | None] = mapped_column(String(64))
    primary_state: Mapped[str] = mapped_column(String(40), nullable=False)
    orphan_state: Mapped[str] = mapped_column(String(48), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    inbound_occurrences: Mapped[int] = mapped_column(Integer, nullable=False)
    unique_referring_pages: Mapped[int] = mapped_column(Integer, nullable=False)
    outbound_occurrences: Mapped[int] = mapped_column(Integer, nullable=False)
    unique_destination_pages: Mapped[int] = mapped_column(Integer, nullable=False)
    direct_inlinks: Mapped[int] = mapped_column(Integer, nullable=False)
    redirect_adjusted_inlinks: Mapped[int] = mapped_column(Integer, nullable=False)
    nofollow_inlinks: Mapped[int] = mapped_column(Integer, nullable=False)
    nofollow_outlinks: Mapped[int] = mapped_column(Integer, nullable=False)
    redirecting_outlinks: Mapped[int] = mapped_column(Integer, nullable=False)
    broken_outlinks: Mapped[int] = mapped_column(Integer, nullable=False)
    external_outlinks: Mapped[int] = mapped_column(Integer, nullable=False)
    sitewide_inlinks: Mapped[int] = mapped_column(Integer, nullable=False)
    non_sitewide_inlinks: Mapped[int] = mapped_column(Integer, nullable=False)
    crawl_depth: Mapped[int] = mapped_column(Integer, nullable=False)
    graph_depth: Mapped[int | None] = mapped_column(Integer)
    reachable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    distinct_seed_paths: Mapped[int] = mapped_column(Integer, nullable=False)
    unique_anchor_count: Mapped[int] = mapped_column(Integer, nullable=False)
    dominant_anchor: Mapped[str | None] = mapped_column(String(512))
    dominant_anchor_share: Mapped[float] = mapped_column(Float, nullable=False)
    url_anchor_count: Mapped[int] = mapped_column(Integer, nullable=False)
    hub_state: Mapped[str] = mapped_column(String(32), nullable=False)
    authority_state: Mapped[str] = mapped_column(String(32), nullable=False)
    discovery_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    page_sequence: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("audit_id", "page_identity", name="uq_internal_link_page_identity"),
        UniqueConstraint("audit_id", "page_sequence", name="uq_internal_link_page_sequence"),
        CheckConstraint(
            "inbound_occurrences >= 0 and unique_referring_pages >= 0 and outbound_occurrences >= 0 and unique_destination_pages >= 0 and direct_inlinks >= 0 and redirect_adjusted_inlinks >= 0 and nofollow_inlinks >= 0 and nofollow_outlinks >= 0 and redirecting_outlinks >= 0 and broken_outlinks >= 0 and external_outlinks >= 0 and sitewide_inlinks >= 0 and non_sitewide_inlinks >= 0 and crawl_depth >= 0 and (graph_depth is null or graph_depth >= 0) and distinct_seed_paths >= 0 and unique_anchor_count >= 0 and dominant_anchor_share >= 0 and dominant_anchor_share <= 1 and url_anchor_count >= 0 and discovery_sequence >= 0 and page_sequence >= 0",
            name="ck_internal_link_page_metrics",
        ),
        Index("ix_internal_link_page_order", "audit_id", "page_sequence", "metric_id"),
        Index(
            "ix_internal_link_page_states",
            "audit_id",
            "eligibility",
            "primary_state",
            "orphan_state",
        ),
        Index(
            "ix_internal_link_page_candidates",
            "audit_id",
            "hub_state",
            "authority_state",
            "severity",
        ),
    )


class InternalLinkEdgeModel(Base):
    __tablename__ = "internal_link_edges"
    edge_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audit_id: Mapped[str] = mapped_column(
        ForeignKey("internal_link_audits.audit_id", ondelete="CASCADE")
    )
    source_identity: Mapped[str] = mapped_column(String(64), nullable=False)
    target_identity: Mapped[str] = mapped_column(String(64), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    target_url: Mapped[str] = mapped_column(Text, nullable=False)
    redirect_adjusted_identity: Mapped[str | None] = mapped_column(String(64))
    canonical_adjusted_identity: Mapped[str | None] = mapped_column(String(64))
    raw_occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    nofollow_occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sitewide: Mapped[bool] = mapped_column(Boolean, nullable=False)
    edge_state: Mapped[str] = mapped_column(String(40), nullable=False)
    anchor_summary_json: Mapped[str] = mapped_column(Text, nullable=False)
    edge_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (
        UniqueConstraint(
            "audit_id", "source_identity", "target_identity", name="uq_internal_link_edge_pair"
        ),
        UniqueConstraint("audit_id", "edge_sequence", name="uq_internal_link_edge_sequence"),
        CheckConstraint(
            "raw_occurrence_count > 0 and nofollow_occurrence_count >= 0 and edge_sequence >= 0",
            name="ck_internal_link_edge_counts",
        ),
        Index("ix_internal_link_edge_order", "audit_id", "edge_sequence", "edge_id"),
        Index(
            "ix_internal_link_edge_source_target", "audit_id", "source_identity", "target_identity"
        ),
    )


class InternalLinkReachabilityModel(Base):
    __tablename__ = "internal_link_reachability"
    reachability_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audit_id: Mapped[str] = mapped_column(
        ForeignKey("internal_link_audits.audit_id", ondelete="CASCADE")
    )
    page_identity: Mapped[str] = mapped_column(String(64), nullable=False)
    seed_identity: Mapped[str | None] = mapped_column(String(64))
    predecessor_identity: Mapped[str | None] = mapped_column(String(64))
    distance: Mapped[int | None] = mapped_column(Integer)
    reachable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    redirect_dependent: Mapped[bool] = mapped_column(Boolean, nullable=False)
    nofollow_only: Mapped[bool] = mapped_column(Boolean, nullable=False)
    path_json: Mapped[str] = mapped_column(Text, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (
        UniqueConstraint("audit_id", "page_identity", name="uq_internal_link_reachability_page"),
        UniqueConstraint("audit_id", "sequence", name="uq_internal_link_reachability_sequence"),
        Index("ix_internal_link_reachability_order", "audit_id", "sequence"),
        Index("ix_internal_link_reachability_state", "audit_id", "reachable", "distance"),
    )


class InternalLinkFindingModel(Base):
    __tablename__ = "internal_link_findings"
    finding_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audit_id: Mapped[str] = mapped_column(
        ForeignKey("internal_link_audits.audit_id", ondelete="CASCADE")
    )
    page_identity: Mapped[str | None] = mapped_column(String(64))
    edge_id: Mapped[str | None] = mapped_column(
        ForeignKey("internal_link_edges.edge_id", ondelete="CASCADE")
    )
    stable_code: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    safe_message: Mapped[str] = mapped_column(String(512), nullable=False)
    context_json: Mapped[str] = mapped_column(Text, nullable=False)
    finding_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (
        UniqueConstraint("audit_id", "finding_sequence", name="uq_internal_link_finding_sequence"),
        Index("ix_internal_link_finding_order", "audit_id", "finding_sequence"),
        Index("ix_internal_link_finding_filter", "audit_id", "severity", "stable_code"),
    )


class InternalLinkAnchorModel(Base):
    __tablename__ = "internal_link_anchor_aggregates"
    anchor_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audit_id: Mapped[str] = mapped_column(
        ForeignKey("internal_link_audits.audit_id", ondelete="CASCADE")
    )
    target_identity: Mapped[str] = mapped_column(String(64), nullable=False)
    target_url: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_anchor: Mapped[str] = mapped_column(String(512), nullable=False)
    representative_anchor: Mapped[str | None] = mapped_column(String(512))
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    share: Mapped[float] = mapped_column(Float, nullable=False)
    anchor_state: Mapped[str] = mapped_column(String(48), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    sample_sources_json: Mapped[str] = mapped_column(Text, nullable=False)
    anchor_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (
        UniqueConstraint(
            "audit_id", "target_identity", "normalized_anchor", name="uq_internal_link_anchor_group"
        ),
        UniqueConstraint("audit_id", "anchor_sequence", name="uq_internal_link_anchor_sequence"),
        CheckConstraint(
            "occurrence_count > 0 and source_page_count > 0 and share >= 0 and share <= 1 and anchor_sequence >= 0",
            name="ck_internal_link_anchor_metrics",
        ),
        Index("ix_internal_link_anchor_order", "audit_id", "anchor_sequence"),
        Index("ix_internal_link_anchor_filter", "audit_id", "anchor_state", "severity"),
    )


class InternalLinkOpportunityModel(Base):
    __tablename__ = "internal_link_opportunities"
    opportunity_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audit_id: Mapped[str] = mapped_column(
        ForeignKey("internal_link_audits.audit_id", ondelete="CASCADE")
    )
    source_identity: Mapped[str | None] = mapped_column(String(64))
    source_url: Mapped[str | None] = mapped_column(Text)
    target_identity: Mapped[str] = mapped_column(String(64), nullable=False)
    target_url: Mapped[str] = mapped_column(Text, nullable=False)
    opportunity_type: Mapped[str] = mapped_column(String(48), nullable=False)
    action: Mapped[str] = mapped_column(String(48), nullable=False)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    human_review_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    supporting_metrics_json: Mapped[str] = mapped_column(Text, nullable=False)
    opportunity_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (
        UniqueConstraint(
            "audit_id", "opportunity_sequence", name="uq_internal_link_opportunity_sequence"
        ),
        Index("ix_internal_link_opportunity_order", "audit_id", "opportunity_sequence"),
        Index(
            "ix_internal_link_opportunity_filter",
            "audit_id",
            "opportunity_type",
            "action",
            "confidence",
            "severity",
        ),
    )


class InternalLinkExportModel(Base):
    __tablename__ = "internal_link_exports"
    export_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audit_id: Mapped[str] = mapped_column(
        ForeignKey("internal_link_audits.audit_id", ondelete="CASCADE")
    )
    export_format: Mapped[str] = mapped_column(String(40), nullable=False)
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
        UniqueConstraint("audit_id", "export_format", name="uq_internal_link_export_format"),
        Index("ix_internal_link_export_audit", "audit_id", "created_at", "export_id"),
        Index("ix_internal_link_export_artifact", "artifact_id"),
    )


class InternalLinkEventModel(Base):
    __tablename__ = "internal_link_events"
    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    audit_id: Mapped[str] = mapped_column(
        ForeignKey("internal_link_audits.audit_id", ondelete="CASCADE")
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    safe_code: Mapped[str | None] = mapped_column(String(128))
    counts_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint("audit_id", "sequence", name="uq_internal_link_event_sequence"),
        Index("ix_internal_link_event_order", "audit_id", "sequence"),
    )
