"""Deterministic Phase 24 taxonomy and policy coverage."""

# ruff: noqa: FBT001, FBT003, SLF001

import pytest

from musimack_tools.domain.image_audit import (
    AltTextState,
    Confidence,
    DimensionState,
    ImageAction,
    ImageAuditConfiguration,
    ImageResourceState,
    LoadingState,
    classify_alt,
    classify_dimensions,
    classify_loading,
    decode_cursor,
    encode_cursor,
)
from musimack_tools.image_audit.service import (
    ImageAuditService,
    _csv_safe,
    _occurrence_severity,
    _recommendation,
    _resource_state,
)


@pytest.mark.parametrize(
    ("present", "value", "linked", "decorative", "expected"),
    [
        (False, None, False, False, AltTextState.MISSING),
        (True, "", False, True, AltTextState.DECORATIVE),
        (True, "   ", False, False, AltTextState.WHITESPACE),
        (True, "", True, False, AltTextState.LINK_EMPTY),
        (True, "image", False, False, AltTextState.GENERIC),
        (True, "IMG_1234", False, False, AltTextState.FILENAME),
        (True, "https://example.test/x", False, False, AltTextState.URL),
    ],
)
def test_alt_taxonomy(
    present: bool, value: str | None, linked: bool, decorative: bool, expected: AltTextState
) -> None:
    assert (
        classify_alt(present=present, raw_value=value, linked=linked, decorative=decorative)
        is expected
    )


def test_dimensions_and_loading_are_conservative() -> None:
    assert classify_dimensions(None, None) is DimensionState.BOTH_MISSING
    assert classify_dimensions("100%", "20") is DimensionState.INVALID_WIDTH
    assert classify_dimensions("0", "20") is DimensionState.ZERO
    assert classify_dimensions("100", "20") is DimensionState.PRESENT
    assert classify_loading(None, None, None) is LoadingState.MISSING
    assert classify_loading("lazy", None, None) is LoadingState.LAZY
    assert classify_loading("viewport", None, None) is LoadingState.INVALID


def test_filter_bound_cursor_and_configuration_bounds() -> None:
    cursor = encode_cursor("resources", "v1", "filter-a", 10)
    assert decode_cursor(cursor, "resources", "v1", "filter-a") == 10
    with pytest.raises(ValueError, match="cursor_filter_mismatch"):
        decode_cursor(cursor, "resources", "v1", "filter-b")
    with pytest.raises(ValueError, match="alt threshold"):
        ImageAuditConfiguration(maximum_alt_length=10)


@pytest.mark.parametrize(
    "value",
    [
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
    ],
)
def test_every_documented_generic_alt_value(value: str) -> None:
    assert (
        classify_alt(present=True, raw_value=value, linked=False, decorative=False)
        is AltTextState.GENERIC
    )


@pytest.mark.parametrize(
    "value",
    ["Musimack", "Company logo", "Go", "Natural hyphenated phrase", "AB-1200"],
)
def test_valid_short_brand_and_product_text_is_not_generic_or_filename_like(value: str) -> None:
    assert (
        classify_alt(present=True, raw_value=value, linked=False, decorative=False)
        is AltTextState.PRESENT
    )


@pytest.mark.parametrize(
    "value",
    ["IMG_1234", "DSC00042", "photo-1", "image_2026_01", "hero-banner-final-v2", "example.jpg"],
)
def test_documented_filename_like_alt_values(value: str) -> None:
    assert (
        classify_alt(present=True, raw_value=value, linked=False, decorative=False)
        is AltTextState.FILENAME
    )


@pytest.mark.parametrize(
    "value",
    ["https://example.com/a", "example.com", "/images/a.png", r"C:\images\a.png"],
)
def test_documented_url_like_alt_values(value: str) -> None:
    assert (
        classify_alt(present=True, raw_value=value, linked=False, decorative=False)
        is AltTextState.URL
    )


def test_natural_domain_word_and_alt_length_boundaries_are_conservative() -> None:
    assert (
        classify_alt(
            present=True, raw_value="Example domain overview", linked=False, decorative=False
        )
        is AltTextState.PRESENT
    )
    for length, expected in (
        (199, AltTextState.PRESENT),
        (200, AltTextState.PRESENT),
        (201, AltTextState.OVERLONG),
    ):
        assert (
            classify_alt(present=True, raw_value="x" * length, linked=False, decorative=False)
            is expected
        )
    assert (
        classify_alt(present=True, raw_value=("x " * 101), linked=False, decorative=False)
        is AltTextState.OVERLONG
    )


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        ("10", "20", DimensionState.PRESENT),
        (None, "20", DimensionState.WIDTH_MISSING),
        ("10", None, DimensionState.HEIGHT_MISSING),
        (None, None, DimensionState.BOTH_MISSING),
        ("0", "20", DimensionState.ZERO),
        ("-1", "20", DimensionState.REVIEW),
        ("wide", "20", DimensionState.INVALID_WIDTH),
        ("10", "50%", DimensionState.INVALID_HEIGHT),
        ("calc(10px)", "20", DimensionState.INVALID_WIDTH),
    ],
)
def test_dimension_taxonomy_boundaries(
    width: str | None, height: str | None, expected: DimensionState
) -> None:
    assert classify_dimensions(width, height) is expected


@pytest.mark.parametrize(
    ("loading", "decoding", "priority", "expected"),
    [
        ("lazy", None, None, LoadingState.LAZY),
        ("eager", None, None, LoadingState.EAGER),
        (None, None, None, LoadingState.MISSING),
        ("fast", None, None, LoadingState.INVALID),
        (None, "async", None, LoadingState.DECODING_ASYNC),
        (None, "sync", None, LoadingState.MISSING),
        (None, None, "high", LoadingState.FETCHPRIORITY_HIGH),
        (None, None, "low", LoadingState.MISSING),
    ],
)
def test_loading_taxonomy_is_evidence_only(
    loading: str | None, decoding: str | None, priority: str | None, expected: LoadingState
) -> None:
    assert classify_loading(loading, decoding, priority) is expected


@pytest.mark.parametrize(
    "content_type",
    [
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "image/svg+xml",
        "image/avif",
        "image/x-icon",
    ],
)
def test_supported_image_content_types(content_type: str) -> None:
    assert _resource_state(200, content_type, 0) is ImageResourceState.VALID


@pytest.mark.parametrize(
    ("status", "content_type", "redirects", "url", "expected"),
    [
        (404, "image/png", 0, "/a.png", ImageResourceState.BROKEN),
        (410, "image/png", 0, "/a.png", ImageResourceState.BROKEN),
        (418, "image/png", 0, "/a.png", ImageResourceState.BROKEN),
        (500, "image/png", 0, "/a.png", ImageResourceState.BROKEN),
        (200, "image/png", 1, "/a.png", ImageResourceState.REDIRECTING),
        (200, "text/html", 0, "/a.png", ImageResourceState.UNVERIFIED),
        (200, "application/json", 0, "/a.png", ImageResourceState.UNVERIFIED),
        (200, "application/octet-stream", 0, "/a.bin", ImageResourceState.UNVERIFIED),
        (200, None, 0, "/a.png", ImageResourceState.UNVERIFIED),
        (200, "image/jpeg", 0, "/a.png", ImageResourceState.UNVERIFIED),
        (None, None, 0, "/a.png", ImageResourceState.UNVERIFIED),
    ],
)
def test_resource_status_mime_redirect_and_extension_policy(
    status: int | None,
    content_type: str | None,
    redirects: int,
    url: str,
    expected: ImageResourceState,
) -> None:
    assert _resource_state(status, content_type, redirects, url) is expected


def test_reuse_metrics_include_all_required_deterministic_impact_fields() -> None:
    service = object.__new__(ImageAuditService)
    service.configuration = ImageAuditConfiguration(
        minimum_sitewide_pages=2, sitewide_source_ratio=0.5
    )
    rows = [
        {
            "source_evidence_id": "page-1",
            "alt_present": False,
            "alt_normalized": None,
            "linked": True,
            "width_value": "10",
            "height_value": "20",
            "loading_value": "lazy",
            "source_discovery_sequence": 4,
            "source_crawl_depth": 2,
        },
        {
            "source_evidence_id": "page-2",
            "alt_present": True,
            "alt_normalized": "Logo",
            "linked": False,
            "width_value": "10",
            "height_value": "30",
            "loading_value": None,
            "source_discovery_sequence": 2,
            "source_crawl_depth": 1,
        },
    ]
    metrics = service._reuse_metrics(rows, 3, ImageResourceState.BROKEN.value)
    assert metrics == {
        "unique_source_page_count": 2,
        "total_occurrence_count": 2,
        "unique_alt_count": 1,
        "missing_alt_count": 1,
        "empty_alt_count": 0,
        "linked_occurrence_count": 1,
        "broken_occurrence_count": 2,
        "redirecting_occurrence_count": 0,
        "width_consistent": True,
        "height_consistent": False,
        "loading_distribution_json": '{"lazy":1,"missing":1}',
        "earliest_discovery_sequence": 2,
        "minimum_source_depth": 1,
        "maximum_source_depth": 2,
        "sitewide_state": "sitewide_candidate",
    }


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r"])
def test_csv_formula_defense(prefix: str) -> None:
    assert _csv_safe(prefix + "payload") == "'" + prefix + "payload"


@pytest.mark.parametrize(
    ("reason", "linked", "expected_action", "expected_confidence"),
    [
        ("broken_internal_image", False, ImageAction.FIX_URL, Confidence.HIGH),
        ("redirecting_image_source", False, ImageAction.UPDATE_DESTINATION, Confidence.HIGH),
        ("placeholder_image", False, ImageAction.REPLACE_PLACEHOLDER, Confidence.HIGH),
        ("missing_alt_linked", True, ImageAction.ADD_ALT, Confidence.HIGH),
        ("missing_alt", False, ImageAction.ADD_ALT, Confidence.MEDIUM),
        ("alt_generic", False, ImageAction.REPLACE_ALT, Confidence.MEDIUM),
        ("alt_filename_like", False, ImageAction.REPLACE_ALT, Confidence.HIGH),
        ("empty_alt_review", False, ImageAction.CONFIRM_DECORATIVE, Confidence.LOW),
        ("missing_or_invalid_dimensions", False, ImageAction.ADD_DIMENSIONS, Confidence.MEDIUM),
        ("loading_attribute_review", False, ImageAction.REVIEW_LOADING, Confidence.LOW),
        ("external_image_review", False, ImageAction.REVIEW, Confidence.LOW),
    ],
)
def test_recommendation_evidence_rules(
    reason: str,
    linked: bool,
    expected_action: ImageAction,
    expected_confidence: Confidence,
) -> None:
    assert _recommendation({"primary_reason": reason, "linked_image": linked}) == (
        expected_action,
        expected_confidence,
    )


def test_broken_resource_takes_precedence_over_dimensions_and_loading() -> None:
    severity, reason = _occurrence_severity(
        AltTextState.PRESENT,
        DimensionState.BOTH_MISSING,
        LoadingState.MISSING,
        ImageResourceState.BROKEN.value,
        False,
        1,
    )
    assert severity.value == "high" and reason == "broken_internal_image"
