"""CSA-03 lifecycle, immutability helpers, identity, and bounds."""

from __future__ import annotations

import pytest

from musimack_tools.domain.site_audit_persistence import (
    AuditLifecycle,
    SiteAuditPersistenceError,
    canonical_json,
    normalized_url_identity,
    require_editable,
    snapshot_hash,
    validate_page_size,
    validate_transition,
)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (AuditLifecycle.DRAFT, AuditLifecycle.VALIDATING),
        (AuditLifecycle.VALIDATING, AuditLifecycle.VALIDATED),
        (AuditLifecycle.VALIDATED, AuditLifecycle.PREFLIGHTING),
        (AuditLifecycle.PREFLIGHTING, AuditLifecycle.READY),
        (AuditLifecycle.READY, AuditLifecycle.QUEUED),
        (AuditLifecycle.QUEUED, AuditLifecycle.RUNNING),
        (AuditLifecycle.RUNNING, AuditLifecycle.RECOVERY_REQUIRED),
        (AuditLifecycle.RECOVERY_REQUIRED, AuditLifecycle.QUEUED),
        (AuditLifecycle.RUNNING, AuditLifecycle.PARTIALLY_COMPLETED),
        (AuditLifecycle.CANCEL_REQUESTED, AuditLifecycle.CANCELLED),
        (AuditLifecycle.COMPLETED, AuditLifecycle.ARCHIVED),
    ],
)
def test_legal_lifecycle_transitions(current: AuditLifecycle, target: AuditLifecycle) -> None:
    validate_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (AuditLifecycle.DRAFT, AuditLifecycle.COMPLETED),
        (AuditLifecycle.COMPLETED, AuditLifecycle.DRAFT),
        (AuditLifecycle.FAILED, AuditLifecycle.RUNNING),
        (AuditLifecycle.CANCELLED, AuditLifecycle.COMPLETED),
        (AuditLifecycle.ARCHIVED, AuditLifecycle.DRAFT),
    ],
)
def test_illegal_lifecycle_transitions_have_stable_error(
    current: AuditLifecycle, target: AuditLifecycle
) -> None:
    with pytest.raises(SiteAuditPersistenceError) as captured:
        validate_transition(current, target)
    assert captured.value.code == "site_audit_invalid_lifecycle_transition"


def test_draft_editability_is_not_inferred_from_terminal_success() -> None:
    require_editable(AuditLifecycle.VALIDATION_FAILED)
    with pytest.raises(SiteAuditPersistenceError) as captured:
        require_editable(AuditLifecycle.COMPLETED_WITH_WARNINGS)
    assert captured.value.code == "site_audit_draft_not_editable"


def test_snapshot_serialization_and_url_identity_are_deterministic() -> None:
    first = {"modules": ["metadata"], "limits": {"maximum_urls": 100}}
    second = {"limits": {"maximum_urls": 100}, "modules": ["metadata"]}
    assert canonical_json(first) == canonical_json(second)
    assert snapshot_hash(first) == snapshot_hash(second)
    assert normalized_url_identity("https://example.com/") == normalized_url_identity(
        "https://example.com/"
    )
    assert normalized_url_identity("https://example.com/") != normalized_url_identity(
        "https://example.com/a"
    )


@pytest.mark.parametrize("value", [50, 100, 500])
def test_accepted_page_sizes(value: int) -> None:
    validate_page_size(value)


@pytest.mark.parametrize("value", [0, 49, 501, 5_000])
def test_unbounded_or_unsupported_page_sizes_fail(value: int) -> None:
    with pytest.raises(SiteAuditPersistenceError) as captured:
        validate_page_size(value)
    assert captured.value.code == "site_audit_invalid_pagination"
