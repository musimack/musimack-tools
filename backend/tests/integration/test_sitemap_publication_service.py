"""End-to-end internal sitemap generation and local publication composition tests."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from musimack_tools.domain.sitemap import (
    CanonicalSummary,
    GenericIndexabilitySummary,
    RecommendationConfigurationSnapshot,
    RecommendationDeterminacy,
    RecommendationState,
    RedirectSummary,
    RobotsPermissionSummary,
    SitemapReasonCode,
    SitemapRecommendation,
    SitemapRecommendationProjection,
)
from musimack_tools.domain.sitemap_orchestration import (
    SitemapGenerationState,
    SitemapOrchestrationRequest,
)
from musimack_tools.domain.sitemap_publication import (
    SITEMAP_PUBLICATION_MANIFEST_VERSION,
    SITEMAP_PUBLICATION_VERSION,
    ExistingFilePolicy,
    PlannedPublicationFile,
    PublicationFailureCode,
    PublicationMode,
    PublicationState,
    SitemapPublicationConfiguration,
)
from musimack_tools.sitemap.limits import SitemapXmlConfiguration
from musimack_tools.sitemap.publication import (
    AtomicWriteError,
    LocalAtomicWriter,
    SitemapPublicationExecutor,
)
from musimack_tools.sitemap.service import SitemapPublicationService

if TYPE_CHECKING:
    from pathlib import Path


def _recommendation(
    url: str,
    state: RecommendationState = RecommendationState.INCLUDE,
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
        metadata_warnings=(),
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
            rule_set_version="sitemap-eligibility-v1",
        ),
        rule_set_version="sitemap-eligibility-v1",
    )


def _request(
    projection: SitemapRecommendationProjection,
    *,
    xml: SitemapXmlConfiguration | None = None,
    publication: SitemapPublicationConfiguration | None = None,
) -> SitemapOrchestrationRequest:
    return SitemapOrchestrationRequest(
        recommendation_projection=projection,
        xml_configuration=xml or SitemapXmlConfiguration(),
        publication_configuration=publication,
    )


def test_generate_only_returns_not_requested_without_filesystem_plan() -> None:
    result = SitemapPublicationService().execute(
        _request(_projection(_recommendation("https://example.test/a")))
    )

    assert result.generation_state is SitemapGenerationState.GENERATED
    assert result.publication_result.state is PublicationState.NOT_REQUESTED
    assert result.publication_result.plan is None
    assert result.xml_bundle.total_entries == 1
    assert result.publication_version == SITEMAP_PUBLICATION_VERSION


def test_dry_run_composes_exact_package_without_writes(tmp_path: Path) -> None:
    configuration = SitemapPublicationConfiguration(tmp_path, mode=PublicationMode.DRY_RUN)
    result = SitemapPublicationService().execute(
        _request(
            _projection(_recommendation("https://example.test/café")),
            publication=configuration,
        )
    )

    assert result.publication_result.state is PublicationState.DRY_RUN
    assert result.publication_result.plan is not None
    assert [item.logical_name for item in result.publication_result.plan.files] == [
        "sitemap.xml",
        "sitemap-manifest.json",
    ]
    assert list(tmp_path.iterdir()) == []


def test_actual_publication_writes_xml_manifest_and_matching_hashes(tmp_path: Path) -> None:
    result = SitemapPublicationService().execute(
        _request(
            _projection(_recommendation("https://example.test/a")),
            publication=SitemapPublicationConfiguration(tmp_path),
        )
    )

    publication = result.publication_result
    assert publication.state is PublicationState.PUBLISHED
    assert publication.plan is not None
    manifest_value = json.loads((tmp_path / "sitemap-manifest.json").read_bytes())
    assert manifest_value["schema_version"] == SITEMAP_PUBLICATION_MANIFEST_VERSION
    assert manifest_value["files"][0]["sha256"] == publication.plan.files[0].sha256
    assert publication.manifest_sha256 == publication.plan.manifest_artifact.sha256


def test_mixed_states_and_duplicate_include_inherit_xml_filtering(tmp_path: Path) -> None:
    include = _recommendation("https://example.test/include")
    projection = _projection(
        include,
        _recommendation("https://example.test/exclude", RecommendationState.EXCLUDE),
        _recommendation("https://example.test/review", RecommendationState.REVIEW),
        _recommendation("https://example.test/unknown", RecommendationState.INDETERMINATE),
        include,
    )
    result = SitemapPublicationService().execute(
        _request(projection, publication=SitemapPublicationConfiguration(tmp_path))
    )

    assert result.xml_bundle.counts.unique_entries_emitted == 1
    assert result.xml_bundle.counts.skipped_non_include == 3
    assert result.xml_bundle.counts.duplicate_suppression_count == 1
    assert b"exclude" not in (tmp_path / "sitemap.xml").read_bytes()


def test_split_bundle_with_base_publishes_index_and_all_documents(tmp_path: Path) -> None:
    projection = _projection(
        _recommendation("https://example.test/a"),
        _recommendation("https://example.test/b"),
    )
    result = SitemapPublicationService().execute(
        _request(
            projection,
            xml=SitemapXmlConfiguration(
                url_entries_per_document_limit=1,
                sitemap_base_url="https://example.test/exports/",
            ),
            publication=SitemapPublicationConfiguration(tmp_path),
        )
    )

    assert result.publication_result.state is PublicationState.PUBLISHED
    assert {item.name for item in tmp_path.iterdir()} == {
        "sitemap-1.xml",
        "sitemap-2.xml",
        "sitemap-index.xml",
        "sitemap-manifest.json",
    }


def test_split_bundle_without_base_preserves_blockage_and_omits_index(tmp_path: Path) -> None:
    projection = _projection(
        _recommendation("https://example.test/a"),
        _recommendation("https://example.test/b"),
    )
    result = SitemapPublicationService().execute(
        _request(
            projection,
            xml=SitemapXmlConfiguration(url_entries_per_document_limit=1),
            publication=SitemapPublicationConfiguration(tmp_path),
        )
    )
    manifest = json.loads((tmp_path / "sitemap-manifest.json").read_bytes())

    assert result.publication_result.state is PublicationState.PUBLISHED
    assert result.xml_bundle.index_document is None
    assert manifest["index_blockage_codes"] == ["index_blocked_missing_base_url"]
    assert not (tmp_path / "sitemap-index.xml").exists()


def test_oversized_url_rejection_is_preserved_while_empty_sitemap_publishes(
    tmp_path: Path,
) -> None:
    prefix = "https://example.test/"
    url = f"{prefix}{'a' * (2_049 - len(prefix))}"
    result = SitemapPublicationService().execute(
        _request(
            _projection(_recommendation(url)),
            publication=SitemapPublicationConfiguration(tmp_path),
        )
    )
    assert result.xml_bundle.counts.rejected_entry_count == 1
    assert result.xml_bundle.total_entries == 0
    assert result.publication_result.state is PublicationState.PUBLISHED


def test_empty_projection_publishes_valid_empty_sitemap_package(tmp_path: Path) -> None:
    result = SitemapPublicationService().execute(
        _request(_projection(), publication=SitemapPublicationConfiguration(tmp_path))
    )
    assert result.xml_bundle.total_entries == 0
    assert b"<urlset" in (tmp_path / "sitemap.xml").read_bytes()
    assert result.publication_result.published_file_count == 2


def test_existing_file_blockage_is_preserved_without_partial_writes(tmp_path: Path) -> None:
    (tmp_path / "sitemap.xml").write_bytes(b"existing")
    result = SitemapPublicationService().execute(
        _request(
            _projection(_recommendation("https://example.test/a")),
            publication=SitemapPublicationConfiguration(tmp_path),
        )
    )
    assert result.publication_result.state is PublicationState.BLOCKED
    assert result.publication_result.failures[0].code is PublicationFailureCode.TARGET_EXISTS
    assert not (tmp_path / "sitemap-manifest.json").exists()


def test_overwrite_service_replaces_generated_files_only(tmp_path: Path) -> None:
    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_bytes(b"keep")
    (tmp_path / "sitemap.xml").write_bytes(b"old")
    configuration = SitemapPublicationConfiguration(
        tmp_path,
        existing_file_policy=ExistingFilePolicy.OVERWRITE,
    )
    result = SitemapPublicationService().execute(
        _request(
            _projection(_recommendation("https://example.test/a")),
            publication=configuration,
        )
    )
    assert result.publication_result.state is PublicationState.PUBLISHED
    assert unrelated.read_bytes() == b"keep"
    assert (tmp_path / "sitemap.xml").read_bytes() != b"old"


class _FailSecondWriter:
    def __init__(self) -> None:
        self.calls = 0
        self.local = LocalAtomicWriter()

    def write(self, planned_file: PlannedPublicationFile, policy: ExistingFilePolicy) -> None:
        self.calls += 1
        if self.calls == 2:
            raise AtomicWriteError(PublicationFailureCode.WRITE_FAILED)
        self.local.write(planned_file, policy)


def test_partial_failure_status_and_generation_evidence_remain_available(tmp_path: Path) -> None:
    service = SitemapPublicationService(SitemapPublicationExecutor(_FailSecondWriter()))
    result = service.execute(
        _request(
            _projection(_recommendation("https://example.test/a")),
            publication=SitemapPublicationConfiguration(tmp_path),
        )
    )

    assert result.generation_state is SitemapGenerationState.GENERATED
    assert result.xml_bundle.total_entries == 1
    assert result.publication_result.state is PublicationState.PARTIALLY_FAILED
    assert result.publication_result.published_file_count == 1
    assert result.publication_result.failures[0].code is PublicationFailureCode.WRITE_FAILED
