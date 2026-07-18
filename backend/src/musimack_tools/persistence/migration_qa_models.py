"""Normalized SQLAlchemy models for website migration QA."""

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


class MigrationQaProjectModel(Base):
    __tablename__ = "migration_qa_projects"
    project_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.job_id", ondelete="CASCADE"))
    destination_run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id", ondelete="CASCADE"))
    source_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.run_id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(256))
    mode: Mapped[str] = mapped_column(String(32))
    migration_type: Mapped[str] = mapped_column(String(64))
    source_origin: Mapped[str | None] = mapped_column(Text)
    destination_origin: Mapped[str] = mapped_column(Text)
    configuration_json: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(64))
    readiness: Mapped[str] = mapped_column(String(64))
    total_sources: Mapped[int] = mapped_column(Integer, default=0)
    total_mappings: Mapped[int] = mapped_column(Integer, default=0)
    total_findings: Mapped[int] = mapped_column(Integer, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retention_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(128))
    __table_args__ = (
        CheckConstraint("mode IN ('pre_launch','post_launch')", name="ck_migration_project_mode"),
        CheckConstraint(
            "state IN ('draft','ready','running','completed','completed_with_warnings','failed','cancelled')",
            name="ck_migration_project_state",
        ),
    )


class _ProjectChild:
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("migration_qa_projects.project_id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MigrationSourceRowModel(_ProjectChild, Base):
    __tablename__ = "migration_source_rows"
    sequence: Mapped[int] = mapped_column(Integer)
    raw_url: Mapped[str] = mapped_column(Text)
    normalized_url: Mapped[str | None] = mapped_column(Text)
    comparison_url: Mapped[str | None] = mapped_column(Text)
    proposed_destination_url: Mapped[str | None] = mapped_column(Text)
    source_kind: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(32))
    diagnostics_json: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("project_id", "sequence", name="uq_migration_source_sequence"),
    )


class MigrationRedirectMapRowModel(_ProjectChild, Base):
    __tablename__ = "migration_redirect_map_rows"
    sequence: Mapped[int] = mapped_column(Integer)
    raw_source_url: Mapped[str] = mapped_column(Text)
    raw_destination_url: Mapped[str] = mapped_column(Text)
    normalized_source_url: Mapped[str | None] = mapped_column(Text)
    normalized_destination_url: Mapped[str | None] = mapped_column(Text)
    expected_status: Mapped[int | None] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(32))
    diagnostics_json: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("project_id", "sequence", name="uq_migration_redirect_sequence"),
    )


class MigrationUrlMappingModel(_ProjectChild, Base):
    __tablename__ = "migration_url_mappings"
    source_row_id: Mapped[str] = mapped_column(
        ForeignKey("migration_source_rows.id", ondelete="CASCADE")
    )
    source_url: Mapped[str] = mapped_column(Text)
    destination_url: Mapped[str | None] = mapped_column(Text)
    mapping_method: Mapped[str] = mapped_column(String(64))
    cardinality: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[str] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(32))
    bounded_evidence_json: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        Index("ix_migration_mapping_project_state", "project_id", "state", "id"),
        Index("ix_migration_mapping_project_method", "project_id", "mapping_method", "id"),
    )


class MigrationRedirectObservationModel(_ProjectChild, Base):
    __tablename__ = "migration_redirect_observations"
    mapping_id: Mapped[str] = mapped_column(
        ForeignKey("migration_url_mappings.id", ondelete="CASCADE")
    )
    planned_destination_url: Mapped[str | None] = mapped_column(Text)
    observed_final_url: Mapped[str | None] = mapped_column(Text)
    observed_status: Mapped[int | None] = mapped_column(Integer)
    chain_json: Mapped[str] = mapped_column(Text)
    chain_identity: Mapped[str | None] = mapped_column(String(64))
    loop_identity: Mapped[str | None] = mapped_column(String(64))
    hop_count: Mapped[int] = mapped_column(Integer)
    truncated: Mapped[bool] = mapped_column(Boolean)
    evidence_source: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(32))
    evidence_json: Mapped[str] = mapped_column(Text)


class MigrationPageComparisonModel(_ProjectChild, Base):
    __tablename__ = "migration_page_comparisons"
    mapping_id: Mapped[str] = mapped_column(
        ForeignKey("migration_url_mappings.id", ondelete="CASCADE")
    )
    source_url: Mapped[str] = mapped_column(Text)
    destination_url: Mapped[str | None] = mapped_column(Text)
    status_state: Mapped[str] = mapped_column(String(32))
    metadata_state: Mapped[str] = mapped_column(String(32))
    content_state: Mapped[str] = mapped_column(String(32))
    canonical_state: Mapped[str] = mapped_column(String(32))
    indexability_state: Mapped[str] = mapped_column(String(32))
    evidence_json: Mapped[str] = mapped_column(Text)
    similarity_score: Mapped[str | None] = mapped_column(String(32))
    comparison_basis_json: Mapped[str] = mapped_column(Text)


class MigrationFindingModel(Base):
    __tablename__ = "migration_findings"
    stable_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("migration_qa_projects.project_id", ondelete="CASCADE")
    )
    mapping_id: Mapped[str | None] = mapped_column(
        ForeignKey("migration_url_mappings.id", ondelete="CASCADE")
    )
    source_url: Mapped[str | None] = mapped_column(Text)
    destination_url: Mapped[str | None] = mapped_column(Text)
    source_evidence_ids_json: Mapped[str] = mapped_column(Text)
    destination_evidence_ids_json: Mapped[str] = mapped_column(Text)
    code: Mapped[str] = mapped_column(String(128))
    category: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[str] = mapped_column(String(32))
    requires_human_review: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str] = mapped_column(Text)
    bounded_evidence_json: Mapped[str] = mapped_column(Text)
    occurrence_count: Mapped[int] = mapped_column(Integer)
    affected_page_count: Mapped[int] = mapped_column(Integer)
    sequence: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint(
            "confidence IN ('high','medium','low','indeterminate')",
            name="ck_migration_finding_confidence",
        ),
        UniqueConstraint("project_id", "sequence", name="uq_migration_finding_sequence"),
        Index("ix_migration_finding_project_mapping", "project_id", "mapping_id", "sequence"),
        Index("ix_migration_finding_project_code", "project_id", "code", "sequence"),
        Index("ix_migration_finding_project_category", "project_id", "category", "sequence"),
        Index("ix_migration_finding_project_severity", "project_id", "severity", "sequence"),
        Index("ix_migration_finding_project_confidence", "project_id", "confidence", "sequence"),
    )


class MigrationRecommendationModel(Base):
    __tablename__ = "migration_recommendations"
    stable_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("migration_qa_projects.project_id", ondelete="CASCADE")
    )
    action: Mapped[str] = mapped_column(String(128))
    severity: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[str] = mapped_column(String(32))
    requires_human_review: Mapped[bool] = mapped_column(Boolean)
    scope: Mapped[str] = mapped_column(String(64))
    source_url: Mapped[str | None] = mapped_column(Text)
    destination_url: Mapped[str | None] = mapped_column(Text)
    occurrence_count: Mapped[int] = mapped_column(Integer)
    affected_page_count: Mapped[int] = mapped_column(Integer)
    supporting_finding_ids_json: Mapped[str] = mapped_column(Text)
    supporting_evidence_json: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    sequence: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("project_id", "sequence", name="uq_migration_recommendation_sequence"),
        Index(
            "ix_migration_recommendation_project_action",
            "project_id",
            "action",
            "sequence",
        ),
        Index(
            "ix_migration_recommendation_project_filter",
            "project_id",
            "severity",
            "confidence",
            "sequence",
        ),
    )


class MigrationSitewideSummaryModel(_ProjectChild, Base):
    __tablename__ = "migration_sitewide_summaries"
    category: Mapped[str] = mapped_column(String(64))
    metric_name: Mapped[str] = mapped_column(String(128))
    numerator: Mapped[int] = mapped_column(Integer)
    denominator: Mapped[int] = mapped_column(Integer)
    ratio: Mapped[str] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(32))
    evidence_json: Mapped[str] = mapped_column(Text)


class MigrationExportModel(_ProjectChild, Base):
    __tablename__ = "migration_exports"
    export_format: Mapped[str] = mapped_column(String(64))
    media_type: Mapped[str] = mapped_column(String(128))
    filename: Mapped[str] = mapped_column(String(512))
    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_records.artifact_id", ondelete="CASCADE")
    )
    row_count: Mapped[int] = mapped_column(Integer)
    truncated: Mapped[bool] = mapped_column(Boolean)
    state: Mapped[str] = mapped_column(String(32))
    __table_args__ = (
        UniqueConstraint("project_id", "export_format", name="uq_migration_project_export"),
    )


class MigrationEventModel(Base):
    __tablename__ = "migration_events"
    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("migration_qa_projects.project_id", ondelete="CASCADE"), index=True
    )
    state: Mapped[str] = mapped_column(String(64))
    affected_count: Mapped[int] = mapped_column(Integer)
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("ix_migration_event_project_order", "project_id", "event_id"),)
