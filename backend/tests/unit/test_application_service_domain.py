"""Application profiles, preparation, validation, capabilities, and diagnostics."""

from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError
from typing import TYPE_CHECKING

import pytest

from musimack_tools.application.diagnostics import serialize_json, serialize_markdown
from musimack_tools.application.preparation import ApplicationRequestPreparer
from musimack_tools.application.profiles import (
    APPLICATION_HARD_MAXIMA,
    profile_for,
    profiles,
    validate_application_maxima,
)
from musimack_tools.application.readiness import capability_report
from musimack_tools.domain.application import (
    APPLICATION_SERVICE_VERSION,
    ApplicationCrawlLimits,
    ApplicationServiceConfiguration,
    CrawlLimitOverrides,
    CrawlProfileName,
    RawApplicationCrawlRequest,
    ReadinessState,
    RecommendationProfile,
    ScopeProfile,
    ValidationIssueCode,
    ValidationSeverity,
)
from musimack_tools.domain.capabilities import SupportedCapability, UnsupportedCapability
from musimack_tools.domain.diagnostics import DIAGNOSTICS_SCHEMA_VERSION
from musimack_tools.domain.run import RunStage
from musimack_tools.domain.sitemap_publication import ExistingFilePolicy

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("name", "urls", "depth", "duration", "concurrency", "stages", "summary"),
    [
        (CrawlProfileName.QUICK_AUDIT, 100, 3, 60, 2, ("crawl", "recommend"), False),
        (
            CrawlProfileName.STANDARD_CRAWL,
            5_000,
            10,
            1_800,
            4,
            ("crawl", "recommend", "generate_xml"),
            False,
        ),
        (
            CrawlProfileName.DEEP_CRAWL,
            25_000,
            25,
            3_600,
            8,
            ("crawl", "recommend", "generate_xml"),
            False,
        ),
        (
            CrawlProfileName.SITEMAP_ONLY,
            10_000,
            15,
            2_400,
            4,
            ("crawl", "recommend", "generate_xml", "write_summary"),
            True,
        ),
    ],
)
def test_named_profile_exact_defaults_and_stages(  # noqa: PLR0913 - table contract.
    name: CrawlProfileName,
    urls: int,
    depth: int,
    duration: float,
    concurrency: int,
    stages: tuple[str, ...],
    summary: bool,  # noqa: FBT001 - parameterized contract value.
    tmp_path: Path,
) -> None:
    profile = profile_for(name)
    assert profile is not None
    assert profile.limits.maximum_urls == urls
    assert profile.limits.maximum_depth == depth
    assert profile.limits.maximum_duration_seconds == duration
    assert profile.limits.maximum_concurrency == concurrency
    raw = RawApplicationCrawlRequest(
        "https://example.com",
        crawl_profile=name,
        summary_root=tmp_path if summary else None,
    )
    result = ApplicationRequestPreparer().prepare(raw)
    assert result.report.valid
    assert result.report.requested_stages == stages


def test_profile_catalog_is_exact_immutable_and_has_no_unlimited_profile() -> None:
    assert tuple(item.name for item in profiles()) == tuple(CrawlProfileName)
    assert all("unlimited" not in item.name.value for item in profiles())
    with pytest.raises(FrozenInstanceError):
        profiles()[0].summary_requested = True  # type: ignore[misc]


def test_raw_and_prepared_requests_are_immutable() -> None:
    raw = RawApplicationCrawlRequest("https://example.com")
    with pytest.raises(FrozenInstanceError):
        raw.seed_url = "https://changed.test"  # type: ignore[misc]
    prepared = ApplicationRequestPreparer().prepare(raw).prepared
    assert prepared is not None
    with pytest.raises(FrozenInstanceError):
        prepared.run_id = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("seed", "code"),
    [
        ("example.com", ValidationIssueCode.INVALID_SEED_URL),
        ("ftp://example.com", ValidationIssueCode.UNSUPPORTED_SCHEME),
        ("https:///missing", ValidationIssueCode.MISSING_HOST),
    ],
)
def test_invalid_seed_evidence(seed: str, code: ValidationIssueCode) -> None:
    report = ApplicationRequestPreparer().prepare(RawApplicationCrawlRequest(seed)).report
    assert not report.valid
    assert code in {item.code for item in report.errors}


def test_http_https_normalization_and_deterministic_run_identity() -> None:
    preparer = ApplicationRequestPreparer()
    https = preparer.prepare(RawApplicationCrawlRequest("HTTPS://EXAMPLE.COM"))
    repeated = preparer.prepare(RawApplicationCrawlRequest("https://example.com/"))
    http = preparer.prepare(RawApplicationCrawlRequest("HTTP://EXAMPLE.COM"))
    assert https.report.normalized_seed_url == "https://example.com/"
    assert http.report.normalized_seed_url == "http://example.com/"
    assert https.report.run_id == repeated.report.run_id
    assert https.report.run_id != http.report.run_id


def test_submission_execution_identity_separates_identical_configurations() -> None:
    preparer = ApplicationRequestPreparer()
    first = preparer.prepare(
        RawApplicationCrawlRequest("https://example.com/", execution_identity="site-audit:first")
    )
    second = preparer.prepare(
        RawApplicationCrawlRequest("https://example.com/", execution_identity="site-audit:second")
    )

    assert first.prepared is not None and second.prepared is not None
    assert first.report.run_id != second.report.run_id
    assert first.prepared.run_request.crawl_request == second.prepared.run_request.crawl_request


def test_approved_hosts_normalize_and_scope_is_explicit() -> None:
    result = ApplicationRequestPreparer().prepare(
        RawApplicationCrawlRequest(
            "https://example.com",
            scope_profile=ScopeProfile.APPROVED_HOSTS,
            approved_hosts=("BLOG.EXAMPLE.COM",),
        )
    )
    assert result.report.valid
    assert result.prepared is not None
    assert "blog.example.com" in result.prepared.scope_summary


@pytest.mark.parametrize(
    "raw",
    [
        RawApplicationCrawlRequest(
            "https://example.com",
            scope_profile=ScopeProfile.APPROVED_HOSTS,
            approved_hosts=("BLOG.EXAMPLE.COM", "blog.example.com"),
        ),
        RawApplicationCrawlRequest(
            "https://example.com",
            scope_profile=ScopeProfile.EXACT_HOST,
            approved_hosts=("blog.example.com",),
        ),
        RawApplicationCrawlRequest(
            "https://example.com",
            scope_profile=ScopeProfile.APPROVED_HOSTS,
            approved_hosts=("bad host",),
        ),
    ],
)
def test_invalid_and_conflicting_approved_hosts(raw: RawApplicationCrawlRequest) -> None:
    assert not ApplicationRequestPreparer().prepare(raw).report.valid


@pytest.mark.parametrize(
    "overrides",
    [
        CrawlLimitOverrides(maximum_urls=50_001),
        CrawlLimitOverrides(maximum_depth=51),
        CrawlLimitOverrides(maximum_duration_seconds=7_201),
        CrawlLimitOverrides(maximum_accepted_bytes=5_000_000_001),
        CrawlLimitOverrides(maximum_concurrency=17),
        CrawlLimitOverrides(maximum_queue_size=100_001),
        CrawlLimitOverrides(minimum_request_delay_seconds=0.09),
        CrawlLimitOverrides(maximum_redirect_hops=21),
        CrawlLimitOverrides(maximum_response_bytes=50_000_001),
    ],
)
def test_application_maxima_reject_without_clamping(overrides: CrawlLimitOverrides) -> None:
    result = ApplicationRequestPreparer().prepare(
        RawApplicationCrawlRequest("https://example.com", overrides=overrides)
    )
    assert not result.report.valid
    issue = result.report.errors[0]
    assert issue.code in {
        ValidationIssueCode.OVERRIDE_ABOVE_MAXIMUM,
        ValidationIssueCode.OVERRIDE_BELOW_MINIMUM,
    }
    assert issue.supplied_value is not None


def test_valid_override_is_applied_without_mutating_profile() -> None:
    before = profile_for(CrawlProfileName.STANDARD_CRAWL)
    result = ApplicationRequestPreparer().prepare(
        RawApplicationCrawlRequest(
            "https://example.com",
            overrides=CrawlLimitOverrides(maximum_urls=123),
        )
    )
    after = profile_for(CrawlProfileName.STANDARD_CRAWL)
    assert result.prepared is not None
    assert result.prepared.run_request.crawl_request.maximum_unique_urls == 123
    assert before == after


def test_service_specific_maxima_are_enforced_without_weakening_absolute_maxima() -> None:
    lower = ApplicationCrawlLimits(50, 3, 60, 25_000_000, 2, 500, 0.5, 5, 2_000_000)
    preparer = ApplicationRequestPreparer(lower)
    accepted = preparer.prepare(
        RawApplicationCrawlRequest(
            "https://example.com",
            crawl_profile=CrawlProfileName.QUICK_AUDIT,
            overrides=CrawlLimitOverrides(maximum_urls=50),
        )
    )
    rejected = preparer.prepare(
        RawApplicationCrawlRequest(
            "https://example.com",
            crawl_profile=CrawlProfileName.QUICK_AUDIT,
            overrides=CrawlLimitOverrides(maximum_urls=51),
        )
    )
    assert accepted.report.valid
    assert not rejected.report.valid

    too_high = ApplicationCrawlLimits(
        50_001, 50, 7_200, 5_000_000_000, 16, 100_000, 0.1, 20, 50_000_000
    )
    with pytest.raises(ValueError):
        validate_application_maxima(too_high)


def test_stage_dependency_and_unknown_profiles_are_typed() -> None:
    invalid_stage = (
        ApplicationRequestPreparer()
        .prepare(
            RawApplicationCrawlRequest(
                "https://example.com",
                recommendation_requested=False,
                xml_generation_requested=True,
            )
        )
        .report
    )
    invalid_profile = (
        ApplicationRequestPreparer()
        .prepare(RawApplicationCrawlRequest("https://example.com", crawl_profile="unlimited"))
        .report
    )
    assert ValidationIssueCode.INVALID_STAGE_DEPENDENCY in {
        item.code for item in invalid_stage.errors
    }
    assert ValidationIssueCode.UNSUPPORTED_PROFILE in {item.code for item in invalid_profile.errors}


def test_publication_summary_and_strict_recommendation_configuration(tmp_path: Path) -> None:
    request = RawApplicationCrawlRequest(
        "https://example.com",
        recommendation_profile=RecommendationProfile.STRICT,
        publication_requested=True,
        publication_dry_run=True,
        publication_root=tmp_path,
        summary_writing_requested=True,
        summary_root=tmp_path,
        existing_file_policy=ExistingFilePolicy.OVERWRITE,
        caller_label="operator",
    )
    prepared = ApplicationRequestPreparer().prepare(request)
    assert prepared.report.valid and prepared.prepared is not None
    run = prepared.prepared.run_request
    assert run.requested_stages == (
        RunStage.CRAWL,
        RunStage.RECOMMEND,
        RunStage.GENERATE_XML,
        RunStage.PUBLISH,
        RunStage.WRITE_SUMMARY,
    )
    assert run.recommendation_policy.missing_canonical_requires_review
    assert run.caller_label == "operator"
    assert ValidationIssueCode.PUBLICATION_OVERWRITE_ENABLED in {
        item.code for item in prepared.report.warnings
    }


def test_missing_roots_and_invalid_caller_are_typed() -> None:
    report = (
        ApplicationRequestPreparer()
        .prepare(
            RawApplicationCrawlRequest(
                "https://example.com",
                publication_requested=True,
                summary_writing_requested=True,
                caller_label=" ",
            )
        )
        .report
    )
    codes = {item.code for item in report.errors}
    assert ValidationIssueCode.PUBLICATION_ROOT_MISSING in codes
    assert ValidationIssueCode.SUMMARY_ROOT_MISSING in codes
    assert ValidationIssueCode.INVALID_CALLER_LABEL in codes


def test_validation_order_is_error_warning_info_and_deterministic() -> None:
    raw = RawApplicationCrawlRequest(
        "invalid",
        crawl_profile=CrawlProfileName.DEEP_CRAWL,
        scope_profile=ScopeProfile.INCLUDE_SUBDOMAINS,
    )
    first = ApplicationRequestPreparer().prepare(raw).report
    second = ApplicationRequestPreparer().prepare(raw).report
    order = [item.severity for item in first.issues]
    assert order == sorted(
        order,
        key=(ValidationSeverity.ERROR, ValidationSeverity.WARNING, ValidationSeverity.INFO).index,
    )
    assert first == second


def test_preparation_has_no_filesystem_side_effect(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    result = ApplicationRequestPreparer().prepare(
        RawApplicationCrawlRequest(
            "https://example.com",
            publication_requested=True,
            publication_root=missing,
            create_publication_directory=True,
        )
    )
    assert result.report.valid
    assert not missing.exists()


def test_versions_configuration_and_capabilities_are_exact() -> None:
    assert APPLICATION_SERVICE_VERSION == "seo-toolkit-application-service-v1"
    assert DIAGNOSTICS_SCHEMA_VERSION == "seo-toolkit-diagnostics-v1"
    assert tuple(capability_report().supported) == tuple(SupportedCapability)
    assert tuple(capability_report().unsupported) == tuple(UnsupportedCapability)
    with pytest.raises(ValueError):
        ApplicationServiceConfiguration(APPLICATION_HARD_MAXIMA, application_service_version="v2")
    assert set(SupportedCapability).isdisjoint(set(UnsupportedCapability))
    assert tuple(ReadinessState) == (
        ReadinessState.READY,
        ReadinessState.DEGRADED,
        ReadinessState.NOT_READY,
    )


def test_json_and_markdown_diagnostics_are_deterministic_safe_and_hashed(
    tmp_path: Path,
) -> None:
    report = (
        ApplicationRequestPreparer()
        .prepare(RawApplicationCrawlRequest("https://example.com"))
        .report
    )
    json_first = serialize_json(report)
    json_second = serialize_json(report)
    markdown = serialize_markdown(report, "Validation Report")
    assert json_first == json_second
    assert json_first.content.endswith(b"\n")
    assert b'"diagnostics_schema_version": "seo-toolkit-diagnostics-v1"' in json_first.content
    assert markdown.content.startswith(b"# Validation Report\n")
    assert markdown.content.endswith(b"\n")
    assert str(tmp_path).encode() not in json_first.content + markdown.content
    assert json_first.byte_count == len(json_first.content)
    assert json_first.sha256 == hashlib.sha256(json_first.content).hexdigest()
