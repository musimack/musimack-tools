"""Direct production behavior coverage for Phase 26 analysis."""

# ruff: noqa: ANN401, PLR0913

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from musimack_tools.domain.migration_qa import (
    MAPPING_METHODS,
    RECOMMENDATION_ACTIONS,
    MigrationQaConfiguration,
    stable_json,
)
from musimack_tools.migration_qa.analysis import (
    _ACTION_BY_CODE,
    _add_sitewide_findings,
    _build_recommendations,
    analyze_migration,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def project(*, source_origin: str | None = "https://old.example") -> dict[str, Any]:
    return {
        "project_id": "project-1",
        "source_origin": source_origin,
        "destination_origin": "https://www.example",
        "destination_run_id": "destination-run",
        "source_run_id": "source-run",
        "updated_at": NOW,
    }


def source(
    sequence: int = 0,
    url: str = "https://old.example/a",
    destination: str | None = None,
    diagnostics: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "id": f"source-{sequence}",
        "project_id": "project-1",
        "sequence": sequence,
        "raw_url": url,
        "normalized_url": url,
        "comparison_url": url,
        "proposed_destination_url": destination,
        "source_kind": "inventory",
        "state": "valid",
        "diagnostics_json": stable_json(diagnostics),
        "created_at": NOW,
    }


def redirect(
    sequence: int = 0,
    source_url: str = "https://old.example/a",
    destination_url: str = "https://www.example/a",
    status: int | None = 301,
    diagnostics: tuple[str, ...] = (),
    state: str = "valid",
) -> dict[str, Any]:
    return {
        "id": f"redirect-{sequence}",
        "project_id": "project-1",
        "sequence": sequence,
        "raw_source_url": source_url,
        "raw_destination_url": destination_url,
        "normalized_source_url": source_url.split("#", 1)[0],
        "normalized_destination_url": destination_url.split("#", 1)[0],
        "expected_status": status,
        "state": state,
        "diagnostics_json": stable_json(diagnostics),
        "created_at": NOW,
    }


def page(url: str, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "evidence_id": "evidence-" + url.rsplit("/", 1)[-1],
        "requested_url": url,
        "final_url": url,
        "http_status": 200,
        "redirect_count": 0,
        "redirect_loop": False,
        "redirect_truncated": False,
        "redirects": (),
        "content_type": "text/html",
        "content_type_category": "html",
        "title_presence": "single",
        "title_value": "Useful page",
        "title_normalized_hash": "title-a",
        "description_presence": "single",
        "description_value": "Useful description",
        "description_normalized_hash": "description-a",
        "canonical_presence": "single",
        "canonical_url": url,
        "canonical_conflicting": False,
        "meta_robots_json": "[]",
        "x_robots_json": "[]",
        "robots_allowed": True,
        "robots_reason_code": None,
        "indexability_state": "indexable",
        "language": "en",
    }
    values.update(overrides)
    return values


def analyze(
    *,
    sources: tuple[dict[str, Any], ...] | None = None,
    redirects: tuple[dict[str, Any], ...] = (),
    destination_pages: tuple[dict[str, Any], ...] = (),
    source_pages: tuple[dict[str, Any], ...] = (),
    links: tuple[dict[str, Any], ...] = (),
    source_links: tuple[dict[str, Any], ...] = (),
    sitemaps: tuple[dict[str, Any], ...] = (),
    images: tuple[dict[str, Any], ...] = (),
    source_images: tuple[dict[str, Any], ...] = (),
    structured: tuple[dict[str, Any], ...] = (),
    source_structured: tuple[dict[str, Any], ...] = (),
    configuration: MigrationQaConfiguration | None = None,
    source_origin: str | None = "https://old.example",
) -> dict[str, list[dict[str, Any]]]:
    return analyze_migration(
        project(source_origin=source_origin),
        configuration or MigrationQaConfiguration(enabled=True),
        sources or (source(),),
        redirects,
        destination_pages,
        source_pages,
        links,
        source_links,
        sitemaps,
        images,
        source_images,
        structured,
        source_structured,
    )


def codes(result: dict[str, list[dict[str, Any]]]) -> set[str]:
    return {str(item["code"]) for item in result["findings"]}


@pytest.mark.parametrize(
    ("method", "sources", "redirects", "destination_pages", "source_pages", "source_origin"),
    [
        (
            "explicit_redirect_map",
            (source(),),
            (redirect(),),
            (page("https://www.example/a"),),
            (),
            "https://old.example",
        ),
        (
            "explicit_proposed_destination",
            (source(destination="https://www.example/a"),),
            (),
            (page("https://www.example/a"),),
            (),
            "https://old.example",
        ),
        (
            "observed_redirect",
            (source(),),
            (),
            (page("https://www.example/a"),),
            (page("https://old.example/a", final_url="https://www.example/a"),),
            None,
        ),
        (
            "exact_normalized_url",
            (source(url="https://www.example/a"),),
            (),
            (page("https://www.example/a"),),
            (),
            None,
        ),
        (
            "configured_origin_substitution",
            (source(),),
            (),
            (page("https://www.example/a"),),
            (),
            "https://old.example",
        ),
        ("path_match", (source(),), (), (page("https://www.example/a"),), (), None),
        (
            "canonical_hint",
            (source(),),
            (),
            (page("https://www.example/different", canonical_url=None),),
            (page("https://old.example/a", canonical_url="https://www.example/different"),),
            None,
        ),
        (
            "content_similarity_hint",
            (source(),),
            (),
            (page("https://www.example/different", canonical_url=None),),
            (page("https://old.example/a", canonical_url=None),),
            None,
        ),
        (
            "manual_review_candidate",
            (source(),),
            (
                redirect(0, destination_url="https://www.example/a"),
                redirect(1, destination_url="https://www.example/b"),
            ),
            (page("https://www.example/a"), page("https://www.example/b")),
            (),
            None,
        ),
        ("unmapped", (source(),), (), (), (), None),
    ],
)
def test_every_mapping_method_is_reached_by_production_analysis(
    method: str,
    sources: tuple[dict[str, Any], ...],
    redirects: tuple[dict[str, Any], ...],
    destination_pages: tuple[dict[str, Any], ...],
    source_pages: tuple[dict[str, Any], ...],
    source_origin: str | None,
) -> None:
    result = analyze(
        sources=sources,
        redirects=redirects,
        destination_pages=destination_pages,
        source_pages=source_pages,
        source_origin=source_origin,
    )
    assert result["mappings"][0]["mapping_method"] == method
    assert result["mappings"][0]["mapping_method"] in MAPPING_METHODS


def test_mapping_cardinality_collision_and_ambiguity_are_not_autoaccepted() -> None:
    many = analyze(
        sources=(
            source(0, "https://old.example/a", "https://www.example/shared"),
            source(1, "https://old.example/b", "https://www.example/shared"),
        ),
        destination_pages=(page("https://www.example/shared"),),
    )
    assert {item["cardinality"] for item in many["mappings"]} == {"many_to_one"}
    assert {
        "mapping_many_to_one",
        "mapping_destination_collision",
        "redirect_many_to_one_review",
        "content_consolidated",
    } <= codes(many)
    ambiguous = analyze(
        redirects=(
            redirect(0, destination_url="https://www.example/a"),
            redirect(1, destination_url="https://www.example/b"),
        ),
        destination_pages=(page("https://www.example/a"), page("https://www.example/b")),
        source_origin=None,
    )
    mapping = ambiguous["mappings"][0]
    assert mapping["state"] == "ambiguous"
    assert mapping["cardinality"] == "one_to_many"
    assert mapping["destination_url"] is None
    assert mapping["confidence"] == "low"
    assert {
        "mapping_ambiguous",
        "mapping_one_to_many",
        "mapping_conflicting_explicit",
        "redirect_one_to_many_review",
        "content_split_review",
    } <= codes(ambiguous)

    competing_hints = analyze(
        destination_pages=(
            page("https://www.example/a", title_normalized_hash="destination-a"),
            page("https://www.example/b", title_normalized_hash="destination-b"),
        ),
        source_pages=(
            page(
                "https://old.example/a",
                canonical_url="https://www.example/b",
                title_normalized_hash="source",
            ),
        ),
        source_origin=None,
    )
    assert competing_hints["mappings"][0]["cardinality"] == "ambiguous"
    assert competing_hints["mappings"][0]["destination_url"] is None


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (None, "destination_status_unknown"),
        (404, "destination_404"),
        (410, "destination_410"),
        (403, "destination_other_4xx"),
        (500, "destination_5xx"),
        (302, "destination_redirecting"),
    ],
)
def test_detailed_destination_status_emission_and_nearby_200_non_emission(
    status: int | None, expected: str
) -> None:
    result = analyze(
        redirects=(redirect(),),
        destination_pages=(page("https://www.example/a", http_status=status),),
    )
    assert expected in codes(result)
    valid = analyze(redirects=(redirect(),), destination_pages=(page("https://www.example/a"),))
    assert expected not in codes(valid)


def test_redirect_verification_emits_observed_boundaries_without_treating_plan_as_observation() -> (
    None
):
    observed = page(
        "https://old.example/a",
        final_url="https://www.example/wrong",
        http_status=302,
        redirect_count=2,
        redirect_loop=True,
        redirects=(
            {"sequence": 0, "status": 302, "target_url": "https://www.example/hop"},
            {"sequence": 1, "status": 301, "target_url": "https://www.example/wrong"},
        ),
    )
    result = analyze(
        redirects=(redirect(status=301),),
        destination_pages=(
            observed,
            page(
                "https://www.example/a",
                http_status=500,
                indexability_state="non_indexable",
            ),
        ),
    )
    assert {
        "redirect_wrong_destination",
        "redirect_temporary",
        "redirect_chain",
        "redirect_loop",
        "redirect_status_mismatch",
        "redirect_to_error",
        "redirect_to_nonindexable",
    } <= codes(result)
    observation = result["redirects"][0]
    assert observation["hop_count"] == 2
    assert observation["chain_identity"]
    assert observation["loop_identity"]
    missing = analyze(redirects=(redirect(),), destination_pages=(page("https://www.example/a"),))
    assert "redirect_missing" in codes(missing)
    assert missing["redirects"][0]["state"] == "missing"


def test_redirect_query_fragment_scope_and_cardinality_findings() -> None:
    result = analyze(
        sources=(source(url="https://old.example/a?x=1"),),
        redirects=(
            redirect(
                source_url="https://old.example/a?x=1#old",
                destination_url="https://external.example/a#new",
            ),
        ),
        destination_pages=(page("https://external.example/a"),),
        configuration=MigrationQaConfiguration(
            enabled=True, compare_fragments=True, preserve_query_parameters=True
        ),
    )
    assert {
        "redirect_to_external",
        "redirect_query_dropped",
        "redirect_fragment_policy_mismatch",
    } <= codes(result)

    unexpected = analyze(
        sources=(source(),),
        redirects=(redirect(destination_url="https://www.example/a?unexpected=1"),),
        destination_pages=(page("https://www.example/a?unexpected=1"),),
        configuration=MigrationQaConfiguration(enabled=True, preserve_query_parameters=False),
    )
    assert "redirect_query_unexpectedly_preserved" in codes(unexpected)

    out_of_scope = analyze(
        sources=(source(),),
        redirects=(redirect(destination_url="https://old.example/elsewhere"),),
        destination_pages=(page("https://old.example/elsewhere"),),
    )
    assert "redirect_to_out_of_scope" in codes(out_of_scope)


def test_destination_technical_states_and_valid_non_emission() -> None:
    result = analyze(
        redirects=(redirect(),),
        destination_pages=(
            page(
                "https://www.example/a",
                content_type="application/pdf",
                content_type_category="pdf",
                indexability_state="non_indexable",
                robots_allowed=False,
                canonical_presence="multiple",
                canonical_conflicting=True,
            ),
        ),
    )
    assert {
        "destination_non_html",
        "destination_noindex",
        "destination_blocked_by_robots",
        "destination_canonical_invalid",
    } <= codes(result)
    valid = analyze(redirects=(redirect(),), destination_pages=(page("https://www.example/a"),))
    assert not (
        {
            "destination_non_html",
            "destination_noindex",
            "destination_blocked_by_robots",
            "destination_canonical_invalid",
        }
        & codes(valid)
    )

    missing = analyze(sources=(source(destination="https://www.example/missing"),))
    assert {"destination_missing", "content_missing"} <= codes(missing)

    elsewhere = analyze(
        sources=(source(destination="https://www.example/a"),),
        destination_pages=(
            page(
                "https://www.example/a",
                canonical_url="https://www.example/canonical",
            ),
            page("https://www.example/canonical", redirect_count=1, http_status=404),
        ),
    )
    assert {
        "destination_canonical_elsewhere",
        "canonical_points_to_redirect",
        "canonical_points_to_error",
        "canonical_regression",
    } <= codes(elsewhere)

    canonical_missing = analyze(
        sources=(source(destination="https://www.example/a"),),
        destination_pages=(page("https://www.example/a", canonical_presence="missing"),),
    )
    assert "destination_canonical_missing" in codes(canonical_missing)


def test_metadata_content_canonical_and_indexability_continuity() -> None:
    source_page = page("https://old.example/a")
    destination_page = page(
        "https://www.example/a",
        title_presence="missing",
        title_value=None,
        title_normalized_hash=None,
        description_value="Entirely unrelated metadata",
        description_normalized_hash="description-b",
        canonical_url="https://old.example/a",
        meta_robots_json='["noindex"]',
        indexability_state="non_indexable",
        robots_allowed=False,
        content_type="application/pdf",
        content_type_category="pdf",
        language="fr",
    )
    result = analyze(
        redirects=(redirect(),),
        destination_pages=(destination_page,),
        source_pages=(source_page,),
    )
    assert {
        "title_missing_after_migration",
        "meta_description_materially_changed",
        "robots_regression",
        "indexability_regression",
        "content_type_changed",
        "language_changed",
        "content_materially_changed",
        "content_similarity_low",
        "canonical_points_to_legacy_url",
        "canonical_points_to_wrong_host",
        "canonical_self_reference_regression",
        "canonical_conflicts_with_redirect",
        "destination_noindex_regression",
        "destination_robots_block_regression",
    } <= codes(result)
    assert result["comparisons"][0]["similarity_score"]


def test_preserved_metadata_and_content_emit_no_regressions() -> None:
    source_page = page("https://old.example/a", canonical_url="https://www.example/a")
    destination_page = page("https://www.example/a")
    result = analyze(
        redirects=(redirect(),),
        destination_pages=(destination_page,),
        source_pages=(source_page,),
    )
    assert "content_likely_preserved" in codes(result)
    assert not (
        {"title_materially_changed", "indexability_regression", "content_materially_changed"}
        & codes(result)
    )


def test_canonical_target_change_is_compared_independently_from_other_metadata() -> None:
    result = analyze(
        redirects=(redirect(),),
        source_pages=(page("https://old.example/a", canonical_url="https://www.example/a"),),
        destination_pages=(
            page("https://www.example/a", canonical_url="https://www.example/other"),
        ),
    )
    assert "canonical_target_changed" in codes(result)


def test_missing_source_evidence_and_missing_destination_description_are_explicit() -> None:
    no_source = analyze(
        redirects=(redirect(),),
        destination_pages=(page("https://www.example/a"),),
    )
    assert {"source_metadata_unavailable", "content_similarity_indeterminate"} <= codes(no_source)

    missing_description = analyze(
        redirects=(redirect(),),
        source_pages=(page("https://old.example/a"),),
        destination_pages=(
            page(
                "https://www.example/a",
                description_presence="missing",
                description_value=None,
                description_normalized_hash=None,
            ),
        ),
    )
    assert "meta_description_missing_after_migration" in codes(missing_description)


def test_retained_indexable_legacy_page_and_destination_are_flagged_without_index_claims() -> None:
    result = analyze(
        redirects=(redirect(),),
        source_pages=(page("https://old.example/a"),),
        destination_pages=(
            page("https://old.example/a"),
            page("https://www.example/a"),
        ),
    )
    assert {
        "legacy_url_still_indexable",
        "duplicate_source_and_destination_indexable",
    } <= codes(result)


def test_internal_link_migration_findings_and_valid_link_boundary() -> None:
    links = (
        {
            "link_id": "link-legacy",
            "source_requested_url": "https://www.example/a",
            "resolved_url": "https://old.example/a",
            "internal": True,
        },
        {
            "link_id": "link-stage",
            "source_requested_url": "https://www.example/a",
            "resolved_url": "https://staging.example/a",
            "internal": True,
        },
        {
            "link_id": "link-broken",
            "source_requested_url": "https://www.example/a",
            "resolved_url": "https://www.example/broken",
            "internal": True,
        },
        {
            "link_id": "link-valid",
            "source_requested_url": "https://www.example/a",
            "resolved_url": "https://www.example/a",
            "internal": True,
        },
        {
            "link_id": "link-unmapped",
            "source_requested_url": "https://www.example/a",
            "resolved_url": "https://elsewhere.example/unmapped",
            "internal": True,
        },
    )
    result = analyze(
        sources=(
            source(destination="https://www.example/a"),
            source(1, "https://old.example/unmapped"),
            source(2, "https://elsewhere.example/unmapped"),
        ),
        destination_pages=(
            page("https://www.example/a"),
            page("https://www.example/broken", http_status=404),
        ),
        links=links,
        source_links=(
            {"link_id": "source-dropped", "resolved_url": "https://old.example/dropped"},
        ),
        configuration=MigrationQaConfiguration(enabled=True, compare_internal_links=True),
    )
    assert {
        "internal_link_to_legacy_url",
        "internal_link_to_redirect",
        "internal_link_to_staging_host",
        "internal_link_host_mismatch",
        "internal_link_to_broken_destination",
        "navigation_target_regression",
        "destination_orphan_candidate",
        "redirect_dependency_sitewide",
        "source_link_target_unmapped",
    } <= codes(result)


def test_sitemap_findings_and_disabled_non_emission() -> None:
    rows = (
        {"entry_id": "s1", "normalized_identity": "https://old.example/a"},
        {"entry_id": "s2", "normalized_identity": "https://www.example/broken"},
        {"entry_id": "s3", "normalized_identity": "https://external.example/x"},
    )
    result = analyze(
        sources=(source(destination="https://www.example/a"),),
        destination_pages=(
            page("https://www.example/a"),
            page(
                "https://www.example/broken",
                http_status=404,
                redirect_count=1,
                indexability_state="non_indexable",
                canonical_url="https://www.example/other",
            ),
        ),
        sitemaps=rows,
        configuration=MigrationQaConfiguration(enabled=True, compare_sitemaps=True),
    )
    assert {
        "legacy_url_in_destination_sitemap",
        "destination_url_missing_from_sitemap",
        "redirecting_url_in_sitemap",
        "broken_url_in_sitemap",
        "nonindexable_url_in_sitemap",
        "canonical_conflict_in_sitemap",
        "sitemap_host_mismatch",
    } <= codes(result)
    disabled = analyze(sitemaps=rows)
    assert not {code for code in codes(disabled) if code.endswith("_sitemap") or "sitemap" in code}


def test_missing_enabled_sitemap_evidence_is_explicit() -> None:
    result = analyze(configuration=MigrationQaConfiguration(enabled=True, compare_sitemaps=True))
    assert "sitemap_evidence_unavailable" in codes(result)


def test_image_continuity_findings_use_exact_identity_without_perceptual_matching() -> None:
    source_rows = (
        {
            "image_id": "source-image",
            "source_requested_url": "https://old.example/a",
            "source_final_url": "https://old.example/a",
            "image_identity": "image-a",
            "alt_present": True,
            "alt_normalized": "Old alt",
            "width_value": "100",
            "height_value": "100",
            "loading_value": "eager",
        },
        {
            "image_id": "missing-image",
            "source_requested_url": "https://old.example/a",
            "source_final_url": "https://old.example/a",
            "image_identity": "image-missing",
            "alt_present": True,
        },
    )
    destination_rows = (
        {
            "image_id": "destination-image",
            "source_requested_url": "https://www.example/a",
            "source_final_url": "https://www.example/a",
            "image_identity": "image-a",
            "resolved_src": "https://old.example/image.png",
            "alt_present": False,
            "alt_normalized": None,
            "width_value": "200",
            "height_value": "100",
            "loading_value": "lazy",
            "resource": {
                "http_status": 404,
                "broken_occurrence_count": 1,
                "redirecting_occurrence_count": 1,
                "redirect_state": "redirected",
            },
        },
        {
            "image_id": "stage-image",
            "source_requested_url": "https://www.example/a",
            "source_final_url": "https://www.example/a",
            "image_identity": "stage",
            "resolved_src": "https://staging.example/image.png",
            "alt_present": True,
        },
    )
    result = analyze(
        sources=(source(destination="https://www.example/a"),),
        destination_pages=(page("https://www.example/a"),),
        images=destination_rows,
        source_images=source_rows,
        configuration=MigrationQaConfiguration(enabled=True, compare_images=True),
    )
    assert {
        "image_missing_after_migration",
        "image_broken_after_migration",
        "image_legacy_host_reference",
        "image_staging_host_reference",
        "image_alt_missing_after_migration",
        "image_alt_materially_changed",
        "image_redirect_dependency",
        "image_dimension_regression",
        "image_loading_regression",
    } - {"image_alt_materially_changed"} <= codes(result)

    changed_alt = analyze(
        sources=(source(destination="https://www.example/a"),),
        destination_pages=(page("https://www.example/a"),),
        source_images=(
            {
                "image_id": "source-alt",
                "source_final_url": "https://old.example/a",
                "image_identity": "shared-image",
                "alt_present": True,
                "alt_normalized": "Original alt",
            },
        ),
        images=(
            {
                "image_id": "destination-alt",
                "source_final_url": "https://www.example/a",
                "image_identity": "shared-image",
                "alt_present": True,
                "alt_normalized": "Materially different alt",
            },
        ),
        configuration=MigrationQaConfiguration(enabled=True, compare_images=True),
    )
    assert "image_alt_materially_changed" in codes(changed_alt)


def test_structured_data_continuity_and_format_only_review() -> None:
    source_rows = (
        {
            "block_id": "source-block",
            "source_requested_url": "https://old.example/a",
            "source_final_url": "https://old.example/a",
            "parse_status": "parsed",
            "types_json": '["Article"]',
            "identifiers_json": '["entity-1"]',
            "format": "json_ld",
        },
        {
            "block_id": "removed-block",
            "source_requested_url": "https://old.example/missing",
            "source_final_url": "https://old.example/missing",
            "parse_status": "parsed",
            "types_json": '["Product"]',
            "identifiers_json": '["product-1"]',
            "format": "json_ld",
        },
    )
    destination_rows = (
        {
            "block_id": "destination-block",
            "source_requested_url": "https://www.example/a",
            "source_final_url": "https://www.example/a",
            "parse_status": "error",
            "parse_error": "invalid",
            "types_json": '["NewsArticle"]',
            "identifiers_json": '["entity-1","entity-2"]',
            "format": "microdata",
        },
    )
    result = analyze(
        sources=(
            source(destination="https://www.example/a"),
            source(1, "https://old.example/missing", "https://www.example/missing"),
        ),
        destination_pages=(page("https://www.example/a", indexability_state="non_indexable"),),
        structured=destination_rows,
        source_structured=source_rows,
        configuration=MigrationQaConfiguration(enabled=True, compare_structured_data=True),
    )
    assert {
        "structured_data_removed",
        "structured_data_type_changed",
        "structured_data_entity_id_changed",
        "structured_data_identity_conflict",
        "structured_data_profile_regression",
        "structured_data_invalid_after_migration",
        "structured_data_nonindexable_destination",
        "structured_data_format_changed",
    } <= codes(result)
    format_finding = next(
        item for item in result["findings"] if item["code"] == "structured_data_format_changed"
    )
    assert format_finding["severity"] == "info"
    assert format_finding["requires_human_review"]


def test_sitewide_threshold_reached_below_threshold_and_small_inventory_safeguard() -> None:
    sources = tuple(source(index, f"https://old.example/{index}") for index in range(10))
    reached = analyze(
        sources=sources,
        configuration=MigrationQaConfiguration(
            enabled=True, minimum_sitewide_pages=10, sitewide_issue_ratio=0.2
        ),
        source_origin=None,
    )
    assert "sitewide_unmapped_source_urls" in codes(reached)
    small = analyze(
        sources=sources[:2],
        configuration=MigrationQaConfiguration(
            enabled=True, minimum_sitewide_pages=10, sitewide_issue_ratio=0.2
        ),
        source_origin=None,
    )
    assert "sitewide_unmapped_source_urls" not in codes(small)
    assert {item["state"] for item in small["sitewide"]} == {"small_inventory"}
    below = analyze(
        sources=tuple(
            source(index, f"https://old.example/{index}", f"https://www.example/{index}")
            for index in range(10)
        ),
        destination_pages=tuple(page(f"https://www.example/{index}") for index in range(10)),
    )
    assert "sitewide_unmapped_source_urls" not in codes(below)


@pytest.mark.parametrize(
    ("source_code", "sitewide_code"),
    [
        ("internal_link_to_legacy_url", "sitewide_legacy_host_references"),
        ("internal_link_to_staging_host", "sitewide_staging_host_references"),
        ("internal_link_to_redirect", "sitewide_redirect_dependency"),
        ("redirect_chain", "sitewide_redirect_chain_pattern"),
        ("redirect_temporary", "sitewide_temporary_redirect_pattern"),
        ("destination_noindex_regression", "sitewide_noindex_regression"),
        ("canonical_points_to_wrong_host", "sitewide_canonical_host_mismatch"),
        ("title_missing_after_migration", "sitewide_metadata_loss"),
        ("destination_url_missing_from_sitemap", "sitewide_sitemap_regression"),
        ("structured_data_removed", "sitewide_structured_data_loss"),
        ("image_legacy_host_reference", "sitewide_image_host_regression"),
        ("mapping_unmapped", "sitewide_unmapped_source_urls"),
        ("destination_404", "sitewide_destination_errors"),
    ],
)
def test_every_sitewide_pattern_emits_at_the_explicit_threshold(
    source_code: str, sitewide_code: str
) -> None:
    resources: dict[str, list[dict[str, Any]]] = {
        "findings": [{"code": source_code}, {"code": source_code}],
        "mappings": [
            {"project_id": "project-1", "created_at": NOW},
        ],
        "sitewide": [],
    }
    emitted: list[str] = []

    def record(code: str, **_kwargs: Any) -> None:
        emitted.append(code)

    _add_sitewide_findings(
        resources,
        10,
        MigrationQaConfiguration(
            enabled=True,
            minimum_sitewide_pages=10,
            sitewide_issue_ratio=0.2,
        ),
        record,
    )
    assert sitewide_code in emitted


@pytest.mark.parametrize("action", sorted(RECOMMENDATION_ACTIONS))
def test_every_recommendation_action_is_generated_by_the_production_aggregator(action: str) -> None:
    code = next(code for code, mapped_action in _ACTION_BY_CODE.items() if mapped_action == action)
    resources: dict[str, list[dict[str, Any]]] = {
        "findings": [
            {
                "stable_id": "finding-1",
                "code": code,
                "category": "redirect",
                "severity": "warning",
                "confidence": "medium",
                "requires_human_review": True,
                "mapping_id": "mapping-1",
                "source_url": "https://old.example/a",
                "destination_url": "https://www.example/a",
                "bounded_evidence_json": "{}",
                "occurrence_count": 2,
                "affected_page_count": 1,
                "created_at": NOW,
            }
        ],
        "recommendations": [],
    }
    _build_recommendations("project-1", resources)
    recommendation = resources["recommendations"][0]
    assert recommendation["action"] == action
    assert recommendation["confidence"] == "medium"
    assert recommendation["scope"] == "page"
    assert recommendation["supporting_finding_ids_json"] == '["finding-1"]'
    assert recommendation["occurrence_count"] == 2


def test_semantic_confidence_ranking_is_not_lexical() -> None:
    resources: dict[str, list[dict[str, Any]]] = {
        "findings": [
            {
                "stable_id": f"finding-{confidence}",
                "code": "redirect_missing",
                "category": "redirect",
                "severity": "warning",
                "confidence": confidence,
                "requires_human_review": False,
                "mapping_id": "mapping-1",
                "source_url": None,
                "destination_url": None,
                "bounded_evidence_json": "{}",
                "occurrence_count": 1,
                "affected_page_count": 1,
                "created_at": NOW,
            }
            for confidence in ("high", "low", "medium")
        ],
        "recommendations": [],
    }
    _build_recommendations("project-1", resources)
    assert resources["recommendations"][0]["confidence"] == "low"
