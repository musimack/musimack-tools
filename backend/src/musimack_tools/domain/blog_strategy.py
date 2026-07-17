"""BS-01 domain contracts for manual blog inventory and organization."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from urllib.parse import SplitResult, urlsplit, urlunsplit

BLOG_STRATEGY_VERSION = "blog-strategy-bs01-v1"


class ProjectStatus(StrEnum):
    DRAFT = "draft"
    INVENTORY_IN_PROGRESS = "inventory_in_progress"
    INVENTORY_READY = "inventory_ready"
    ORGANIZATION_IN_PROGRESS = "organization_in_progress"
    REVIEW_READY = "review_ready"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class InclusionState(StrEnum):
    INCLUDED = "included"
    EXCLUDED = "excluded"
    NEEDS_REVIEW = "needs_review"


class SourceType(StrEnum):
    MANUAL = "manual"
    SITEMAP = "sitemap"
    CRAWL = "crawl"
    IMPORT = "import"


class SearchIntent(StrEnum):
    LEARN_CONDITION = "learn_condition"
    UNDERSTAND_SYMPTOMS = "understand_symptoms"
    UNDERSTAND_CAUSES = "understand_causes"
    COMPARE_OPTIONS = "compare_options"
    PREPARE_FOR_APPOINTMENT = "prepare_for_appointment"
    DECIDE_TO_CONTACT = "decide_to_contact"
    FIND_LOCAL_PROVIDER = "find_local_provider"
    ANSWER_SPECIFIC_QUESTION = "answer_specific_question"
    COMMERCIAL_INVESTIGATION = "commercial_investigation"
    NAVIGATIONAL = "navigational"
    OTHER = "other"
    UNCLASSIFIED = "unclassified"


class ContentRole(StrEnum):
    PRIMARY_GUIDE = "primary_guide"
    SUPPORTING_ARTICLE = "supporting_article"
    FAQ = "faq"
    LOCAL_ARTICLE = "local_article"
    SEASONAL_ARTICLE = "seasonal_article"
    NEWS = "news"
    ANNOUNCEMENT = "announcement"
    CUSTOMER_EDUCATION = "customer_education"
    OUTDATED_OR_LOW_VALUE = "outdated_or_low_value"
    UNCLASSIFIED = "unclassified"


class ClaimRisk(StrEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    REQUIRES_PROFESSIONAL_REVIEW = "requires_professional_review"


class TopicFamilyStatus(StrEnum):
    ACTIVE = "active"
    MERGED = "merged"
    ARCHIVED = "archived"


class MembershipRole(StrEnum):
    PRIMARY = "primary"
    SUPPORTING = "supporting"
    FAQ = "faq"
    LOCAL = "local"
    SEASONAL = "seasonal"
    REFERENCE = "reference"
    UNCLASSIFIED = "unclassified"


class ConcernType(StrEnum):
    POSSIBLE_OVERLAP = "possible_overlap"
    POSSIBLE_DUPLICATE = "possible_duplicate"
    SAME_INTENT = "same_intent"
    SERVICE_PAGE_CONFLICT = "service_page_conflict"
    UNCLEAR_PAGE_ROLE = "unclear_page_role"
    MANUAL_REVIEW = "manual_review"


class ReviewState(StrEnum):
    OPEN = "open"
    DISMISSED = "dismissed"
    CONFIRMED = "confirmed"
    RESOLVED = "resolved"
    DEFERRED = "deferred"


class StrategyAction(StrEnum):
    PRESERVE = "preserve"
    REFRESH = "refresh"
    EXPAND = "expand"
    CONSOLIDATE = "consolidate"
    REPOSITION = "reposition"
    RECLASSIFY = "reclassify"
    REDIRECT_OR_REMOVE = "redirect_or_remove"
    CLAIM_REVIEW = "claim_review"
    DEFER = "defer"
    UNDECIDED = "undecided"


class Priority(StrEnum):
    PRIORITY_1 = "priority_1"
    PRIORITY_2 = "priority_2"
    PRIORITY_3 = "priority_3"
    LATER = "later"
    DO_NOT_PURSUE = "do_not_pursue"


_TRANSITIONS = {
    ProjectStatus.DRAFT: {ProjectStatus.INVENTORY_IN_PROGRESS, ProjectStatus.ARCHIVED},
    ProjectStatus.INVENTORY_IN_PROGRESS: {
        ProjectStatus.DRAFT,
        ProjectStatus.INVENTORY_READY,
        ProjectStatus.ARCHIVED,
    },
    ProjectStatus.INVENTORY_READY: {
        ProjectStatus.INVENTORY_IN_PROGRESS,
        ProjectStatus.ORGANIZATION_IN_PROGRESS,
        ProjectStatus.ARCHIVED,
    },
    ProjectStatus.ORGANIZATION_IN_PROGRESS: {
        ProjectStatus.INVENTORY_READY,
        ProjectStatus.REVIEW_READY,
        ProjectStatus.ARCHIVED,
    },
    ProjectStatus.REVIEW_READY: {
        ProjectStatus.ORGANIZATION_IN_PROGRESS,
        ProjectStatus.COMPLETED,
        ProjectStatus.ARCHIVED,
    },
    ProjectStatus.COMPLETED: {ProjectStatus.REVIEW_READY, ProjectStatus.ARCHIVED},
    ProjectStatus.ARCHIVED: set(),
}


def validate_project_transition(current: ProjectStatus, target: ProjectStatus) -> None:
    if current != target and target not in _TRANSITIONS[current]:
        raise ValueError("blog_strategy_invalid_status_transition")


def normalize_blog_url(value: str) -> str:
    """Return a stable HTTP(S) identity without fragments or default ports."""
    raw = value.strip()
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError:
        raise ValueError("blog_strategy_url_invalid") from None
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("blog_strategy_url_invalid")
    host = parsed.hostname.encode("idna").decode("ascii").casefold()
    if port is not None and port != (443 if parsed.scheme.casefold() == "https" else 80):
        host = f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit(SplitResult(parsed.scheme.casefold(), host, path, parsed.query, ""))


@dataclass(frozen=True, slots=True)
class EvidenceCandidate:
    source_reference: str
    url: str
    title: str | None = None
    canonical_url: str | None = None
    http_status: int | None = None
    indexability: str | None = None


@dataclass(frozen=True, slots=True)
class ImportReport:
    imported: int
    skipped: int
    conflicted: int
    page_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExportReadiness:
    ready: bool
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BlogStrategyProject:
    project_id: str
    client_name: str
    primary_website: str
    normalized_origin: str
    primary_market: str
    service_area_notes: str = ""
    core_services: tuple[str, ...] = ()
    important_pages: tuple[str, ...] = ()
    compliance_notes: str = ""
    status: ProjectStatus = ProjectStatus.DRAFT
    revision: int = 1
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class PageEvidenceProvider:
    """Narrow read-only boundary owned by shared sitemap/crawl evidence."""

    def preview(self, source_reference: str) -> tuple[EvidenceCandidate, ...]:
        raise NotImplementedError
