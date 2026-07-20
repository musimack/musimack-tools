"""Normalized CSA-03 aggregate, evidence, and projection storage models."""

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


class SiteAuditModel(Base):
    __tablename__ = "site_audits"

    audit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audit_name: Mapped[str] = mapped_column(String(200), nullable=False)
    site_label: Mapped[str | None] = mapped_column(String(200))
    seed_url: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_seed_url: Mapped[str] = mapped_column(Text, nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(32), nullable=False)
    population_completeness: Mapped[str] = mapped_column(String(32), nullable=False)
    module_completeness: Mapped[str] = mapped_column(String(32), nullable=False)
    partial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    draft_json: Mapped[str] = mapped_column(Text, nullable=False)
    draft_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(128))
    failure_explanation: Mapped[str | None] = mapped_column(Text)
    projection_version: Mapped[str] = mapped_column(String(64), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    site_profile_id: Mapped[str | None] = mapped_column(String(64))
    site_profile_version: Mapped[int | None] = mapped_column(Integer)
    platform_preset_id: Mapped[str | None] = mapped_column(String(64))
    platform_preset_version: Mapped[str | None] = mapped_column(String(64))
    parent_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.job_id", ondelete="SET NULL")
    )
    parent_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.run_id", ondelete="SET NULL")
    )

    __table_args__ = (
        CheckConstraint(
            "lifecycle in ('draft','validating','validation_failed','validated',"
            "'preflighting','preflight_failed','ready','queued','running',"
            "'cancel_requested','cancelled','completed','completed_with_warnings',"
            "'partially_completed','failed','recovery_required','archived')",
            name="ck_site_audit_lifecycle",
        ),
        CheckConstraint("revision > 0", name="ck_site_audit_revision_positive"),
        CheckConstraint("length(draft_hash) = 64", name="ck_site_audit_draft_hash"),
        Index("ix_site_audits_created", "created_at", "audit_id"),
        Index("ix_site_audits_lifecycle", "lifecycle", "created_at", "audit_id"),
        Index("ix_site_audits_seed", "normalized_seed_url", "created_at", "audit_id"),
    )


class SiteAuditSnapshotModel(Base):
    __tablename__ = "site_audit_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audit_id: Mapped[str] = mapped_column(
        ForeignKey("site_audits.audit_id", ondelete="CASCADE"), nullable=False, unique=True
    )
    source_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    canonical_json: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    approved_hosts_json: Mapped[str] = mapped_column(Text, nullable=False)
    scope_policy_json: Mapped[str] = mapped_column(Text, nullable=False)
    crawl_limits_json: Mapped[str] = mapped_column(Text, nullable=False)
    thresholds_json: Mapped[str] = mapped_column(Text, nullable=False)
    enabled_modules_json: Mapped[str] = mapped_column(Text, nullable=False)
    tracking_parameters_json: Mapped[str] = mapped_column(Text, nullable=False)
    population_definition_version: Mapped[str] = mapped_column(String(64), nullable=False)
    priority_model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_schema_versions_json: Mapped[str] = mapped_column(Text, nullable=False)
    application_version: Mapped[str] = mapped_column(String(64), nullable=False)
    projection_version: Mapped[str] = mapped_column(String(64), nullable=False)
    site_profile_id: Mapped[str | None] = mapped_column(String(64))
    site_profile_version: Mapped[int | None] = mapped_column(Integer)
    platform_preset_id: Mapped[str | None] = mapped_column(String(64))
    platform_preset_version: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("source_revision > 0", name="ck_site_audit_snapshot_revision"),
        CheckConstraint("length(sha256) = 64", name="ck_site_audit_snapshot_hash"),
        Index("ix_site_audit_snapshots_audit", "audit_id", "created_at"),
    )


class SiteAuditRuleSnapshotModel(Base):
    __tablename__ = "site_audit_rule_snapshots"

    snapshot_rule_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("site_audit_snapshots.snapshot_id", ondelete="CASCADE"), nullable=False
    )
    audit_id: Mapped[str] = mapped_column(
        ForeignKey("site_audits.audit_id", ondelete="CASCADE"), nullable=False
    )
    stable_rule_id: Mapped[str] = mapped_column(String(96), nullable=False)
    rule_source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(64))
    source_version: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_layer: Mapped[str] = mapped_column(String(32), nullable=False)
    match_type: Mapped[str] = mapped_column(String(40), nullable=False)
    match_value: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    specificity: Mapped[int] = mapped_column(Integer, nullable=False)
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    overrides_rule_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    stable_order: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("snapshot_id", "stable_rule_id", name="uq_site_audit_snapshot_rule"),
        Index("ix_site_audit_rules_order", "audit_id", "decision_layer", "stable_order"),
    )


class SiteAuditDisabledRuleModel(Base):
    __tablename__ = "site_audit_disabled_inherited_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("site_audit_snapshots.snapshot_id", ondelete="CASCADE"), nullable=False
    )
    audit_id: Mapped[str] = mapped_column(
        ForeignKey("site_audits.audit_id", ondelete="CASCADE"), nullable=False
    )
    stable_rule_id: Mapped[str] = mapped_column(String(96), nullable=False)
    rule_source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_version: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)

    __table_args__ = (
        UniqueConstraint("snapshot_id", "stable_rule_id", name="uq_site_audit_disabled_rule"),
        Index("ix_site_audit_disabled_rules", "audit_id", "stable_rule_id"),
    )


class SiteAuditURLModel(Base):
    __tablename__ = "site_audit_urls"

    url_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audit_id: Mapped[str] = mapped_column(
        ForeignKey("site_audits.audit_id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    original_url: Mapped[str] = mapped_column(Text, nullable=False)
    requested_url: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_url: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_url_identity: Mapped[str] = mapped_column(String(64), nullable=False)
    final_url: Mapped[str | None] = mapped_column(Text)
    host: Mapped[str] = mapped_column(String(253), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    discovery_state: Mapped[str] = mapped_column(String(32), nullable=False)
    enqueued_state: Mapped[str] = mapped_column(String(32), nullable=False)
    fetch_state: Mapped[str] = mapped_column(String(32), nullable=False)
    parse_state: Mapped[str] = mapped_column(String(32), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    content_type: Mapped[str | None] = mapped_column(String(256))
    fetch_outcome: Mapped[str | None] = mapped_column(String(64))
    redirect_state: Mapped[str] = mapped_column(String(32), nullable=False)
    robots_state: Mapped[str] = mapped_column(String(32), nullable=False)
    indexability_state: Mapped[str] = mapped_column(String(32), nullable=False)
    canonical_state: Mapped[str] = mapped_column(String(32), nullable=False)
    existing_sitemap_state: Mapped[str] = mapped_column(String(32), nullable=False)
    recommended_sitemap_state: Mapped[str] = mapped_column(String(32), nullable=False)
    discovery_decision: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_scoring_decision: Mapped[str] = mapped_column(String(64), nullable=False)
    sitemap_policy_decision: Mapped[str] = mapped_column(String(64), nullable=False)
    highest_severity: Mapped[str | None] = mapped_column(String(24))
    issue_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    crawl_depth: Mapped[int | None] = mapped_column(Integer)
    inbound_link_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outbound_link_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    partial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    failure_code: Mapped[str | None] = mapped_column(String(128))
    business_importance: Mapped[str] = mapped_column(String(24), nullable=False)
    evidence_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("audit_id", "sequence", name="uq_site_audit_url_sequence"),
        UniqueConstraint("audit_id", "normalized_url_identity", name="uq_site_audit_url_identity"),
        CheckConstraint("sequence >= 0", name="ck_site_audit_url_sequence"),
        CheckConstraint(
            "length(normalized_url_identity) = 64", name="ck_site_audit_url_identity_hash"
        ),
        CheckConstraint(
            "http_status IS NULL OR (http_status >= 100 AND http_status <= 599)",
            name="ck_site_audit_url_http_status",
        ),
        Index("ix_site_audit_urls_order", "audit_id", "sequence", "url_id"),
        Index("ix_site_audit_urls_status", "audit_id", "http_status", "sequence"),
        Index("ix_site_audit_urls_sitemap", "audit_id", "recommended_sitemap_state", "sequence"),
        Index("ix_site_audit_urls_severity", "audit_id", "highest_severity", "sequence"),
    )


class SiteAuditDiscoverySourceModel(Base):
    __tablename__ = "site_audit_url_discovery_sources"

    discovery_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    url_id: Mapped[str] = mapped_column(
        ForeignKey("site_audit_urls.url_id", ondelete="CASCADE"), nullable=False
    )
    audit_id: Mapped[str] = mapped_column(
        ForeignKey("site_audits.audit_id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_artifact_id: Mapped[str | None] = mapped_column(String(64))
    source_evidence_id: Mapped[str | None] = mapped_column(String(64))
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    original_observed_url: Mapped[str] = mapped_column(Text, nullable=False)
    relationship_json: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_key: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("url_id", "evidence_key", name="uq_site_audit_discovery_evidence"),
        UniqueConstraint("audit_id", "sequence", name="uq_site_audit_discovery_sequence"),
        Index("ix_site_audit_discoveries_url", "url_id", "sequence"),
    )


class SiteAuditPopulationModel(Base):
    __tablename__ = "site_audit_url_populations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    audit_id: Mapped[str] = mapped_column(
        ForeignKey("site_audits.audit_id", ondelete="CASCADE"), nullable=False
    )
    url_id: Mapped[str] = mapped_column(
        ForeignKey("site_audit_urls.url_id", ondelete="CASCADE"), nullable=False
    )
    population: Mapped[str] = mapped_column(String(40), nullable=False)
    decision_state: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(128))
    evidence_id: Mapped[str | None] = mapped_column(String(64))
    definition_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("url_id", "population", name="uq_site_audit_url_population"),
        CheckConstraint(
            "population in ('discovered','enqueued','fetched','parsed_html','indexable',"
            "'canonical','metadata_scoring_eligible','sitemap_eligible','resource',"
            "'excluded','partial','failed','indeterminate')",
            name="ck_site_audit_population",
        ),
        Index("ix_site_audit_populations", "audit_id", "population", "url_id"),
    )


class SiteAuditRuleMatchModel(Base):
    __tablename__ = "site_audit_rule_matches"

    match_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audit_id: Mapped[str] = mapped_column(
        ForeignKey("site_audits.audit_id", ondelete="CASCADE"), nullable=False
    )
    url_id: Mapped[str] = mapped_column(
        ForeignKey("site_audit_urls.url_id", ondelete="CASCADE"), nullable=False
    )
    snapshot_rule_id: Mapped[str] = mapped_column(
        ForeignKey("site_audit_rule_snapshots.snapshot_rule_id", ondelete="CASCADE"), nullable=False
    )
    decision_layer: Mapped[str] = mapped_column(String(32), nullable=False)
    primary_rule: Mapped[bool] = mapped_column(Boolean, nullable=False)
    contributed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    disabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    overridden: Mapped[bool] = mapped_column(Boolean, nullable=False)
    specificity: Mapped[int] = mapped_column(Integer, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    precedence_key: Mapped[str] = mapped_column(String(200), nullable=False)
    conflict_code: Mapped[str | None] = mapped_column(String(128))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    matched_original_url: Mapped[str] = mapped_column(Text, nullable=False)
    matched_normalized_url: Mapped[str] = mapped_column(Text, nullable=False)
    matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "url_id", "snapshot_rule_id", "decision_layer", name="uq_site_audit_rule_match"
        ),
        Index(
            "ix_site_audit_rule_matches_order",
            "audit_id",
            "url_id",
            "decision_layer",
            "precedence_key",
            "match_id",
        ),
    )


class SiteAuditFindingModel(Base):
    __tablename__ = "site_audit_findings"

    finding_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audit_id: Mapped[str] = mapped_column(
        ForeignKey("site_audits.audit_id", ondelete="CASCADE"), nullable=False
    )
    url_id: Mapped[str | None] = mapped_column(
        ForeignKey("site_audit_urls.url_id", ondelete="CASCADE")
    )
    module: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    severity: Mapped[str] = mapped_column(String(24), nullable=False)
    determinacy: Mapped[str] = mapped_column(String(24), nullable=False)
    confidence: Mapped[str] = mapped_column(String(24), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_reference: Mapped[str | None] = mapped_column(String(128))
    sitemap_impact: Mapped[bool] = mapped_column(Boolean, nullable=False)
    metadata_impact: Mapped[bool] = mapped_column(Boolean, nullable=False)
    indexability_impact: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    projection_version: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        Index("ix_site_audit_findings", "audit_id", "module", "severity", "finding_id"),
    )


class SiteAuditIssueGroupModel(Base):
    __tablename__ = "site_audit_issue_groups"

    group_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audit_id: Mapped[str] = mapped_column(
        ForeignKey("site_audits.audit_id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    remediation_key: Mapped[str] = mapped_column(String(128), nullable=False)
    applicable_population: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(24), nullable=False)
    affected_url_count: Mapped[int] = mapped_column(Integer, nullable=False)
    highest_business_importance: Mapped[str] = mapped_column(String(24), nullable=False)
    pattern_state: Mapped[str] = mapped_column(String(32), nullable=False)
    sitemap_impact: Mapped[bool] = mapped_column(Boolean, nullable=False)
    metadata_impact: Mapped[bool] = mapped_column(Boolean, nullable=False)
    indexability_impact: Mapped[bool] = mapped_column(Boolean, nullable=False)
    internal_link_impact: Mapped[bool] = mapped_column(Boolean, nullable=False)
    confidence: Mapped[str] = mapped_column(String(24), nullable=False)
    determinacy: Mapped[str] = mapped_column(String(24), nullable=False)
    priority_band: Mapped[str] = mapped_column(String(24), nullable=False)
    priority_key: Mapped[str] = mapped_column(String(256), nullable=False)
    priority_explanation: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_action: Mapped[str] = mapped_column(Text, nullable=False)
    sample_urls_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    projection_version: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "audit_id",
            "projection_version",
            "code",
            "remediation_key",
            "applicable_population",
            name="uq_site_audit_issue_group_key",
        ),
        Index("ix_site_audit_issue_groups_priority", "audit_id", "priority_key", "group_id"),
    )


class SiteAuditIssueMembershipModel(Base):
    __tablename__ = "site_audit_issue_group_memberships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[str] = mapped_column(
        ForeignKey("site_audit_issue_groups.group_id", ondelete="CASCADE"), nullable=False
    )
    finding_id: Mapped[str] = mapped_column(
        ForeignKey("site_audit_findings.finding_id", ondelete="CASCADE"), nullable=False
    )
    url_id: Mapped[str | None] = mapped_column(
        ForeignKey("site_audit_urls.url_id", ondelete="CASCADE")
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    membership_reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("group_id", "finding_id", name="uq_site_audit_issue_membership"),
        UniqueConstraint("group_id", "sequence", name="uq_site_audit_issue_membership_sequence"),
        Index("ix_site_audit_memberships_order", "group_id", "sequence", "id"),
    )


class SiteAuditModuleStatusModel(Base):
    __tablename__ = "site_audit_module_statuses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    audit_id: Mapped[str] = mapped_column(
        ForeignKey("site_audits.audit_id", ondelete="CASCADE"), nullable=False
    )
    module: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_source: Mapped[str] = mapped_column(String(32), nullable=False)
    specialist_audit_id: Mapped[str | None] = mapped_column(String(64))
    lifecycle: Mapped[str] = mapped_column(String(32), nullable=False)
    completeness: Mapped[str] = mapped_column(String(32), nullable=False)
    partial: Mapped[bool] = mapped_column(Boolean, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(128))
    failure_explanation: Mapped[str | None] = mapped_column(Text)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False)
    artifact_count: Mapped[int] = mapped_column(Integer, nullable=False)
    projection_version: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("audit_id", "module", name="uq_site_audit_module_status"),
        CheckConstraint(
            "completeness in ('complete','partial','unavailable','failed','stale','not_enabled')",
            name="ck_site_audit_module_completeness",
        ),
        Index("ix_site_audit_module_statuses", "audit_id", "module"),
    )


class SiteAuditSummaryModel(Base):
    __tablename__ = "site_audit_summary_projections"

    audit_id: Mapped[str] = mapped_column(
        ForeignKey("site_audits.audit_id", ondelete="CASCADE"), primary_key=True
    )
    urls_discovered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    urls_enqueued: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    urls_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    html_urls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    indexable_urls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    canonical_urls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_scoring_eligible_urls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sitemap_eligible_urls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    urls_excluded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    partial_urls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_urls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    indeterminate_urls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    critical_issue_groups: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    high_issue_groups: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    medium_issue_groups: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    low_issue_groups: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unassigned_issue_groups: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recommendation_include: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recommendation_exclude: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recommendation_review: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recommendation_indeterminate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    image_summary_json: Mapped[str] = mapped_column(Text, nullable=False)
    structured_data_summary_json: Mapped[str] = mapped_column(Text, nullable=False)
    module_counts_json: Mapped[str] = mapped_column(Text, nullable=False)
    projection_version: Mapped[str] = mapped_column(String(64), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (CheckConstraint("revision > 0", name="ck_site_audit_summary_revision"),)


class SiteAuditArtifactAssociationModel(Base):
    __tablename__ = "site_audit_artifact_associations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    audit_id: Mapped[str] = mapped_column(
        ForeignKey("site_audits.audit_id", ondelete="CASCADE"), nullable=False
    )
    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_records.artifact_id", ondelete="RESTRICT"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    completeness: Mapped[str] = mapped_column(String(32), nullable=False)
    row_count: Mapped[int | None] = mapped_column(Integer)
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "audit_id", "artifact_id", "purpose", name="uq_site_audit_artifact_association"
        ),
        Index("ix_site_audit_artifacts", "audit_id", "purpose", "id"),
    )


class SiteAuditOrchestrationModel(Base):
    __tablename__ = "site_audit_orchestrations"

    audit_id: Mapped[str] = mapped_column(
        ForeignKey("site_audits.audit_id", ondelete="CASCADE"), primary_key=True
    )
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("site_audit_snapshots.snapshot_id", ondelete="CASCADE"), nullable=False
    )
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    current_stage: Mapped[str | None] = mapped_column(String(64))
    crawl_job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.job_id", ondelete="SET NULL"))
    crawl_run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.run_id", ondelete="SET NULL"))
    cancellation_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recovery_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    projection_version: Mapped[str] = mapped_column(String(64), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(128))
    failure_explanation: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint("snapshot_id", name="uq_site_audit_orchestration_snapshot"),
        CheckConstraint("retry_count >= 0", name="ck_site_audit_orchestration_retries"),
        CheckConstraint("recovery_count >= 0", name="ck_site_audit_orchestration_recoveries"),
        CheckConstraint("revision > 0", name="ck_site_audit_orchestration_revision"),
        CheckConstraint(
            "state in ('queued','running','cancel_requested','cancelled','completed',"
            "'completed_with_warnings','partially_completed','failed','recovery_required')",
            name="ck_site_audit_orchestration_state",
        ),
        Index("ix_site_audit_orchestration_state", "state", "updated_at", "audit_id"),
        Index("ix_site_audit_orchestration_job", "crawl_job_id", "crawl_run_id"),
    )


class SiteAuditOrchestrationStageModel(Base):
    __tablename__ = "site_audit_orchestration_stages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    audit_id: Mapped[str] = mapped_column(
        ForeignKey("site_audit_orchestrations.audit_id", ondelete="CASCADE"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    stable_order: Mapped[int] = mapped_column(Integer, nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    dependencies_json: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checkpoint: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    projected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(String(64))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(128))
    failure_explanation: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("audit_id", "stage", name="uq_site_audit_orchestration_stage"),
        UniqueConstraint("audit_id", "stable_order", name="uq_site_audit_stage_order"),
        CheckConstraint("attempt_count >= 0", name="ck_site_audit_stage_attempts"),
        CheckConstraint("checkpoint >= 0", name="ck_site_audit_stage_checkpoint"),
        CheckConstraint(
            "source_count >= 0 and projected_count >= 0", name="ck_site_audit_stage_counts"
        ),
        CheckConstraint(
            "state in ('pending','running','completed','partial','unavailable','failed',"
            "'cancelled','blocked')",
            name="ck_site_audit_stage_state",
        ),
        Index("ix_site_audit_stage_state", "audit_id", "state", "stable_order"),
        Index("ix_site_audit_stage_lease", "lease_expires_at", "state"),
    )


class SiteAuditSpecialistAssociationModel(Base):
    __tablename__ = "site_audit_specialist_associations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    audit_id: Mapped[str] = mapped_column(
        ForeignKey("site_audit_orchestrations.audit_id", ondelete="CASCADE"), nullable=False
    )
    module: Mapped[str] = mapped_column(String(64), nullable=False)
    specialist_audit_id: Mapped[str | None] = mapped_column(String(64))
    source_run_id: Mapped[str | None] = mapped_column(String(64))
    execution_source: Mapped[str] = mapped_column(String(32), nullable=False)
    eligibility_state: Mapped[str] = mapped_column(String(32), nullable=False)
    eligibility_reason: Mapped[str] = mapped_column(String(128), nullable=False)
    freshness_state: Mapped[str] = mapped_column(String(32), nullable=False)
    partial: Mapped[bool] = mapped_column(Boolean, nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    associated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("audit_id", "module", name="uq_site_audit_specialist_module"),
        CheckConstraint("evidence_count >= 0", name="ck_site_audit_specialist_evidence"),
        Index("ix_site_audit_specialist_source", "specialist_audit_id", "source_run_id"),
    )
