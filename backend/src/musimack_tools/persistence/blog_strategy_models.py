"""Additive SQLAlchemy models owned by Blog Strategy BS-01."""

# ruff: noqa: TC003 - SQLAlchemy resolves mapped datetime annotations at runtime.

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from musimack_tools.persistence.base import Base


class BlogStrategyProjectModel(Base):
    __tablename__ = "blog_strategy_projects"
    project_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    client_name: Mapped[str] = mapped_column(String(200), nullable=False)
    primary_website: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_origin: Mapped[str] = mapped_column(Text, nullable=False)
    primary_market: Mapped[str] = mapped_column(String(200), nullable=False)
    service_area_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    core_services_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    important_pages_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    compliance_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BlogStrategyPageModel(Base):
    __tablename__ = "blog_strategy_pages"
    __table_args__ = (UniqueConstraint("project_id", "normalized_url"),)
    page_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("blog_strategy_projects.project_id", ondelete="CASCADE"), index=True
    )
    original_url: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_reference: Mapped[str | None] = mapped_column(String(128))
    provenance_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    inclusion_state: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    meta_description: Mapped[str | None] = mapped_column(Text)
    h1: Mapped[str | None] = mapped_column(Text)
    publication_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    modified_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    author: Mapped[str | None] = mapped_column(String(200))
    http_status: Mapped[int | None] = mapped_column(Integer)
    indexability: Mapped[str | None] = mapped_column(String(40))
    word_count: Mapped[int | None] = mapped_column(Integer)
    primary_topic: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    secondary_topics_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    search_intent: Mapped[str] = mapped_column(String(40), nullable=False, default="unclassified")
    audience_question: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_role: Mapped[str] = mapped_column(String(40), nullable=False, default="unclassified")
    funnel_stage: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    geographic_intent: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    supported_page: Mapped[str] = mapped_column(Text, nullable=False, default="")
    supported_area: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    time_sensitivity: Mapped[str] = mapped_column(String(30), nullable=False, default="evergreen")
    claim_risk: Mapped[str] = mapped_column(String(40), nullable=False, default="none")
    classification_source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    human_reviewed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    family_id: Mapped[str | None] = mapped_column(
        ForeignKey("blog_strategy_topic_families.family_id", ondelete="SET NULL")
    )
    membership_role: Mapped[str] = mapped_column(String(20), nullable=False, default="unclassified")
    action: Mapped[str] = mapped_column(String(40), nullable=False, default="undecided")
    priority: Mapped[str] = mapped_column(String(30), nullable=False, default="later")
    destination_page: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approved_by: Mapped[str | None] = mapped_column(String(128))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BlogStrategyTopicFamilyModel(Base):
    __tablename__ = "blog_strategy_topic_families"
    __table_args__ = (UniqueConstraint("project_id", "name"),)
    family_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("blog_strategy_projects.project_id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    primary_guide_page_id: Mapped[str | None] = mapped_column(String(40))
    supported_page: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    merged_into_family_id: Mapped[str | None] = mapped_column(String(40))
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BlogStrategyOverlapModel(Base):
    __tablename__ = "blog_strategy_overlap_notes"
    overlap_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("blog_strategy_projects.project_id", ondelete="CASCADE"), index=True
    )
    page_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    concern_type: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    preferred_page_id: Mapped[str | None] = mapped_column(String(40))
    review_state: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    resolution_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BlogStrategyEventModel(Base):
    __tablename__ = "blog_strategy_events"
    event_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("blog_strategy_projects.project_id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(40))
    actor: Mapped[str | None] = mapped_column(String(128))
    details_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
