"""Domain rules for the bounded Combined Site Audit persistence foundation."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum

SITE_AUDIT_PERSISTENCE_VERSION = "site-audit-persistence-v1"
SITE_AUDIT_POPULATION_VERSION = "site-audit-populations-v1"
SITE_AUDIT_PRIORITY_VERSION = "site-audit-priority-v1"
SITE_AUDIT_PROJECTION_VERSION = "site-audit-summary-v1"
MAX_SITE_AUDIT_URLS = 100_000
MAX_SITE_AUDIT_PAGE_SIZE = 500
SITE_AUDIT_PAGE_SIZES = frozenset({50, 100, 500})


class SiteAuditPersistenceError(RuntimeError):
    """Safe stable failure raised by the CSA persistence boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class AuditLifecycle(StrEnum):
    DRAFT = "draft"
    VALIDATING = "validating"
    VALIDATION_FAILED = "validation_failed"
    VALIDATED = "validated"
    PREFLIGHTING = "preflighting"
    PREFLIGHT_FAILED = "preflight_failed"
    READY = "ready"
    QUEUED = "queued"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    RECOVERY_REQUIRED = "recovery_required"
    ARCHIVED = "archived"


EDITABLE_LIFECYCLES = frozenset(
    {
        AuditLifecycle.DRAFT,
        AuditLifecycle.VALIDATION_FAILED,
        AuditLifecycle.VALIDATED,
        AuditLifecycle.PREFLIGHT_FAILED,
        AuditLifecycle.READY,
    }
)
TERMINAL_LIFECYCLES = frozenset(
    {
        AuditLifecycle.CANCELLED,
        AuditLifecycle.COMPLETED,
        AuditLifecycle.COMPLETED_WITH_WARNINGS,
        AuditLifecycle.PARTIALLY_COMPLETED,
        AuditLifecycle.FAILED,
        AuditLifecycle.ARCHIVED,
    }
)

_TRANSITIONS: dict[AuditLifecycle, frozenset[AuditLifecycle]] = {
    AuditLifecycle.DRAFT: frozenset({AuditLifecycle.VALIDATING, AuditLifecycle.ARCHIVED}),
    AuditLifecycle.VALIDATING: frozenset(
        {AuditLifecycle.VALIDATION_FAILED, AuditLifecycle.VALIDATED}
    ),
    AuditLifecycle.VALIDATION_FAILED: frozenset(
        {AuditLifecycle.DRAFT, AuditLifecycle.VALIDATING, AuditLifecycle.ARCHIVED}
    ),
    AuditLifecycle.VALIDATED: frozenset(
        {AuditLifecycle.DRAFT, AuditLifecycle.PREFLIGHTING, AuditLifecycle.ARCHIVED}
    ),
    AuditLifecycle.PREFLIGHTING: frozenset({AuditLifecycle.PREFLIGHT_FAILED, AuditLifecycle.READY}),
    AuditLifecycle.PREFLIGHT_FAILED: frozenset(
        {AuditLifecycle.DRAFT, AuditLifecycle.VALIDATING, AuditLifecycle.ARCHIVED}
    ),
    AuditLifecycle.READY: frozenset(
        {AuditLifecycle.DRAFT, AuditLifecycle.QUEUED, AuditLifecycle.ARCHIVED}
    ),
    AuditLifecycle.QUEUED: frozenset(
        {AuditLifecycle.RUNNING, AuditLifecycle.CANCEL_REQUESTED, AuditLifecycle.FAILED}
    ),
    AuditLifecycle.RUNNING: frozenset(
        {
            AuditLifecycle.CANCEL_REQUESTED,
            AuditLifecycle.COMPLETED,
            AuditLifecycle.COMPLETED_WITH_WARNINGS,
            AuditLifecycle.PARTIALLY_COMPLETED,
            AuditLifecycle.FAILED,
            AuditLifecycle.RECOVERY_REQUIRED,
        }
    ),
    AuditLifecycle.CANCEL_REQUESTED: frozenset(
        {
            AuditLifecycle.CANCELLED,
            AuditLifecycle.COMPLETED,
            AuditLifecycle.COMPLETED_WITH_WARNINGS,
            AuditLifecycle.PARTIALLY_COMPLETED,
            AuditLifecycle.FAILED,
            AuditLifecycle.RECOVERY_REQUIRED,
        }
    ),
    AuditLifecycle.RECOVERY_REQUIRED: frozenset({AuditLifecycle.QUEUED, AuditLifecycle.FAILED}),
    AuditLifecycle.CANCELLED: frozenset({AuditLifecycle.ARCHIVED}),
    AuditLifecycle.COMPLETED: frozenset({AuditLifecycle.ARCHIVED}),
    AuditLifecycle.COMPLETED_WITH_WARNINGS: frozenset({AuditLifecycle.ARCHIVED}),
    AuditLifecycle.PARTIALLY_COMPLETED: frozenset({AuditLifecycle.ARCHIVED}),
    AuditLifecycle.FAILED: frozenset({AuditLifecycle.ARCHIVED}),
    AuditLifecycle.ARCHIVED: frozenset(),
}


class Population(StrEnum):
    DISCOVERED = "discovered"
    ENQUEUED = "enqueued"
    FETCHED = "fetched"
    PARSED_HTML = "parsed_html"
    INDEXABLE = "indexable"
    CANONICAL = "canonical"
    METADATA_SCORING_ELIGIBLE = "metadata_scoring_eligible"
    SITEMAP_ELIGIBLE = "sitemap_eligible"
    RESOURCE = "resource"
    EXCLUDED = "excluded"
    PARTIAL = "partial"
    FAILED = "failed"
    INDETERMINATE = "indeterminate"


class ModuleCompleteness(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    STALE = "stale"
    NOT_ENABLED = "not_enabled"


def validate_transition(current: AuditLifecycle, target: AuditLifecycle) -> None:
    if target not in _TRANSITIONS[current]:
        raise SiteAuditPersistenceError(
            "site_audit_invalid_lifecycle_transition",
            f"A Site Audit cannot transition from {current.value} to {target.value}.",
        )


def require_editable(lifecycle: AuditLifecycle) -> None:
    if lifecycle not in EDITABLE_LIFECYCLES:
        raise SiteAuditPersistenceError(
            "site_audit_draft_not_editable", "This Site Audit draft is no longer editable."
        )


def validate_page_size(page_size: int) -> None:
    if page_size not in SITE_AUDIT_PAGE_SIZES:
        raise SiteAuditPersistenceError(
            "site_audit_invalid_pagination",
            "Page size must be 50, 100, or 500.",
        )


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def snapshot_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def normalized_url_identity(normalized_url: str) -> str:
    return hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()
