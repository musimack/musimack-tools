"""Typed contracts and deterministic policy for image and alt-text audits."""

# ruff: noqa: ANN401, PLR0911, PLR2004, TRY003

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

IMAGE_EVIDENCE_VERSION = "seo-toolkit-image-evidence-v1"
IMAGE_AUDIT_VERSION = "seo-toolkit-image-audit-v1"
IMAGE_POLICY_VERSION = "seo-toolkit-image-policy-v1"
IMAGE_EXPORT_VERSION = "seo-toolkit-image-export-v1"
IMAGE_API_VERSION = "seo-toolkit-image-api-v1"
AUDIT_ORDERING = "created_at_desc_audit_id_desc-v1"
RESOURCE_ORDERING = "resource_sequence_asc_resource_id_asc-v1"
OCCURRENCE_ORDERING = "occurrence_sequence_asc_analysis_id_asc-v1"
PAGE_ORDERING = "page_sequence_asc_page_summary_id_asc-v1"
GROUP_ORDERING = "group_sequence_asc_group_id_asc-v1"
FINDING_ORDERING = "finding_sequence_asc_finding_id_asc-v1"
RECOMMENDATION_ORDERING = "recommendation_sequence_asc_recommendation_id_asc-v1"


class ImageAuditLifecycle(StrEnum):
    ACCEPTED = "accepted"
    CLAIMING = "claiming"
    BUILDING_INVENTORY = "building_inventory"
    RESOLVING_RESOURCES = "resolving_resources"
    CLASSIFYING_ALT_TEXT = "classifying_alt_text"
    ANALYZING_REUSE = "analyzing_reuse"
    BUILDING_RECOMMENDATIONS = "building_recommendations"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_LIFECYCLES = frozenset(
    {
        ImageAuditLifecycle.COMPLETED,
        ImageAuditLifecycle.COMPLETED_WITH_WARNINGS,
        ImageAuditLifecycle.FAILED,
        ImageAuditLifecycle.CANCELLED,
    }
)


class ImageResourceState(StrEnum):
    VALID = "valid_image"
    BROKEN = "broken_image"
    REDIRECTING = "redirecting_image"
    UNVERIFIED = "unverified_image"
    EXTERNAL = "external_image"
    OUT_OF_SCOPE = "out_of_scope_image"
    DATA = "data_image"
    UNSUPPORTED = "unsupported_image_source"
    PLACEHOLDER = "placeholder_image"
    DECORATIVE = "decorative_image"


class AltTextState(StrEnum):
    PRESENT = "alt_present"
    MISSING = "alt_missing"
    EMPTY = "alt_empty"
    WHITESPACE = "alt_whitespace_only"
    GENERIC = "alt_generic"
    FILENAME = "alt_filename_like"
    URL = "alt_url_like"
    OVERLONG = "alt_overlong"
    DUPLICATE_PAGE = "alt_duplicate_on_page"
    DUPLICATE_PAGES = "alt_duplicate_across_pages"
    SAME_MULTIPLE_IMAGES = "alt_same_for_multiple_images"
    LINK_EMPTY = "alt_image_link_empty"
    DECORATIVE = "alt_decorative_explicit"
    REVIEW = "alt_review"


class DimensionState(StrEnum):
    PRESENT = "dimensions_present"
    WIDTH_MISSING = "width_missing"
    HEIGHT_MISSING = "height_missing"
    BOTH_MISSING = "both_dimensions_missing"
    INVALID_WIDTH = "invalid_width"
    INVALID_HEIGHT = "invalid_height"
    ZERO = "zero_dimension"
    REVIEW = "dimension_review"


class LoadingState(StrEnum):
    LAZY = "lazy_loading_present"
    MISSING = "lazy_loading_missing"
    EAGER = "eager_loading_explicit"
    INVALID = "invalid_loading_value"
    DECODING_ASYNC = "decoding_async"
    FETCHPRIORITY_HIGH = "fetchpriority_high"
    REVIEW = "loading_review"


class ImageAction(StrEnum):
    ADD_ALT = "add_alt_text"
    REPLACE_ALT = "replace_alt_text"
    CONFIRM_DECORATIVE = "confirm_decorative"
    FIX_URL = "fix_image_url"
    UPDATE_DESTINATION = "update_image_destination"
    ADD_DIMENSIONS = "add_dimensions"
    REVIEW_LOADING = "review_loading_behavior"
    REPLACE_PLACEHOLDER = "replace_placeholder"
    REVIEW_DUPLICATE = "review_duplicate_usage"
    REVIEW = "review"
    NO_ACTION = "no_action"


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ImageExportFormat(StrEnum):
    INVENTORY_CSV = "image_inventory_csv"
    ALT_FINDINGS_CSV = "alt_findings_csv"
    BROKEN_REDIRECTING_CSV = "broken_redirecting_images_csv"
    DUPLICATE_GROUPS_CSV = "duplicate_groups_csv"
    PAGE_SUMMARIES_CSV = "page_summaries_csv"
    RECOMMENDATIONS_CSV = "recommendations_csv"
    JSON = "json"
    MARKDOWN = "markdown"


class ImageAuditErrorCode(StrEnum):
    RUN_NOT_FOUND = "image_audit_run_not_found"
    RUN_UNAUTHORIZED = "image_audit_run_unauthorized"
    PAGE_EVIDENCE_MISSING = "image_audit_page_evidence_missing"
    IMAGE_EVIDENCE_MISSING = "image_audit_image_evidence_missing"
    SCOPE_UNAVAILABLE = "image_audit_scope_unavailable"
    VERSION_UNSUPPORTED = "image_audit_evidence_version_unsupported"
    DUPLICATE = "image_audit_duplicate"
    EXECUTION_CONFLICT = "image_audit_execution_conflict"
    TERMINAL = "image_audit_already_terminal"
    RETAINED_EVIDENCE_UNAVAILABLE = "image_audit_retained_evidence_unavailable"
    INVALID_FILTER = "image_audit_invalid_filter"
    INVALID_CURSOR = "image_audit_invalid_cursor"
    CURSOR_FILTER_MISMATCH = "image_audit_cursor_filter_mismatch"
    EXPORT_CONFLICT = "image_audit_export_conflict"
    VERIFICATION_LIMIT = "image_audit_verification_limit_exceeded"
    UNSAFE_TARGET = "image_audit_unsafe_target_blocked"
    NOT_FOUND = "image_audit_not_found"


@dataclass(frozen=True, slots=True)
class ImageAuditConfiguration:
    enabled: bool = False
    verify_internal_images: bool = True
    verify_external_images: bool = False
    maximum_unique_image_fetches: int = 10_000
    maximum_image_response_bytes: int = 2_000_000
    maximum_alt_length: int = 200
    minimum_sitewide_pages: int = 5
    sitewide_source_ratio: float = 0.50
    default_page_size: int = 50
    maximum_page_size: int = 200
    maximum_export_rows: int = 100_000
    retention_days: int = 180

    def __post_init__(self) -> None:
        if not 1 <= self.maximum_unique_image_fetches <= 100_000:
            raise ValueError("image audit fetch limit is invalid")
        if not 1_024 <= self.maximum_image_response_bytes <= 50_000_000:
            raise ValueError("image audit response limit is invalid")
        if not 32 <= self.maximum_alt_length <= 4_096:
            raise ValueError("image audit alt threshold is invalid")
        if not 1 <= self.minimum_sitewide_pages <= 10_000:
            raise ValueError("image audit sitewide threshold is invalid")
        if not 0 < self.sitewide_source_ratio <= 1:
            raise ValueError("image audit sitewide ratio is invalid")
        if not 1 <= self.default_page_size <= self.maximum_page_size <= 1_000:
            raise ValueError("image audit page sizes are invalid")
        if not 1 <= self.maximum_export_rows <= 1_000_000:
            raise ValueError("image audit export limit is invalid")
        if not 1 <= self.retention_days <= 3_650:
            raise ValueError("image audit retention is invalid")

    def snapshot(self) -> dict[str, Any]:
        return asdict(self)


_SPACE = re.compile(r"\s+")
_GENERIC = frozenset(
    {
        "image",
        "photo",
        "picture",
        "graphic",
        "icon",
        "logo",
        "banner",
        "thumbnail",
        "click here",
        "read more",
        "learn more",
    }
)
_FILENAME = re.compile(
    r"^(?:img[_-]?\d+|dsc\d+|photo[_-]?\d+|image(?:[_-]\d+)+|[\w-]+(?:final|copy|v\d+)[\w-]*|[^/\\]+\.(?:jpe?g|png|gif|webp|svg|avif))$",
    re.IGNORECASE,
)
_URLISH = re.compile(r"^(?:https?://|www\.|/|[A-Za-z]:\\|[^\s]+\.[a-z]{2,}(?:/|$))", re.I)


def normalize_alt(value: str | None, *, maximum_length: int = 1_024) -> str | None:
    if value is None:
        return None
    return _SPACE.sub(" ", value.strip())[:maximum_length]


def classify_alt(
    *,
    present: bool,
    raw_value: str | None,
    linked: bool,
    decorative: bool,
    maximum_length: int = 200,
) -> AltTextState:
    if not present:
        return AltTextState.MISSING
    normalized = normalize_alt(raw_value) or ""
    if not normalized:
        if raw_value and raw_value.strip() == "":
            return AltTextState.WHITESPACE
        if linked:
            return AltTextState.LINK_EMPTY
        return AltTextState.DECORATIVE if decorative else AltTextState.EMPTY
    folded = normalized.casefold()
    if len(normalized) > maximum_length:
        return AltTextState.OVERLONG
    if folded in _GENERIC:
        return AltTextState.GENERIC
    if _FILENAME.fullmatch(normalized):
        return AltTextState.FILENAME
    if _URLISH.search(normalized):
        return AltTextState.URL
    return AltTextState.PRESENT


def classify_dimensions(width: str | None, height: str | None) -> DimensionState:
    if width is None and height is None:
        return DimensionState.BOTH_MISSING
    if width is None:
        return DimensionState.WIDTH_MISSING
    if height is None:
        return DimensionState.HEIGHT_MISSING
    parsed: list[int] = []
    for value, invalid in (
        (width, DimensionState.INVALID_WIDTH),
        (height, DimensionState.INVALID_HEIGHT),
    ):
        try:
            parsed.append(int(value.strip()))
        except ValueError:
            return invalid
    if min(parsed) <= 0:
        return DimensionState.ZERO if 0 in parsed else DimensionState.REVIEW
    return DimensionState.PRESENT


def classify_loading(
    loading: str | None, decoding: str | None, fetch_priority: str | None
) -> LoadingState:
    normalized = (loading or "").strip().casefold()
    if normalized == "lazy":
        return LoadingState.LAZY
    if normalized == "eager":
        return LoadingState.EAGER
    if normalized:
        return LoadingState.INVALID
    if (decoding or "").strip().casefold() == "async":
        return LoadingState.DECODING_ASYNC
    if (fetch_priority or "").strip().casefold() == "high":
        return LoadingState.FETCHPRIORITY_HIGH
    return LoadingState.MISSING


def stable_identity(*values: object) -> str:
    return hashlib.sha256("\0".join(str(value) for value in values).encode()).hexdigest()


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def audit_identity(run_id: str, configuration: ImageAuditConfiguration) -> str:
    return f"image-audit-{stable_identity(run_id, stable_json(configuration.snapshot()))[:24]}"


def filter_fingerprint(values: dict[str, Any]) -> str:
    return stable_identity(stable_json(values))[:24]


def encode_cursor(kind: str, ordering: str, fingerprint: str, offset: int) -> str:
    payload = stable_json({"f": fingerprint, "k": kind, "o": offset, "v": ordering}).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_cursor(value: str, kind: str, ordering: str, fingerprint: str) -> int:
    try:
        payload = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        offset = int(payload["o"])
    except KeyError, TypeError, ValueError, json.JSONDecodeError:
        raise ValueError(ImageAuditErrorCode.INVALID_CURSOR) from None
    if payload != {"f": fingerprint, "k": kind, "o": payload["o"], "v": ordering}:
        raise ValueError(ImageAuditErrorCode.CURSOR_FILTER_MISMATCH)
    if offset < 0:
        raise ValueError(ImageAuditErrorCode.INVALID_CURSOR)
    return offset
