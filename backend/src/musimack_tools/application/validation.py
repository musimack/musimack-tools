"""Deterministic validation helpers for raw application requests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from musimack_tools.application.profiles import APPLICATION_HARD_MAXIMA
from musimack_tools.domain.application import (
    ApplicationCrawlLimits,
    CrawlLimitOverrides,
    ValidationIssue,
    ValidationIssueCode,
    ValidationSeverity,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path


def effective_limits(
    base: ApplicationCrawlLimits,
    overrides: CrawlLimitOverrides,
    maxima: ApplicationCrawlLimits = APPLICATION_HARD_MAXIMA,
) -> tuple[ApplicationCrawlLimits | None, tuple[ValidationIssue, ...]]:
    """Apply explicit overrides only when every value is within hard bounds."""
    fields = (
        ("maximum_urls", 1, maxima.maximum_urls),
        ("maximum_depth", 0, maxima.maximum_depth),
        ("maximum_duration_seconds", 0.001, maxima.maximum_duration_seconds),
        ("maximum_accepted_bytes", 1, maxima.maximum_accepted_bytes),
        ("maximum_concurrency", 1, maxima.maximum_concurrency),
        ("maximum_queue_size", 1, maxima.maximum_queue_size),
        (
            "minimum_request_delay_seconds",
            maxima.minimum_request_delay_seconds,
            None,
        ),
        ("maximum_redirect_hops", 0, maxima.maximum_redirect_hops),
        ("maximum_response_bytes", 1, maxima.maximum_response_bytes),
    )
    issues: list[ValidationIssue] = []
    values: dict[str, int | float] = {}
    for name, minimum, maximum in fields:
        supplied = getattr(overrides, name)
        value = getattr(base, name) if supplied is None else supplied
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            issues.append(_override_issue(ValidationIssueCode.INVALID_OVERRIDE, name, supplied))
            continue
        if value < minimum:
            issues.append(
                _override_issue(ValidationIssueCode.OVERRIDE_BELOW_MINIMUM, name, supplied)
            )
        elif maximum is not None and value > maximum:
            issues.append(
                _override_issue(ValidationIssueCode.OVERRIDE_ABOVE_MAXIMUM, name, supplied)
            )
        values[name] = value
    if issues:
        return None, tuple(issues)
    return ApplicationCrawlLimits(**values), ()  # type: ignore[arg-type]


def validate_output_root(root: Path | None, field: str) -> tuple[ValidationIssue, ...]:
    if root is None:
        code = (
            ValidationIssueCode.PUBLICATION_ROOT_MISSING
            if field == "publication_root"
            else ValidationIssueCode.SUMMARY_ROOT_MISSING
        )
        return (ValidationIssue(ValidationSeverity.ERROR, code, f"{field} is required", field),)
    if not root.is_absolute() or any(part.casefold() == ".git" for part in root.parts):
        return (
            ValidationIssue(
                ValidationSeverity.ERROR,
                ValidationIssueCode.UNSAFE_OUTPUT_ROOT,
                f"{field} must be an absolute non-.git path",
                field,
            ),
        )
    return ()


def ordered_issues(issues: Iterable[ValidationIssue]) -> tuple[ValidationIssue, ...]:
    values = tuple(issues)
    return tuple(
        item
        for severity in (
            ValidationSeverity.ERROR,
            ValidationSeverity.WARNING,
            ValidationSeverity.INFO,
        )
        for item in values
        if item.severity is severity
    )


def _override_issue(
    code: ValidationIssueCode,
    field: str,
    supplied: float | None,
) -> ValidationIssue:
    return ValidationIssue(
        ValidationSeverity.ERROR,
        code,
        f"{field} is outside the accepted application boundary",
        field,
        supplied,
    )
