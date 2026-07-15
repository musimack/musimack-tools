"""Boundary-heavy tests for deterministic in-memory XML sitemap generation."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from xml.etree import ElementTree as ET

import pytest

from musimack_tools.domain.sitemap import (
    CanonicalSummary,
    GenericIndexabilitySummary,
    RecommendationConfigurationSnapshot,
    RecommendationDeterminacy,
    RecommendationState,
    RecommendationWarning,
    RedirectSummary,
    RobotsPermissionSummary,
    SitemapReasonCode,
    SitemapRecommendation,
    SitemapRecommendationProjection,
)
from musimack_tools.domain.sitemap_xml import (
    PROTOCOL_MAX_DOCUMENT_BYTES,
    PROTOCOL_MAX_INDEX_BYTES,
    PROTOCOL_MAX_INDEX_ENTRIES,
    PROTOCOL_MAX_LOCATION_CHARACTERS,
    PROTOCOL_MAX_URL_ENTRIES,
    SITEMAP_XML_DECLARATION,
    SITEMAP_XML_FORMAT_VERSION,
    SITEMAP_XML_NAMESPACE,
    SitemapBundleWarningCode,
    SitemapEntryRejectionReason,
    SitemapSplitReason,
)
from musimack_tools.sitemap.limits import (
    MINIMUM_INDEX_DOCUMENT_BYTES,
    MINIMUM_URL_DOCUMENT_BYTES,
    SitemapXmlConfiguration,
)
from musimack_tools.sitemap.xml import SitemapXmlGenerator

_NS = {"sm": SITEMAP_XML_NAMESPACE}


def _recommendation(
    url: str,
    state: RecommendationState = RecommendationState.INCLUDE,
    *,
    metadata_warnings: tuple[RecommendationWarning, ...] = (),
) -> SitemapRecommendation:
    return SitemapRecommendation(
        evaluated_url=url,
        requested_url=url,
        final_url=url,
        state=state,
        determinacy=RecommendationDeterminacy.DETERMINATE,
        primary_reason=SitemapReasonCode.ELIGIBLE_HTML_PAGE,
        hard_exclusion_reasons=(),
        review_reasons=(),
        warnings=(),
        metadata_warnings=metadata_warnings,
        fetch_failure_code=None,
        http_status=200,
        content_type="text/html",
        robots=RobotsPermissionSummary(available=True, allowed=True, reason_code="allowed"),
        indexability=GenericIndexabilitySummary(
            generic_directives=(),
            crawler_specific_directives=(),
            generic_index_conflict=False,
        ),
        canonical=CanonicalSummary(
            selected_url=url,
            valid_candidates=(url,),
            invalid_observation_count=0,
            conflicting=False,
        ),
        redirect=RedirectSummary(
            is_redirect_source=False,
            hop_count=0,
            final_url=url,
            target_independently_evaluated=None,
        ),
        configured_exclusions=(),
        rule_results=(),
        explanation="Fixture recommendation.",
    )


def _projection(*recommendations: SitemapRecommendation) -> SitemapRecommendationProjection:
    states = [item.state for item in recommendations]
    return SitemapRecommendationProjection(
        recommendations=tuple(recommendations),
        included_url_count=states.count(RecommendationState.INCLUDE),
        excluded_url_count=states.count(RecommendationState.EXCLUDE),
        review_count=states.count(RecommendationState.REVIEW),
        indeterminate_count=states.count(RecommendationState.INDETERMINATE),
        counts_by_primary_reason=(),
        metadata_warning_counts=(),
        duplicate_suppression_count=0,
        redirect_source_count=0,
        canonical_exclusion_count=0,
        noindex_exclusion_count=0,
        robots_denial_count=0,
        non_html_count=0,
        non_200_count=0,
        configuration=RecommendationConfigurationSnapshot(
            missing_canonical_requires_review=False,
            invalid_canonical_requires_review=True,
            ambiguous_sniffed_html_requires_review=False,
            crawler_specific_noindex_requires_review=False,
            severe_parser_recovery_requires_review=True,
            rule_set_version="v1",
        ),
        rule_set_version="v1",
    )


def _locations(xml_bytes: bytes, element: str = "url") -> list[str]:
    # The parser receives only serializer output created in this test process.
    root = ET.fromstring(xml_bytes)  # noqa: S314
    return [item.text or "" for item in root.findall(f"sm:{element}/sm:loc", _NS)]


def test_empty_projection_generates_valid_empty_urlset() -> None:
    bundle = SitemapXmlGenerator().generate(_projection())

    expected = (
        f'{SITEMAP_XML_DECLARATION}\n<urlset xmlns="{SITEMAP_XML_NAMESPACE}">\n</urlset>\n'
    ).encode()
    assert bundle.documents[0].xml_bytes == expected
    assert bundle.documents[0].logical_name == "sitemap.xml"
    assert bundle.documents[0].entry_count == 0
    assert bundle.index_document is None


def test_single_entry_has_exact_readable_xml_contract() -> None:
    url = "https://example.test/page"
    bundle = SitemapXmlGenerator().generate(_projection(_recommendation(url)))

    expected = (
        f'{SITEMAP_XML_DECLARATION}\n<urlset xmlns="{SITEMAP_XML_NAMESPACE}">\n'
        f"  <url>\n    <loc>{url}</loc>\n  </url>\n</urlset>\n"
    ).encode()
    assert bundle.documents[0].xml_bytes == expected
    assert bundle.documents[0].byte_count == len(expected)
    assert bundle.format_version == SITEMAP_XML_FORMAT_VERSION


def test_only_include_state_is_serialized_and_source_is_unchanged() -> None:
    items = tuple(
        _recommendation(f"https://example.test/{state.value}", state)
        for state in RecommendationState
    )
    projection = _projection(*items)

    bundle = SitemapXmlGenerator().generate(projection)

    assert _locations(bundle.documents[0].xml_bytes) == ["https://example.test/include"]
    assert bundle.counts.considered_recommendations == 4
    assert bundle.counts.include_recommendation_inputs == 1
    assert bundle.counts.skipped_non_include == 3
    assert projection.recommendations == items


def test_recommendation_evidence_is_not_re_evaluated() -> None:
    url = "https://example.test/contract-boundary"
    included = replace(
        _recommendation(url),
        http_status=302,
        robots=RobotsPermissionSummary(available=True, allowed=False, reason_code="denied"),
        indexability=GenericIndexabilitySummary(
            generic_directives=("noindex",),
            crawler_specific_directives=(),
            generic_index_conflict=False,
        ),
        canonical=CanonicalSummary(
            selected_url="https://other.test/",
            valid_candidates=("https://other.test/",),
            invalid_observation_count=0,
            conflicting=False,
        ),
    )

    bundle = SitemapXmlGenerator().generate(_projection(included))

    assert _locations(bundle.documents[0].xml_bytes) == [url]


def test_metadata_warnings_do_not_change_serialization() -> None:
    warning = RecommendationWarning("missing_title", "Title is missing.", "metadata")
    item = _recommendation("https://example.test/warning", metadata_warnings=(warning,))
    assert SitemapXmlGenerator().generate(_projection(item)).counts.unique_entries_emitted == 1


@pytest.mark.parametrize(
    "url",
    [
        "https://example.test/a?x=1&y=2",
        "https://example.test/a%2Fb?next=%2Fpath%3Fx%3D1",
        "https://example.test/café?q=naïve",
        "https://example.test/?a=1&a=&a=THREE",
        "https://example.test/<angle>?quote=\"yes\"&apostrophe='yes'",
    ],
)
def test_xml_escaping_and_utf8_round_trip_preserve_location(url: str) -> None:
    document = SitemapXmlGenerator().generate(_projection(_recommendation(url))).documents[0]

    assert _locations(document.xml_bytes) == [url]
    assert document.byte_count == len(document.xml_bytes)
    assert document.xml_bytes.endswith(b"\n")


def test_input_order_is_preserved() -> None:
    urls = ["https://example.test/z", "https://example.test/a", "https://example.test/m"]
    bundle = SitemapXmlGenerator().generate(_projection(*map(_recommendation, urls)))
    assert _locations(bundle.documents[0].xml_bytes) == urls


def test_exact_duplicates_are_suppressed_first_occurrence_wins() -> None:
    url = "https://example.test/a"
    bundle = SitemapXmlGenerator().generate(
        _projection(_recommendation(url), _recommendation(url), _recommendation(url))
    )

    assert _locations(bundle.documents[0].xml_bytes) == [url]
    assert bundle.documents[0].entries[0].source_recommendation_index == 0
    assert bundle.counts.duplicate_suppression_count == 2


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("https://example.test/a", "https://example.test/a/"),
        ("https://example.test/A", "https://example.test/a"),
        ("https://example.test/?a=1&b=2", "https://example.test/?b=2&a=1"),
        ("https://example.test/?a=1&a=2", "https://example.test/?a=1&a=3"),
    ],
)
def test_distinct_normalized_identities_are_not_deduplicated(first: str, second: str) -> None:
    bundle = SitemapXmlGenerator().generate(
        _projection(_recommendation(first), _recommendation(second))
    )
    assert _locations(bundle.documents[0].xml_bytes) == [first, second]


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("", SitemapEntryRejectionReason.INVALID_URL),
        ("example.test/path", SitemapEntryRejectionReason.INVALID_URL),
        ("ftp://example.test/path", SitemapEntryRejectionReason.UNSUPPORTED_SCHEME),
        ("https:///path", SitemapEntryRejectionReason.MISSING_HOST),
        ("https://example.test/\x01", SitemapEntryRejectionReason.XML_ILLEGAL_CHARACTER),
        ("https://example.test/\ud800", SitemapEntryRejectionReason.XML_ILLEGAL_CHARACTER),
        ("HTTPS://EXAMPLE.TEST/path", SitemapEntryRejectionReason.INVALID_URL),
    ],
)
def test_invalid_include_locations_are_rejected_with_stable_reason(
    url: str, reason: SitemapEntryRejectionReason
) -> None:
    bundle = SitemapXmlGenerator().generate(_projection(_recommendation(url)))

    assert bundle.documents[0].entry_count == 0
    assert bundle.rejections[0].reason is reason
    assert bundle.rejections[0].supplied_url == url


def test_character_limit_rejects_without_truncating() -> None:
    url = f"https://example.test/{'a' * 80}"
    configuration = SitemapXmlConfiguration(url_maximum_characters=len(url) - 1)
    bundle = SitemapXmlGenerator(configuration).generate(_projection(_recommendation(url)))

    assert bundle.rejections[0].reason is SitemapEntryRejectionReason.URL_TOO_LONG
    assert bundle.rejections[0].supplied_url == url
    assert url.encode() not in bundle.documents[0].xml_bytes


def test_default_2048_character_limit_rejects_2049_character_location() -> None:
    prefix = "https://example.test/"
    url = f"{prefix}{'a' * (PROTOCOL_MAX_LOCATION_CHARACTERS + 1 - len(prefix))}"

    bundle = SitemapXmlGenerator().generate(_projection(_recommendation(url)))

    assert len(url) == 2_049
    assert bundle.rejections[0].reason is SitemapEntryRejectionReason.URL_TOO_LONG


def test_invalid_entry_does_not_block_valid_entries_and_order_is_retained() -> None:
    items = (
        _recommendation("ftp://example.test/a"),
        _recommendation("https://example.test/valid"),
        _recommendation(""),
    )
    bundle = SitemapXmlGenerator().generate(_projection(*items))

    assert _locations(bundle.documents[0].xml_bytes) == ["https://example.test/valid"]
    assert [item.source_recommendation_index for item in bundle.rejections] == [0, 2]


def test_one_entry_that_cannot_fit_is_rejected_without_partial_body() -> None:
    url = "https://example.test/a-long-location"
    configuration = SitemapXmlConfiguration(url_document_byte_limit=MINIMUM_URL_DOCUMENT_BYTES + 5)
    bundle = SitemapXmlGenerator(configuration).generate(_projection(_recommendation(url)))

    assert bundle.rejections[0].reason is (
        SitemapEntryRejectionReason.ENTRY_EXCEEDS_DOCUMENT_BYTE_LIMIT
    )
    assert bundle.documents[0].entry_count == 0
    assert bundle.split_events == ()


@pytest.mark.parametrize("count", [2, 3, 5])
def test_entry_limit_splits_deterministically(count: int) -> None:
    urls = [f"https://example.test/{index}" for index in range(count)]
    configuration = SitemapXmlConfiguration(url_entries_per_document_limit=2)
    bundle = SitemapXmlGenerator(configuration).generate(_projection(*map(_recommendation, urls)))

    document_count = (count + 1) // 2
    expected_names = (
        ["sitemap.xml"]
        if document_count == 1
        else [f"sitemap-{index}.xml" for index in range(1, document_count + 1)]
    )
    assert [item.logical_name for item in bundle.documents] == expected_names
    assert [url for document in bundle.documents for url in _locations(document.xml_bytes)] == urls
    assert all(item.entry_count <= 2 for item in bundle.documents)


def test_exact_entry_limit_does_not_split_and_plus_one_does() -> None:
    two = [_recommendation(f"https://example.test/{index}") for index in range(2)]
    generator = SitemapXmlGenerator(SitemapXmlConfiguration(url_entries_per_document_limit=2))

    assert len(generator.generate(_projection(*two)).documents) == 1
    split = generator.generate(_projection(*two, _recommendation("https://example.test/2")))
    assert len(split.documents) == 2
    assert split.split_events[0].reason is SitemapSplitReason.ENTRY_LIMIT


def test_exact_utf8_byte_limit_fits_and_one_more_entry_splits() -> None:
    first = _recommendation("https://example.test/café")
    one = SitemapXmlGenerator().generate(_projection(first)).documents[0]
    configuration = SitemapXmlConfiguration(url_document_byte_limit=one.byte_count)
    generator = SitemapXmlGenerator(configuration)

    assert len(generator.generate(_projection(first)).documents) == 1
    bundle = generator.generate(_projection(first, _recommendation("https://example.test/b")))
    assert len(bundle.documents) == 2
    assert bundle.split_events[0].reason is SitemapSplitReason.BYTE_LIMIT
    assert all(item.byte_count <= one.byte_count for item in bundle.documents)


def test_multi_document_bundle_without_base_has_typed_warning_and_no_index() -> None:
    configuration = SitemapXmlConfiguration(url_entries_per_document_limit=1)
    bundle = SitemapXmlGenerator(configuration).generate(
        _projection(
            _recommendation("https://example.test/a"), _recommendation("https://example.test/b")
        )
    )

    assert len(bundle.documents) == 2
    assert bundle.index_document is None
    assert bundle.warnings[0].code is SitemapBundleWarningCode.INDEX_BLOCKED_MISSING_BASE_URL


def test_multi_document_bundle_with_base_has_deterministic_index() -> None:
    configuration = SitemapXmlConfiguration(
        url_entries_per_document_limit=1,
        sitemap_base_url="https://cdn.example.test/maps",
    )
    bundle = SitemapXmlGenerator(configuration).generate(
        _projection(
            _recommendation("https://example.test/a"), _recommendation("https://example.test/b")
        )
    )

    assert bundle.index_document is not None
    assert bundle.index_document.logical_name == "sitemap-index.xml"
    assert _locations(bundle.index_document.xml_bytes, "sitemap") == [
        "https://cdn.example.test/maps/sitemap-1.xml",
        "https://cdn.example.test/maps/sitemap-2.xml",
    ]
    assert bundle.warnings == ()


def test_index_locations_are_xml_escaped() -> None:
    configuration = SitemapXmlConfiguration(
        url_entries_per_document_limit=1,
        sitemap_base_url="https://cdn.example.test/maps&reports",
    )
    bundle = SitemapXmlGenerator(configuration).generate(
        _projection(
            _recommendation("https://example.test/a"), _recommendation("https://example.test/b")
        )
    )
    assert bundle.index_document is not None
    assert b"maps&amp;reports" in bundle.index_document.xml_bytes


def test_index_entry_capacity_blocks_index_without_dropping_documents() -> None:
    configuration = SitemapXmlConfiguration(
        url_entries_per_document_limit=1,
        index_entries_limit=1,
        sitemap_base_url="https://example.test/maps/",
    )
    bundle = SitemapXmlGenerator(configuration).generate(
        _projection(
            _recommendation("https://example.test/a"), _recommendation("https://example.test/b")
        )
    )

    assert len(bundle.documents) == 2
    assert bundle.index_document is None
    assert bundle.warnings[0].code is SitemapBundleWarningCode.INDEX_BLOCKED_ENTRY_LIMIT


def test_index_byte_capacity_blocks_index_without_recursive_index() -> None:
    items = (_recommendation("https://example.test/a"), _recommendation("https://example.test/b"))
    base = SitemapXmlConfiguration(
        url_entries_per_document_limit=1,
        sitemap_base_url="https://example.test/maps/",
    )
    first = SitemapXmlGenerator(base).generate(_projection(*items))
    assert first.index_document is not None
    constrained = replace(base, index_document_byte_limit=first.index_document.byte_count - 1)

    bundle = SitemapXmlGenerator(constrained).generate(_projection(*items))

    assert bundle.index_document is None
    assert bundle.warnings[0].code is SitemapBundleWarningCode.INDEX_BLOCKED_BYTE_LIMIT
    assert all("index" not in item.logical_name for item in bundle.documents)


@pytest.mark.parametrize(
    "base",
    ["ftp://example.test/maps", "https://example.test/maps?x=1", "https://example.test/#x", "maps"],
)
def test_invalid_index_base_is_rejected(base: str) -> None:
    with pytest.raises(ValueError, match="sitemap base URL"):
        SitemapXmlConfiguration(sitemap_base_url=base)


def test_single_document_never_generates_an_index_even_with_base() -> None:
    configuration = SitemapXmlConfiguration(sitemap_base_url="https://example.test/maps/")
    bundle = SitemapXmlGenerator(configuration).generate(
        _projection(_recommendation("https://example.test/a"))
    )
    assert bundle.index_document is None


def test_generation_is_byte_for_byte_deterministic_and_immutable() -> None:
    projection = _projection(_recommendation("https://example.test/a?x=1&y=2"))
    first = SitemapXmlGenerator().generate(projection)
    second = SitemapXmlGenerator().generate(projection)

    assert first == second
    with pytest.raises(FrozenInstanceError):
        first.format_version = "other"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("url_entries_per_document_limit", 0),
        ("url_entries_per_document_limit", -1),
        ("url_entries_per_document_limit", PROTOCOL_MAX_URL_ENTRIES + 1),
        ("url_document_byte_limit", MINIMUM_URL_DOCUMENT_BYTES - 1),
        ("url_document_byte_limit", -1),
        ("url_document_byte_limit", PROTOCOL_MAX_DOCUMENT_BYTES + 1),
        ("index_entries_limit", 0),
        ("index_entries_limit", -1),
        ("index_entries_limit", PROTOCOL_MAX_INDEX_ENTRIES + 1),
        ("index_document_byte_limit", MINIMUM_INDEX_DOCUMENT_BYTES - 1),
        ("index_document_byte_limit", -1),
        ("index_document_byte_limit", PROTOCOL_MAX_INDEX_BYTES + 1),
        ("url_maximum_characters", 0),
        ("url_maximum_characters", -1),
        ("url_maximum_characters", PROTOCOL_MAX_LOCATION_CHARACTERS + 1),
    ],
)
def test_protocol_limit_configuration_rejects_out_of_bounds(field: str, value: int) -> None:
    with pytest.raises(ValueError):
        SitemapXmlConfiguration(**{field: value})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("single_document_name", "../sitemap.xml"),
        ("single_document_name", "sitemap.txt"),
        ("split_document_prefix", "../map"),
        ("index_document_name", "index"),
    ],
)
def test_logical_names_reject_paths_and_invalid_extensions(field: str, value: str) -> None:
    with pytest.raises(ValueError):
        SitemapXmlConfiguration(**{field: value})  # type: ignore[arg-type]


def test_format_version_is_defined_once_and_cannot_be_overridden() -> None:
    assert SitemapXmlConfiguration().format_version == SITEMAP_XML_FORMAT_VERSION
    with pytest.raises(ValueError, match="format version"):
        SitemapXmlConfiguration(format_version="sitemap-xml-v2")


def test_configuration_defaults_are_protocol_bounded() -> None:
    configuration = SitemapXmlConfiguration()
    assert configuration.url_entries_per_document_limit == PROTOCOL_MAX_URL_ENTRIES
    assert configuration.url_document_byte_limit == PROTOCOL_MAX_DOCUMENT_BYTES
    assert configuration.index_entries_limit == PROTOCOL_MAX_INDEX_ENTRIES
    assert configuration.index_document_byte_limit == PROTOCOL_MAX_INDEX_BYTES
    assert configuration.url_maximum_characters == PROTOCOL_MAX_LOCATION_CHARACTERS
    with pytest.raises(FrozenInstanceError):
        configuration.url_maximum_characters = 1  # type: ignore[misc]


def test_bundle_counts_reconcile_valid_duplicates_rejections_and_skips() -> None:
    url = "https://example.test/a"
    bundle = SitemapXmlGenerator().generate(
        _projection(
            _recommendation(url),
            _recommendation(url),
            _recommendation("ftp://example.test/a"),
            _recommendation("https://example.test/excluded", RecommendationState.EXCLUDE),
        )
    )

    assert bundle.counts.include_recommendation_inputs == 3
    assert bundle.counts.unique_entries_emitted == 1
    assert bundle.counts.duplicate_suppression_count == 1
    assert bundle.counts.rejected_entry_count == 1
    assert bundle.counts.skipped_non_include == 1


def test_documents_contain_only_loc_elements_without_optional_fields() -> None:
    xml_bytes = (
        SitemapXmlGenerator()
        .generate(_projection(_recommendation("https://example.test/a")))
        .documents[0]
        .xml_bytes
    )
    text = xml_bytes.decode()
    assert "<lastmod>" not in text
    assert "<changefreq>" not in text
    assert "<priority>" not in text
    assert "<url>" in text and "<loc>" in text
