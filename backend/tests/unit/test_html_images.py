"""Parser-owned bounded image evidence coverage."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from musimack_tools.crawl.html import HtmlMetadataParser
from musimack_tools.crawl.normalization import normalize_url
from musimack_tools.crawl.scope import create_scope_policy
from musimack_tools.domain.fetching import FetchOutcome, FetchResult, ResponseHeaders
from musimack_tools.domain.page_evidence import PageEvidenceConfiguration, project_crawl_result
from page_evidence_helpers import PageRecordOptions, crawl_result, page_record

if TYPE_CHECKING:
    from musimack_tools.domain.html import HtmlParseResult

_URL = "https://example.test/directory/page"


def _parse(html: str) -> HtmlParseResult:
    body = html.encode()
    fetch = FetchResult(
        requested_url=_URL,
        final_url=_URL,
        outcome=FetchOutcome.SUCCESS,
        status_code=200,
        headers=ResponseHeaders(content_type="text/html"),
        content_type="text/html",
        declared_content_length=len(body),
        actual_bytes_read=len(body),
        body_truncated=False,
        redirect_chain=(),
        request_duration_seconds=0.01,
        dns_evidence=(),
        failure_code=None,
        failure_explanation=None,
        body=body,
    )
    seed = normalize_url(_URL)
    return HtmlMetadataParser().parse(fetch, scope=create_scope_policy(seed))


def test_img_attributes_preserve_missing_empty_and_link_context() -> None:
    images = _parse(
        "<img src='/missing.jpg'><a href='/buy'>"
        "<img src='/empty.png' alt='' width='0' height='20' loading='lazy'></a>"
    ).images
    assert len(images) == 2
    assert images[0].alt_present is False
    assert images[0].normalized_url == "https://example.test/missing.jpg"
    assert images[0].in_scope is True
    assert images[1].alt_present is True and images[1].alt_value == ""
    assert images[1].linked and images[1].parent_link_url == "https://example.test/buy"
    assert images[1].decorative_explicit and images[1].loading == "lazy"


def test_picture_srcset_and_lazy_allowlist_are_bounded_evidence() -> None:
    result = _parse(
        "<picture><source srcset='/small.webp 320w, /large.webp 2x'>"
        "<img data-src='/hero.jpg' data-srcset='/hero-2.jpg 2x' "
        "sizes='100vw' alt='Hero'></picture>"
    )
    image = result.images[0]
    assert image.element_type == "picture-img"
    assert image.source_kind == "data-src"
    assert image.normalized_url == "https://example.test/hero.jpg"
    assert image.srcset_candidates == (
        ("/small.webp", "320w"),
        ("/large.webp", "2x"),
        ("/hero-2.jpg", "2x"),
    )


def test_data_and_unsupported_sources_are_never_normalized_or_fetched() -> None:
    images = _parse(
        "<img src='data:image/png;base64,AAAA' alt=''><img src='ftp://example.test/x.png' alt='x'>"
    ).images
    assert images[0].data_image and images[0].normalized_url is None
    assert images[1].unsupported_scheme and images[1].parse_warning == "unsupported_image_scheme"


def test_basic_sources_fragments_duplicates_and_order_are_explicit() -> None:
    images = _parse(
        "<img><img src='/asset.png?size=2#hero' title='Hero' width='20' height='10' "
        "loading='eager' decoding='async' fetchpriority='high'>"
        "<img src='https://example.test/asset.png?size=2#other'>"
    ).images
    assert [image.occurrence_index for image in images] == [0, 1, 2]
    assert images[0].parse_warning == "missing_image_source"
    assert images[1].raw_src == "/asset.png?size=2#hero"
    assert images[1].normalized_url == "https://example.test/asset.png?size=2"
    assert images[2].normalized_url == images[1].normalized_url
    assert (images[1].title_value, images[1].width, images[1].height) == ("Hero", "20", "10")
    assert (images[1].loading, images[1].decoding, images[1].fetch_priority) == (
        "eager",
        "async",
        "high",
    )


@pytest.mark.parametrize(
    ("attribute", "expected_kind"),
    [
        ("data-src", "data-src"),
        ("data-lazy-src", "data-lazy-src"),
        ("data-original", "data-original"),
    ],
)
def test_lazy_source_allowlist_preserves_source_kind(attribute: str, expected_kind: str) -> None:
    image = _parse(f"<img {attribute}='/lazy.png' data-unsupported='/ignored.png'>").images[0]
    assert image.source_kind == expected_kind
    assert image.normalized_url == "https://example.test/lazy.png"


def test_unsupported_lazy_attribute_is_ignored() -> None:
    image = _parse("<img data-unsupported='/ignored.png'>").images[0]
    assert image.normalized_url is None
    assert image.parse_warning == "missing_image_source"


@pytest.mark.parametrize(
    ("markup", "role", "aria"),
    [
        ("role='presentation'", "presentation", None),
        ("role='none'", "none", None),
        ("aria-hidden='true'", None, "true"),
    ],
)
def test_explicit_decorative_context(markup: str, role: str | None, aria: str | None) -> None:
    image = _parse(f"<a href='/action'><img src='/icon.svg' alt=' ' {markup}></a>").images[0]
    assert image.decorative_explicit
    assert image.linked and image.parent_link_url == "https://example.test/action"
    assert image.role == role and image.aria_hidden == aria


def test_multiple_picture_sources_preserve_candidate_order_without_viewport_selection() -> None:
    image = _parse(
        "<picture><source srcset='/a.avif 1x, /b.avif 2x'>"
        "<source srcset='/small.webp 320w, /large.webp 640w'>"
        "<img srcset='/fallback.png 1x' alt='Hero'></picture>"
    ).images[0]
    assert image.normalized_url is None
    assert image.parse_warning == "responsive_candidates_without_primary_source"
    assert image.srcset_candidates == (
        ("/a.avif", "1x"),
        ("/b.avif", "2x"),
        ("/small.webp", "320w"),
        ("/large.webp", "640w"),
        ("/fallback.png", "1x"),
    )


def test_projection_caps_values_candidates_and_redacts_data_payload() -> None:
    candidates = ",".join(f"/image-{index}.png {index + 1}w" for index in range(105))
    long_alt = "a" * 1_100
    record = page_record(
        options=PageRecordOptions(
            body=(
                f"<img src='/bounded.png' srcset='{candidates}' alt='{long_alt}'>"
                "<img src='data:image/png;base64,AAAA' alt=''>"
            ),
            x_robots=(),
        )
    )
    projection = project_crawl_result(
        "job-image-bounds",
        "run-image-bounds",
        crawl_result((record,)),
        PageEvidenceConfiguration(enabled=True),
    )
    bounded, inline = projection.images
    assert len(bounded.alt_raw or "") == 1_024 and bounded.value_truncated
    assert len(json.loads(bounded.srcset_candidates_json)) == 100
    assert inline.raw_src and inline.raw_src.startswith("data:image/png;length=4;sha256=")
    assert inline.data_media_type == "image/png" and inline.data_byte_length_estimate == 4
    assert inline.data_fingerprint and "AAAA" not in inline.raw_src
