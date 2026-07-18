"""Evidence-bounded production analysis for website migrations."""

# ruff: noqa: ANN401, ARG001, C901, FBT001, PERF401, PLR0912, PLR0913, PLR0915, PLR2004

from __future__ import annotations

import json
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import urlsplit

from musimack_tools.domain.migration_qa import (
    MigrationQaConfiguration,
    classify_migration_finding,
    stable_identity,
    stable_json,
)

_ACTION_BY_CODE: dict[str, str] = {
    "redirect_missing": "add_missing_redirect",
    "redirect_wrong_destination": "correct_redirect_destination",
    "redirect_temporary": "replace_temporary_redirect",
    "redirect_chain": "shorten_redirect_chain",
    "redirect_loop": "resolve_redirect_loop",
    "redirect_to_error": "fix_redirect_to_error",
    "redirect_to_nonindexable": "remove_destination_noindex",
    "redirect_to_external": "correct_redirect_destination",
    "redirect_to_out_of_scope": "correct_redirect_destination",
    "redirect_status_mismatch": "correct_redirect_destination",
    "redirect_query_dropped": "review_query_string_policy",
    "redirect_query_unexpectedly_preserved": "review_query_string_policy",
    "redirect_fragment_policy_mismatch": "review_fragment_policy",
    "redirect_many_to_one_review": "review_many_to_one_mapping",
    "redirect_one_to_many_review": "review_one_to_many_mapping",
    "redirect_destination_collision": "resolve_mapping_conflict",
    "redirect_map_duplicate_source": "resolve_mapping_conflict",
    "redirect_map_conflicting_destination": "resolve_mapping_conflict",
    "redirect_map_loop": "resolve_redirect_loop",
    "redirect_map_chain": "shorten_redirect_chain",
    "redirect_map_invalid_url": "resolve_mapping_conflict",
    "mapping_unmapped": "map_unmatched_source_url",
    "mapping_ambiguous": "verify_manual_mapping",
    "mapping_many_to_one": "review_many_to_one_mapping",
    "mapping_one_to_many": "review_one_to_many_mapping",
    "mapping_destination_collision": "resolve_mapping_conflict",
    "mapping_conflicting_explicit": "resolve_mapping_conflict",
    "destination_missing": "restore_missing_destination_page",
    "destination_404": "restore_missing_destination_page",
    "destination_410": "restore_missing_destination_page",
    "destination_other_4xx": "fix_destination_error",
    "destination_5xx": "fix_destination_error",
    "destination_redirecting": "correct_redirect_destination",
    "destination_non_html": "fix_destination_error",
    "destination_noindex": "remove_destination_noindex",
    "destination_blocked_by_robots": "review_robots_block",
    "destination_canonical_elsewhere": "correct_destination_canonical",
    "destination_canonical_missing": "correct_destination_canonical",
    "destination_canonical_invalid": "correct_destination_canonical",
    "destination_status_unknown": "fix_destination_error",
    "title_missing_after_migration": "restore_missing_metadata",
    "meta_description_missing_after_migration": "restore_missing_metadata",
    "title_materially_changed": "review_material_metadata_change",
    "meta_description_materially_changed": "review_material_metadata_change",
    "canonical_target_changed": "review_canonical_conflict",
    "canonical_regression": "review_canonical_conflict",
    "robots_regression": "review_indexability_regression",
    "indexability_regression": "review_indexability_regression",
    "content_type_changed": "review_content_continuity",
    "language_changed": "review_material_metadata_change",
    "source_metadata_unavailable": "review_content_continuity",
    "content_likely_preserved": "review_content_continuity",
    "content_materially_changed": "review_content_continuity",
    "content_missing": "restore_missing_destination_page",
    "content_similarity_low": "review_content_continuity",
    "content_similarity_indeterminate": "review_content_continuity",
    "content_consolidated": "review_many_to_one_mapping",
    "content_split_review": "review_one_to_many_mapping",
    "canonical_points_to_legacy_url": "review_canonical_conflict",
    "canonical_points_to_wrong_host": "correct_destination_canonical",
    "canonical_points_to_redirect": "correct_destination_canonical",
    "canonical_points_to_error": "correct_destination_canonical",
    "canonical_self_reference_regression": "review_canonical_conflict",
    "canonical_conflicts_with_redirect": "review_canonical_conflict",
    "destination_noindex_regression": "review_indexability_regression",
    "destination_robots_block_regression": "review_robots_block",
    "legacy_url_still_indexable": "review_indexability_regression",
    "duplicate_source_and_destination_indexable": "review_indexability_regression",
    "internal_link_to_legacy_url": "update_internal_legacy_links",
    "internal_link_to_redirect": "replace_internal_redirect_links",
    "internal_link_to_broken_destination": "fix_broken_internal_links",
    "internal_link_to_staging_host": "remove_staging_host_references",
    "internal_link_host_mismatch": "remove_staging_host_references",
    "destination_orphan_candidate": "review_content_continuity",
    "navigation_target_regression": "review_content_continuity",
    "source_link_target_unmapped": "map_unmatched_source_url",
    "redirect_dependency_sitewide": "replace_internal_redirect_links",
    "legacy_url_in_destination_sitemap": "remove_legacy_urls_from_sitemap",
    "destination_url_missing_from_sitemap": "update_destination_sitemap",
    "redirecting_url_in_sitemap": "update_destination_sitemap",
    "broken_url_in_sitemap": "update_destination_sitemap",
    "nonindexable_url_in_sitemap": "update_destination_sitemap",
    "canonical_conflict_in_sitemap": "update_destination_sitemap",
    "sitemap_host_mismatch": "update_destination_sitemap",
    "sitemap_evidence_unavailable": "update_destination_sitemap",
    "image_missing_after_migration": "restore_image_reference",
    "image_broken_after_migration": "restore_image_reference",
    "image_legacy_host_reference": "restore_image_reference",
    "image_staging_host_reference": "remove_staging_host_references",
    "image_alt_missing_after_migration": "restore_image_alt_text",
    "image_alt_materially_changed": "review_image_regression",
    "image_redirect_dependency": "review_image_regression",
    "image_dimension_regression": "review_image_regression",
    "image_loading_regression": "review_image_regression",
    "structured_data_removed": "restore_structured_data",
    "structured_data_type_changed": "review_structured_data_change",
    "structured_data_entity_id_changed": "review_structured_data_change",
    "structured_data_identity_conflict": "review_structured_data_change",
    "structured_data_profile_regression": "review_structured_data_change",
    "structured_data_invalid_after_migration": "restore_structured_data",
    "structured_data_nonindexable_destination": "review_indexability_regression",
    "structured_data_format_changed": "review_structured_data_change",
    "sitewide_legacy_host_references": "review_sitewide_migration_pattern",
    "sitewide_staging_host_references": "remove_staging_host_references",
    "sitewide_redirect_dependency": "review_sitewide_migration_pattern",
    "sitewide_redirect_chain_pattern": "review_sitewide_migration_pattern",
    "sitewide_temporary_redirect_pattern": "review_sitewide_migration_pattern",
    "sitewide_noindex_regression": "review_sitewide_migration_pattern",
    "sitewide_canonical_host_mismatch": "review_sitewide_migration_pattern",
    "sitewide_metadata_loss": "review_sitewide_migration_pattern",
    "sitewide_sitemap_regression": "review_sitewide_migration_pattern",
    "sitewide_structured_data_loss": "review_sitewide_migration_pattern",
    "sitewide_image_host_regression": "review_sitewide_migration_pattern",
    "sitewide_unmapped_source_urls": "review_sitewide_migration_pattern",
    "sitewide_destination_errors": "review_sitewide_migration_pattern",
    "inventory_invalid_url": "verify_manual_mapping",
    "inventory_unsupported_scheme": "verify_manual_mapping",
    "inventory_out_of_scope": "verify_manual_mapping",
    "inventory_duplicate_source": "resolve_mapping_conflict",
    "inventory_conflicting_destination": "resolve_mapping_conflict",
    "inventory_field_too_long": "verify_manual_mapping",
    "readiness_missing_evidence": "verify_manual_mapping",
    "readiness_incompatible_evidence": "verify_manual_mapping",
    "readiness_expired_evidence": "verify_manual_mapping",
    "readiness_invalid_configuration": "verify_manual_mapping",
}

_CONFIDENCE_RANK = {"indeterminate": 0, "low": 1, "medium": 2, "high": 3}
_SEVERITY_RANK = {"info": 0, "warning": 1, "error": 2}


def analyze_migration(
    project: dict[str, Any],
    configuration: MigrationQaConfiguration,
    sources: tuple[dict[str, Any], ...],
    redirect_rows: tuple[dict[str, Any], ...],
    destination_pages: tuple[dict[str, Any], ...],
    source_pages: tuple[dict[str, Any], ...] = (),
    destination_links: tuple[dict[str, Any], ...] = (),
    source_links: tuple[dict[str, Any], ...] = (),
    sitemap_rows: tuple[dict[str, Any], ...] = (),
    destination_images: tuple[dict[str, Any], ...] = (),
    source_images: tuple[dict[str, Any], ...] = (),
    destination_structured: tuple[dict[str, Any], ...] = (),
    source_structured: tuple[dict[str, Any], ...] = (),
) -> dict[str, list[dict[str, Any]]]:
    """Build deterministic records exclusively from retained evidence and operator plans."""
    project_id = str(project["project_id"])
    destination_origin = str(project["destination_origin"])
    source_origin = str(project.get("source_origin") or "")
    resources: dict[str, list[dict[str, Any]]] = {
        name: []
        for name in (
            "mappings",
            "redirects",
            "comparisons",
            "findings",
            "recommendations",
            "sitewide",
        )
    }
    destination_by_url = _page_index(destination_pages)
    source_by_url = _page_index(source_pages)
    valid_redirects: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in redirect_rows:
        source = row.get("normalized_source_url")
        if source and row.get("state") not in {"invalid"}:
            valid_redirects[str(source)].append(row)

    def add_finding(
        code: str,
        *,
        mapping_id: str | None = None,
        source_url: str | None = None,
        destination_url: str | None = None,
        source_evidence_ids: tuple[str, ...] = (),
        destination_evidence_ids: tuple[str, ...] = (),
        evidence: dict[str, Any] | None = None,
        confidence: str | None = None,
        occurrence_count: int = 1,
        affected_page_count: int = 1,
    ) -> None:
        bounded = evidence or {}
        policy = classify_migration_finding(code, bounded, confidence=confidence)
        sequence = len(resources["findings"])
        resources["findings"].append(
            {
                "stable_id": stable_identity(project_id, "finding", str(sequence), code),
                "project_id": project_id,
                "mapping_id": mapping_id,
                "source_url": source_url,
                "destination_url": destination_url,
                "source_evidence_ids_json": stable_json(source_evidence_ids),
                "destination_evidence_ids_json": stable_json(destination_evidence_ids),
                "code": code,
                "category": policy["category"],
                "severity": policy["severity"],
                "confidence": policy["confidence"],
                "requires_human_review": policy["requires_human_review"],
                "reason": code.replace("_", " ").capitalize(),
                "bounded_evidence_json": stable_json(bounded),
                "occurrence_count": max(1, occurrence_count),
                "affected_page_count": max(0, affected_page_count),
                "sequence": sequence,
                "created_at": project["updated_at"],
            }
        )

    for source in sources:
        diagnostics = _json_list(source.get("diagnostics_json"))
        diagnostic_codes = {item.split(":", 1)[0] for item in diagnostics if isinstance(item, str)}
        for code in sorted(
            diagnostic_codes
            & {
                "inventory_invalid_url",
                "inventory_unsupported_scheme",
                "inventory_out_of_scope",
                "inventory_duplicate_source",
                "inventory_conflicting_destination",
                "inventory_field_too_long",
            }
        ):
            add_finding(
                code,
                source_url=source.get("normalized_url") or source.get("raw_url"),
                evidence={"source_row_id": source["id"], "diagnostics": diagnostics},
            )
    for row in redirect_rows:
        diagnostics = _json_list(row.get("diagnostics_json"))
        for code in sorted(
            set(diagnostics)
            & {
                "redirect_map_duplicate_source",
                "redirect_map_conflicting_destination",
                "redirect_map_loop",
                "redirect_map_chain",
                "redirect_map_invalid_url",
                "redirect_destination_collision",
            }
        ):
            add_finding(
                code,
                source_url=row.get("normalized_source_url") or row.get("raw_source_url"),
                destination_url=row.get("normalized_destination_url")
                or row.get("raw_destination_url"),
                evidence={"redirect_row_id": row["id"], "planned": True},
            )

    mappings = _build_mappings(
        project,
        sources,
        valid_redirects,
        destination_pages,
        source_by_url,
    )
    destination_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for mapping in mappings:
        if mapping["destination_url"]:
            destination_groups[str(mapping["destination_url"])].append(mapping)
    for mapping in mappings:
        if mapping["state"] == "unmapped":
            mapping["cardinality"] = "unmapped"
        elif mapping["state"] == "ambiguous":
            evidence = _json_object(mapping["bounded_evidence_json"])
            explicit_count = sum(
                1
                for candidate in evidence.get("candidates", [])
                if isinstance(candidate, dict)
                and candidate.get("method") == "explicit_redirect_map"
            )
            mapping["cardinality"] = "one_to_many" if explicit_count > 1 else "ambiguous"
        elif len(destination_groups[str(mapping["destination_url"])]) > 1:
            mapping["cardinality"] = "many_to_one"
        else:
            mapping["cardinality"] = "one_to_one"
        resources["mappings"].append(mapping)
        if mapping["cardinality"] == "unmapped":
            add_finding(
                "mapping_unmapped",
                mapping_id=mapping["id"],
                source_url=mapping["source_url"],
                evidence={"method": "unmapped"},
                confidence="indeterminate",
            )
        elif mapping["cardinality"] in {"ambiguous", "one_to_many"}:
            add_finding(
                "mapping_ambiguous",
                mapping_id=mapping["id"],
                source_url=mapping["source_url"],
                evidence=_json_object(mapping["bounded_evidence_json"]),
                confidence="low",
            )
            if mapping["cardinality"] == "one_to_many":
                for code in (
                    "mapping_one_to_many",
                    "mapping_conflicting_explicit",
                    "redirect_one_to_many_review",
                    "content_split_review",
                ):
                    add_finding(
                        code,
                        mapping_id=mapping["id"],
                        source_url=mapping["source_url"],
                        evidence=_json_object(mapping["bounded_evidence_json"]),
                        confidence="low",
                    )
        elif mapping["cardinality"] == "many_to_one":
            add_finding(
                "mapping_many_to_one",
                mapping_id=mapping["id"],
                source_url=mapping["source_url"],
                destination_url=mapping["destination_url"],
                evidence={"source_count": len(destination_groups[str(mapping["destination_url"])])},
                confidence="medium",
            )
            add_finding(
                "mapping_destination_collision",
                mapping_id=mapping["id"],
                source_url=mapping["source_url"],
                destination_url=mapping["destination_url"],
                evidence={"source_count": len(destination_groups[str(mapping["destination_url"])])},
                confidence="medium",
            )

    for mapping in mappings:
        _analyze_mapping(
            mapping,
            project,
            configuration,
            valid_redirects,
            destination_by_url,
            source_by_url,
            add_finding,
            resources,
        )

    _analyze_internal_links(
        mappings,
        destination_links if configuration.compare_internal_links else (),
        source_links if configuration.compare_internal_links else (),
        destination_by_url,
        source_origin,
        destination_origin,
        add_finding,
    )
    _analyze_sitemaps(
        mappings,
        sitemap_rows,
        destination_by_url,
        source_origin,
        destination_origin,
        configuration.compare_sitemaps,
        add_finding,
    )
    _analyze_images(
        mappings,
        source_images,
        destination_images,
        source_origin,
        destination_origin,
        configuration.compare_images,
        add_finding,
    )
    _analyze_structured_data(
        mappings,
        source_structured,
        destination_structured,
        destination_by_url,
        configuration.compare_structured_data,
        add_finding,
    )
    _add_sitewide_findings(resources, len(sources), configuration, add_finding)
    _build_recommendations(project_id, resources)
    return resources


def _build_mappings(
    project: dict[str, Any],
    sources: tuple[dict[str, Any], ...],
    redirects: dict[str, list[dict[str, Any]]],
    destination_pages: tuple[dict[str, Any], ...],
    source_by_url: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    destination_urls = sorted(_page_index(destination_pages))
    destination_origin = str(project["destination_origin"])
    source_origin = str(project.get("source_origin") or "")
    result: list[dict[str, Any]] = []
    for source in sources:
        source_url = source.get("normalized_url")
        candidates: list[tuple[str, str, str, dict[str, Any]]] = []
        explicit = redirects.get(str(source_url), ())
        explicit_destinations = sorted(
            {
                str(row["normalized_destination_url"])
                for row in explicit
                if row.get("normalized_destination_url")
            }
        )
        for explicit_destination in explicit_destinations:
            candidates.append(
                (
                    "explicit_redirect_map",
                    explicit_destination,
                    "high",
                    {
                        "redirect_row_ids": [
                            row["id"]
                            for row in explicit
                            if row.get("normalized_destination_url") == explicit_destination
                        ]
                    },
                )
            )
        proposed = source.get("proposed_destination_url")
        if proposed:
            candidates.append(
                (
                    "explicit_proposed_destination",
                    str(proposed),
                    "high",
                    {"source_row_id": source["id"]},
                )
            )
        source_page = source_by_url.get(str(source_url))
        if source_page and source_page.get("final_url") and source_page["final_url"] != source_url:
            candidates.append(
                (
                    "observed_redirect",
                    str(source_page["final_url"]),
                    "high",
                    {"source_evidence_id": source_page.get("evidence_id")},
                )
            )
        if source_url in destination_urls:
            candidates.append(("exact_normalized_url", str(source_url), "high", {"exact": True}))
        if source_url and source_origin and str(source_url).startswith(source_origin):
            candidates.append(
                (
                    "configured_origin_substitution",
                    destination_origin + str(source_url)[len(source_origin) :],
                    "medium",
                    {"source_origin": source_origin, "destination_origin": destination_origin},
                )
            )
        path = urlsplit(str(source_url)).path if source_url else ""
        path_matches = [url for url in destination_urls if urlsplit(url).path == path]
        if len(path_matches) == 1:
            candidates.append(
                (
                    "path_match",
                    path_matches[0],
                    "low",
                    {"path": path, "semantic_equivalence": False},
                )
            )
        canonical = source_page.get("canonical_url") if source_page else None
        if canonical in destination_urls:
            candidates.append(
                (
                    "canonical_hint",
                    str(canonical),
                    "low",
                    {
                        "source_evidence_id": source_page.get("evidence_id")
                        if source_page
                        else None,
                        "semantic_equivalence": False,
                    },
                )
            )
        content_matches = [
            page.get("final_url") or page.get("requested_url")
            for page in destination_pages
            if source_page and _content_signature(source_page) == _content_signature(page)
        ]
        if len(set(content_matches)) == 1 and content_matches[0]:
            candidates.append(
                (
                    "content_similarity_hint",
                    str(content_matches[0]),
                    "low",
                    {"basis": "bounded_fingerprint", "semantic_equivalence": False},
                )
            )
        candidates = _deduplicate_candidates(candidates)
        method: str
        destination: str | None
        confidence: str
        state: str
        if len(explicit_destinations) > 1:
            method, destination, confidence, state = (
                "manual_review_candidate",
                None,
                "low",
                "ambiguous",
            )
        elif candidates:
            method, destination, confidence, evidence = candidates[0]
            competing = sorted({item[1] for item in candidates})
            if len(competing) > 1 and method not in {
                "explicit_redirect_map",
                "explicit_proposed_destination",
                "observed_redirect",
            }:
                method, destination, confidence, state = (
                    "manual_review_candidate",
                    None,
                    "low",
                    "ambiguous",
                )
            else:
                state = "mapped"
        else:
            method, destination, confidence, state = "unmapped", None, "indeterminate", "unmapped"
        evidence = {
            "source_row_id": source["id"],
            "candidates": [
                {
                    "method": item[0],
                    "destination_url": item[1],
                    "confidence": item[2],
                    "basis": item[3],
                }
                for item in candidates
            ],
            "accepted_automatically": state == "mapped",
        }
        mapping_id = stable_identity(str(project["project_id"]), "mapping", source["id"])
        result.append(
            {
                "id": mapping_id,
                "project_id": project["project_id"],
                "source_row_id": source["id"],
                "source_url": source_url or source["raw_url"],
                "destination_url": destination,
                "mapping_method": method,
                "cardinality": "unmapped",
                "confidence": confidence,
                "state": state,
                "bounded_evidence_json": stable_json(evidence),
                "created_at": project["updated_at"],
            }
        )
    return result


def _analyze_mapping(
    mapping: dict[str, Any],
    project: dict[str, Any],
    configuration: MigrationQaConfiguration,
    redirect_rows: dict[str, list[dict[str, Any]]],
    destination_by_url: dict[str, dict[str, Any]],
    source_by_url: dict[str, dict[str, Any]],
    finding: Any,
    resources: dict[str, list[dict[str, Any]]],
) -> None:
    source_url = str(mapping["source_url"])
    destination_url = mapping.get("destination_url")
    if not destination_url:
        return
    destination_url = str(destination_url)
    mapping_id = str(mapping["id"])
    planned_rows = redirect_rows.get(source_url, [])
    planned = planned_rows[0] if len(planned_rows) == 1 else None
    observed = destination_by_url.get(source_url)
    page = destination_by_url.get(destination_url)
    source_page = source_by_url.get(source_url)
    source_ids = _evidence_ids(source_page)
    destination_ids = _evidence_ids(page)
    hops = tuple((observed or {}).get("redirects", ()))
    hop_urls = [str(item.get("target_url") or item.get("location_url") or "") for item in hops]
    chain_identity = stable_identity(*hop_urls) if hop_urls else None
    loop_identity = chain_identity if observed and observed.get("redirect_loop") else None
    resources["redirects"].append(
        {
            "id": stable_identity(mapping_id, "redirect"),
            "project_id": project["project_id"],
            "mapping_id": mapping_id,
            "planned_destination_url": destination_url,
            "observed_final_url": observed.get("final_url") if observed else None,
            "observed_status": observed.get("http_status") if observed else None,
            "chain_json": stable_json(hops),
            "chain_identity": chain_identity,
            "loop_identity": loop_identity,
            "hop_count": len(hops) or int((observed or {}).get("redirect_count") or 0),
            "truncated": bool((observed or {}).get("redirect_truncated")),
            "evidence_source": "retained_destination_page_evidence",
            "state": "observed" if observed else "missing",
            "evidence_json": stable_json({"planned": bool(planned), "observed": bool(observed)}),
            "created_at": project["updated_at"],
        }
    )
    common = {
        "mapping_id": mapping_id,
        "source_url": source_url,
        "destination_url": destination_url,
        "source_evidence_ids": source_ids,
        "destination_evidence_ids": destination_ids,
    }
    if planned and not observed:
        finding(
            "redirect_missing", **common, evidence={"planned": True, "deployed_evidence": False}
        )
    if observed:
        final = observed.get("final_url")
        if final and final != destination_url:
            finding(
                "redirect_wrong_destination",
                **common,
                evidence={"planned": destination_url, "observed": final},
            )
        status = observed.get("http_status")
        if status in {302, 307}:
            finding("redirect_temporary", **common, evidence={"observed_status": status})
        if planned and planned.get("expected_status") and status != planned["expected_status"]:
            finding(
                "redirect_status_mismatch",
                **common,
                evidence={"planned_status": planned["expected_status"], "observed_status": status},
            )
        if observed.get("redirect_loop"):
            finding(
                "redirect_loop", **common, evidence={"loop_identity": loop_identity, "hops": hops}
            )
        if int(observed.get("redirect_count") or 0) > 1:
            finding(
                "redirect_chain",
                **common,
                evidence={
                    "chain_identity": chain_identity,
                    "hops": hops,
                    "truncated": observed.get("redirect_truncated"),
                },
            )
    if page:
        status = page.get("http_status")
        if status is not None and int(status) >= 400:
            finding("redirect_to_error", **common, evidence={"status": status})
        if page.get("indexability_state") == "non_indexable":
            finding(
                "redirect_to_nonindexable",
                **common,
                evidence={"indexability": page.get("indexability_state")},
            )
    destination_origin = str(project["destination_origin"])
    source_origin = str(project.get("source_origin") or "")
    target_origin = _origin(destination_url)
    if target_origin not in {destination_origin, source_origin}:
        finding("redirect_to_external", **common, evidence={"target_origin": target_origin})
    elif target_origin != destination_origin:
        finding("redirect_to_out_of_scope", **common, evidence={"target_origin": target_origin})
    source_query = urlsplit(source_url).query
    target_query = urlsplit(destination_url).query
    if configuration.preserve_query_parameters and source_query and not target_query:
        finding("redirect_query_dropped", **common, evidence={"source_query": source_query})
    if not configuration.preserve_query_parameters and not source_query and target_query:
        finding(
            "redirect_query_unexpectedly_preserved",
            **common,
            evidence={"destination_query": target_query},
        )
    if configuration.compare_fragments:
        planned_fragment = urlsplit(
            str((planned or {}).get("raw_destination_url") or destination_url)
        ).fragment
        source_fragment = urlsplit(
            str((planned or {}).get("raw_source_url") or source_url)
        ).fragment
        if planned_fragment != source_fragment:
            finding(
                "redirect_fragment_policy_mismatch",
                **common,
                evidence={
                    "source_fragment": source_fragment,
                    "destination_fragment": planned_fragment,
                },
            )
    if mapping["cardinality"] == "many_to_one":
        finding(
            "redirect_many_to_one_review",
            **common,
            evidence={"cardinality": "many_to_one"},
            confidence="medium",
        )
        finding(
            "redirect_destination_collision",
            **common,
            evidence={"destination_url": destination_url},
            confidence="medium",
        )
        finding(
            "content_consolidated",
            **common,
            evidence={"cardinality": "many_to_one"},
            confidence="medium",
        )
    elif mapping["cardinality"] == "ambiguous":
        finding(
            "redirect_one_to_many_review",
            **common,
            evidence={"cardinality": "ambiguous"},
            confidence="low",
        )
        finding(
            "content_split_review",
            **common,
            evidence={"cardinality": "ambiguous"},
            confidence="low",
        )
    _destination_findings(page, common, finding)
    comparison = _comparison(source_page, page, configuration, common, finding)
    resources["comparisons"].append(
        {
            "id": stable_identity(mapping_id, "comparison"),
            "project_id": project["project_id"],
            "mapping_id": mapping_id,
            "source_url": source_url,
            "destination_url": destination_url,
            **comparison,
            "created_at": project["updated_at"],
        }
    )
    _canonical_indexability_findings(
        source_page, page, destination_by_url, project, common, finding
    )


def _destination_findings(
    page: dict[str, Any] | None, common: dict[str, Any], finding: Any
) -> None:
    if page is None:
        finding("destination_missing", **common, evidence={"state": "missing"})
        return
    status = page.get("http_status")
    if status is None:
        finding(
            "destination_status_unknown",
            **common,
            evidence={"state": "indeterminate"},
            confidence="indeterminate",
        )
    elif status == 404:
        finding("destination_404", **common, evidence={"status": 404, "state": "confirmed"})
    elif status == 410:
        finding("destination_410", **common, evidence={"status": 410, "state": "confirmed"})
    elif 400 <= int(status) < 500:
        finding(
            "destination_other_4xx", **common, evidence={"status": status, "state": "confirmed"}
        )
    elif int(status) >= 500:
        finding("destination_5xx", **common, evidence={"status": status, "state": "confirmed"})
    elif 300 <= int(status) < 400 or int(page.get("redirect_count") or 0):
        finding(
            "destination_redirecting", **common, evidence={"status": status, "state": "confirmed"}
        )
    if page.get("content_type_category") not in {None, "html"}:
        finding(
            "destination_non_html",
            **common,
            evidence={"content_type": page.get("content_type"), "state": "confirmed"},
        )
    if page.get("indexability_state") == "non_indexable":
        finding(
            "destination_noindex",
            **common,
            evidence={"indexability": "non_indexable", "state": "confirmed"},
        )
    if page.get("robots_allowed") is False:
        finding(
            "destination_blocked_by_robots",
            **common,
            evidence={"robots_reason": page.get("robots_reason_code"), "state": "confirmed"},
        )
    canonical_presence = page.get("canonical_presence")
    canonical = page.get("canonical_url")
    if canonical_presence in {"missing", "empty"}:
        finding(
            "destination_canonical_missing", **common, evidence={"presence": canonical_presence}
        )
    elif canonical_presence == "multiple" or page.get("canonical_conflicting"):
        finding(
            "destination_canonical_invalid",
            **common,
            evidence={
                "presence": canonical_presence,
                "conflicting": page.get("canonical_conflicting"),
            },
        )
    elif canonical and canonical != common["destination_url"]:
        finding("destination_canonical_elsewhere", **common, evidence={"canonical": canonical})


def _comparison(
    source: dict[str, Any] | None,
    destination: dict[str, Any] | None,
    configuration: MigrationQaConfiguration,
    common: dict[str, Any],
    finding: Any,
) -> dict[str, Any]:
    if destination is None:
        finding("content_missing", **common, evidence={"destination": "missing"})
        return {
            "status_state": "missing",
            "metadata_state": "not_available",
            "content_state": "missing",
            "canonical_state": "not_available",
            "indexability_state": "not_available",
            "evidence_json": stable_json({"source": bool(source), "destination": False}),
            "similarity_score": None,
            "comparison_basis_json": stable_json({"basis": "retained_evidence"}),
        }
    if source is None:
        finding(
            "source_metadata_unavailable",
            **common,
            evidence={"source": "not_available"},
            confidence="indeterminate",
        )
        finding(
            "content_similarity_indeterminate",
            **common,
            evidence={"source": "not_available"},
            confidence="indeterminate",
        )
        return {
            "status_state": "confirmed",
            "metadata_state": "not_available",
            "content_state": "indeterminate",
            "canonical_state": "not_available",
            "indexability_state": "not_available",
            "evidence_json": stable_json({"source": False, "destination": True}),
            "similarity_score": None,
            "comparison_basis_json": stable_json({"basis": "retained_evidence"}),
        }
    states: dict[str, str] = {}
    for key, presence_key, missing_code, changed_code in (
        ("title", "title_presence", "title_missing_after_migration", "title_materially_changed"),
        (
            "description",
            "description_presence",
            "meta_description_missing_after_migration",
            "meta_description_materially_changed",
        ),
    ):
        source_value = source.get(f"{key}_value")
        destination_value = destination.get(f"{key}_value")
        source_presence = source.get(presence_key)
        destination_presence = destination.get(presence_key)
        if source_presence in {"single", "multiple"} and destination_presence in {
            "missing",
            "empty",
        }:
            states[key] = "missing"
            finding(
                missing_code,
                **common,
                evidence={
                    "source_presence": source_presence,
                    "destination_presence": destination_presence,
                },
            )
        elif source_presence in {"missing", "empty"} and destination_presence in {
            "single",
            "multiple",
        }:
            states[key] = "added"
        elif source.get(f"{key}_normalized_hash") == destination.get(f"{key}_normalized_hash"):
            states[key] = "preserved"
        elif _material_change(
            source_value, destination_value, configuration.material_content_change_ratio
        ):
            states[key] = "changed"
            finding(
                changed_code,
                **common,
                evidence={
                    "threshold": configuration.material_content_change_ratio,
                    "similarity": _text_similarity(source_value, destination_value),
                },
                confidence="medium",
            )
        else:
            states[key] = "changed"
    if source.get("canonical_url") != destination.get("canonical_url"):
        finding(
            "canonical_target_changed",
            **common,
            evidence={
                "source": source.get("canonical_url"),
                "destination": destination.get("canonical_url"),
            },
            confidence="medium",
        )
    if source.get("meta_robots_json") != destination.get("meta_robots_json") or source.get(
        "x_robots_json"
    ) != destination.get("x_robots_json"):
        finding(
            "robots_regression",
            **common,
            evidence={
                "source_meta_robots": source.get("meta_robots_json"),
                "destination_meta_robots": destination.get("meta_robots_json"),
                "source_x_robots": source.get("x_robots_json"),
                "destination_x_robots": destination.get("x_robots_json"),
            },
            confidence="medium",
        )
    if source.get("indexability_state") != destination.get("indexability_state"):
        finding(
            "indexability_regression",
            **common,
            evidence={
                "source": source.get("indexability_state"),
                "destination": destination.get("indexability_state"),
            },
            confidence="high",
        )
    if source.get("content_type_category") != destination.get("content_type_category"):
        finding(
            "content_type_changed",
            **common,
            evidence={
                "source": source.get("content_type"),
                "destination": destination.get("content_type"),
            },
            confidence="high",
        )
    language_source = source.get("language")
    language_destination = destination.get("language")
    if language_source and language_destination and language_source != language_destination:
        finding(
            "language_changed",
            **common,
            evidence={"source": language_source, "destination": language_destination},
            confidence="medium",
        )
    score = _content_score(source, destination)
    if score >= 1 - configuration.material_content_change_ratio:
        content_state = "preserved"
        finding(
            "content_likely_preserved",
            **common,
            evidence={"score": score, "basis": "bounded_technical_fingerprints"},
            confidence="medium",
        )
    else:
        content_state = "changed"
        finding(
            "content_materially_changed",
            **common,
            evidence={
                "score": score,
                "threshold": 1 - configuration.material_content_change_ratio,
                "basis": "bounded_technical_fingerprints",
            },
            confidence="medium",
        )
        finding(
            "content_similarity_low",
            **common,
            evidence={"score": score, "semantic_equivalence": False},
            confidence="low",
        )
    return {
        "status_state": "preserved"
        if source.get("http_status") == destination.get("http_status")
        else "changed",
        "metadata_state": "preserved" if set(states.values()) == {"preserved"} else "changed",
        "content_state": content_state,
        "canonical_state": "preserved"
        if source.get("canonical_url") == destination.get("canonical_url")
        else "changed",
        "indexability_state": "preserved"
        if source.get("indexability_state") == destination.get("indexability_state")
        else "changed",
        "evidence_json": stable_json(
            {
                "source_evidence_id": source.get("evidence_id"),
                "destination_evidence_id": destination.get("evidence_id"),
                "metadata_states": states,
            }
        ),
        "similarity_score": f"{score:.6f}",
        "comparison_basis_json": stable_json(
            {
                "signals": ["title", "description", "canonical", "content_type", "indexability"],
                "semantic_equivalence": False,
            }
        ),
    }


def _canonical_indexability_findings(
    source: dict[str, Any] | None,
    destination: dict[str, Any] | None,
    page_index: dict[str, dict[str, Any]],
    project: dict[str, Any],
    common: dict[str, Any],
    finding: Any,
) -> None:
    if destination is None:
        return
    canonical = destination.get("canonical_url")
    destination_url = str(common["destination_url"])
    source_url = str(common["source_url"])
    if (
        canonical
        and project.get("source_origin")
        and str(canonical).startswith(str(project["source_origin"]))
    ):
        finding("canonical_points_to_legacy_url", **common, evidence={"canonical": canonical})
    if canonical and _origin(str(canonical)) != str(project["destination_origin"]):
        finding("canonical_points_to_wrong_host", **common, evidence={"canonical": canonical})
    canonical_page = page_index.get(str(canonical)) if canonical else None
    if canonical_page and int(canonical_page.get("redirect_count") or 0):
        finding("canonical_points_to_redirect", **common, evidence={"canonical": canonical})
    if canonical_page and int(canonical_page.get("http_status") or 0) >= 400:
        finding(
            "canonical_points_to_error",
            **common,
            evidence={"canonical": canonical, "status": canonical_page.get("http_status")},
        )
    if source and source.get("canonical_url") == source_url and canonical != destination_url:
        finding(
            "canonical_self_reference_regression",
            **common,
            evidence={"source_self_reference": True, "destination_canonical": canonical},
            confidence="medium",
        )
    if canonical and canonical != destination_url:
        finding(
            "canonical_conflicts_with_redirect",
            **common,
            evidence={"redirect_destination": destination_url, "canonical": canonical},
        )
        finding("canonical_regression", **common, evidence={"canonical": canonical})
    if (
        source
        and source.get("indexability_state") == "indexable"
        and destination.get("indexability_state") == "non_indexable"
    ):
        finding(
            "destination_noindex_regression",
            **common,
            evidence={"source": "indexable", "destination": "non_indexable"},
        )
    if (
        source
        and source.get("robots_allowed") is not False
        and destination.get("robots_allowed") is False
    ):
        finding(
            "destination_robots_block_regression",
            **common,
            evidence={"destination_robots_allowed": False},
        )
    legacy_page = page_index.get(source_url)
    if legacy_page and legacy_page.get("indexability_state") == "indexable":
        finding(
            "legacy_url_still_indexable",
            **common,
            evidence={"legacy_evidence_id": legacy_page.get("evidence_id")},
        )
        if destination.get("indexability_state") == "indexable":
            finding(
                "duplicate_source_and_destination_indexable",
                **common,
                evidence={"source": source_url, "destination": destination_url},
            )


def _analyze_internal_links(
    mappings: list[dict[str, Any]],
    destination_links: tuple[dict[str, Any], ...],
    source_links: tuple[dict[str, Any], ...],
    destination_pages: dict[str, dict[str, Any]],
    source_origin: str,
    destination_origin: str,
    finding: Any,
) -> None:
    mapping_by_source = {str(item["source_url"]): item for item in mappings}
    incoming: Counter[str] = Counter()
    for link in destination_links:
        target = link.get("resolved_url")
        if not target:
            continue
        target = str(target)
        incoming[target] += 1
        common = {
            "source_url": link.get("source_final_url") or link.get("source_requested_url"),
            "destination_url": target,
            "destination_evidence_ids": (str(link.get("link_id")),),
        }
        host = urlsplit(target).hostname or ""
        if source_origin and target.startswith(source_origin):
            finding(
                "internal_link_to_legacy_url", **common, evidence={"link_id": link.get("link_id")}
            )
        if _is_staging_host(host):
            finding("internal_link_to_staging_host", **common, evidence={"host": host})
        if _origin(target) not in {destination_origin, source_origin} and link.get("internal"):
            finding("internal_link_host_mismatch", **common, evidence={"host": host})
        page = destination_pages.get(target)
        if target in mapping_by_source:
            finding(
                "internal_link_to_redirect",
                **common,
                evidence={"mapping_id": mapping_by_source[target]["id"]},
            )
        if page and int(page.get("http_status") or 0) >= 400:
            finding(
                "internal_link_to_broken_destination",
                **common,
                evidence={"status": page.get("http_status")},
            )
        if target in mapping_by_source and mapping_by_source[target]["state"] == "unmapped":
            finding(
                "source_link_target_unmapped",
                **common,
                evidence={"mapping_id": mapping_by_source[target]["id"]},
                confidence="low",
            )
    source_targets = {
        str(item.get("resolved_url")) for item in source_links if item.get("resolved_url")
    }
    destination_targets = {
        str(item.get("resolved_url")) for item in destination_links if item.get("resolved_url")
    }
    for target in sorted(source_targets - destination_targets):
        mapped = mapping_by_source.get(target)
        finding(
            "navigation_target_regression",
            source_url=target,
            destination_url=mapped.get("destination_url") if mapped else None,
            evidence={"source_link_present": True, "destination_link_present": False},
            confidence="low",
        )
    for mapping in mappings:
        destination = mapping.get("destination_url")
        if destination and incoming[str(destination)] == 0:
            finding(
                "destination_orphan_candidate",
                mapping_id=mapping["id"],
                source_url=mapping["source_url"],
                destination_url=str(destination),
                evidence={"retained_incoming_links": 0},
                confidence="low",
            )
    redirect_dependent = sum(
        str(item.get("resolved_url")) in mapping_by_source for item in destination_links
    )
    if redirect_dependent:
        finding(
            "redirect_dependency_sitewide",
            evidence={"occurrences": redirect_dependent},
            occurrence_count=redirect_dependent,
            affected_page_count=len(
                {
                    item.get("source_requested_url")
                    for item in destination_links
                    if str(item.get("resolved_url")) in mapping_by_source
                }
            ),
        )


def _analyze_sitemaps(
    mappings: list[dict[str, Any]],
    rows: tuple[dict[str, Any], ...],
    destination_pages: dict[str, dict[str, Any]],
    source_origin: str,
    destination_origin: str,
    enabled: bool,
    finding: Any,
) -> None:
    if not enabled:
        return
    if not rows:
        finding(
            "sitemap_evidence_unavailable",
            evidence={"enabled": True},
            confidence="indeterminate",
            affected_page_count=0,
        )
        return
    urls = {str(row.get("normalized_identity")) for row in rows if row.get("normalized_identity")}
    for url in sorted(urls):
        common = {
            "destination_url": url,
            "destination_evidence_ids": tuple(
                str(row.get("entry_id")) for row in rows if row.get("normalized_identity") == url
            ),
        }
        page = destination_pages.get(url)
        if source_origin and url.startswith(source_origin):
            finding("legacy_url_in_destination_sitemap", **common, evidence={"url": url})
        if _origin(url) != destination_origin:
            finding("sitemap_host_mismatch", **common, evidence={"origin": _origin(url)})
        if page and int(page.get("redirect_count") or 0):
            finding(
                "redirecting_url_in_sitemap",
                **common,
                evidence={"redirect_count": page.get("redirect_count")},
            )
        if page and int(page.get("http_status") or 0) >= 400:
            finding("broken_url_in_sitemap", **common, evidence={"status": page.get("http_status")})
        if page and page.get("indexability_state") == "non_indexable":
            finding(
                "nonindexable_url_in_sitemap", **common, evidence={"indexability": "non_indexable"}
            )
        if page and page.get("canonical_url") and page.get("canonical_url") != url:
            finding(
                "canonical_conflict_in_sitemap",
                **common,
                evidence={"canonical": page.get("canonical_url")},
            )
    for mapping in mappings:
        destination = mapping.get("destination_url")
        if destination and destination not in urls:
            finding(
                "destination_url_missing_from_sitemap",
                mapping_id=mapping["id"],
                source_url=mapping["source_url"],
                destination_url=str(destination),
                evidence={"sitemap_entries": len(urls)},
            )


def _analyze_images(
    mappings: list[dict[str, Any]],
    source_rows: tuple[dict[str, Any], ...],
    destination_rows: tuple[dict[str, Any], ...],
    source_origin: str,
    destination_origin: str,
    enabled: bool,
    finding: Any,
) -> None:
    if not enabled:
        return
    mapping_by_source = {
        str(item["source_url"]): str(item.get("destination_url") or "") for item in mappings
    }
    source_by_page: dict[str, list[dict[str, Any]]] = defaultdict(list)
    destination_by_page: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in source_rows:
        source_by_page[str(row.get("source_final_url") or row.get("source_requested_url"))].append(
            row
        )
    for row in destination_rows:
        destination_by_page[
            str(row.get("source_final_url") or row.get("source_requested_url"))
        ].append(row)
        image_url = str(row.get("resolved_src") or "")
        host = urlsplit(image_url).hostname or ""
        common = {
            "source_url": row.get("source_requested_url"),
            "destination_url": image_url,
            "destination_evidence_ids": (str(row.get("image_id")),),
        }
        if source_origin and image_url.startswith(source_origin):
            finding(
                "image_legacy_host_reference", **common, evidence={"image_id": row.get("image_id")}
            )
        if _is_staging_host(host):
            finding("image_staging_host_reference", **common, evidence={"host": host})
        resource = row.get("resource") or {}
        if int(resource.get("http_status") or 0) >= 400 or int(
            resource.get("broken_occurrence_count") or 0
        ):
            finding(
                "image_broken_after_migration",
                **common,
                evidence={"status": resource.get("http_status")},
            )
        if int(resource.get("redirecting_occurrence_count") or 0):
            finding(
                "image_redirect_dependency",
                **common,
                evidence={"redirect_state": resource.get("redirect_state")},
            )
    for source_page, rows in source_by_page.items():
        destination_page = mapping_by_source.get(source_page)
        destination_images = destination_by_page.get(destination_page or "", [])
        destination_identities = {row.get("image_identity") for row in destination_images}
        for row in rows:
            common = {
                "source_url": source_page,
                "destination_url": destination_page,
                "source_evidence_ids": (str(row.get("image_id")),),
            }
            if row.get("image_identity") not in destination_identities:
                finding(
                    "image_missing_after_migration",
                    **common,
                    evidence={"image_identity": row.get("image_identity")},
                )
                continue
            matches = [
                item
                for item in destination_images
                if item.get("image_identity") == row.get("image_identity")
            ]
            destination = matches[0]
            if row.get("alt_present") and not destination.get("alt_present"):
                finding(
                    "image_alt_missing_after_migration",
                    **common,
                    destination_evidence_ids=(str(destination.get("image_id")),),
                    evidence={"source_alt": row.get("alt_normalized")},
                )
            elif row.get("alt_normalized") != destination.get("alt_normalized"):
                finding(
                    "image_alt_materially_changed",
                    **common,
                    destination_evidence_ids=(str(destination.get("image_id")),),
                    evidence={
                        "source_alt": row.get("alt_normalized"),
                        "destination_alt": destination.get("alt_normalized"),
                    },
                    confidence="medium",
                )
            if (row.get("width_value"), row.get("height_value")) != (
                destination.get("width_value"),
                destination.get("height_value"),
            ):
                finding(
                    "image_dimension_regression",
                    **common,
                    evidence={
                        "source": [row.get("width_value"), row.get("height_value")],
                        "destination": [
                            destination.get("width_value"),
                            destination.get("height_value"),
                        ],
                    },
                    confidence="medium",
                )
            if row.get("loading_value") != destination.get("loading_value"):
                finding(
                    "image_loading_regression",
                    **common,
                    evidence={
                        "source": row.get("loading_value"),
                        "destination": destination.get("loading_value"),
                    },
                    confidence="low",
                )


def _analyze_structured_data(
    mappings: list[dict[str, Any]],
    source_rows: tuple[dict[str, Any], ...],
    destination_rows: tuple[dict[str, Any], ...],
    destination_pages: dict[str, dict[str, Any]],
    enabled: bool,
    finding: Any,
) -> None:
    if not enabled:
        return
    mapping_by_source = {
        str(item["source_url"]): str(item.get("destination_url") or "") for item in mappings
    }
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_destination: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in source_rows:
        by_source[str(row.get("source_final_url") or row.get("source_requested_url"))].append(row)
    for row in destination_rows:
        page_url = str(row.get("source_final_url") or row.get("source_requested_url"))
        by_destination[page_url].append(row)
        if row.get("parse_status") != "parsed":
            finding(
                "structured_data_invalid_after_migration",
                destination_url=page_url,
                destination_evidence_ids=(str(row.get("block_id")),),
                evidence={
                    "parse_status": row.get("parse_status"),
                    "parse_error": row.get("parse_error"),
                },
            )
        page = destination_pages.get(page_url)
        if page and page.get("indexability_state") == "non_indexable":
            finding(
                "structured_data_nonindexable_destination",
                destination_url=page_url,
                destination_evidence_ids=(str(row.get("block_id")),),
                evidence={"indexability": "non_indexable"},
            )
    for source_page, rows in by_source.items():
        destination_page = mapping_by_source.get(source_page)
        targets = by_destination.get(destination_page or "", [])
        common = {
            "source_url": source_page,
            "destination_url": destination_page,
            "source_evidence_ids": tuple(str(row.get("block_id")) for row in rows),
            "destination_evidence_ids": tuple(str(row.get("block_id")) for row in targets),
        }
        if not targets:
            finding(
                "structured_data_removed",
                **common,
                evidence={"source_blocks": len(rows), "destination_blocks": 0},
            )
            continue
        source_types = _json_union(rows, "types_json")
        destination_types = _json_union(targets, "types_json")
        source_ids = _json_union(rows, "identifiers_json")
        destination_ids = _json_union(targets, "identifiers_json")
        if source_types != destination_types:
            finding(
                "structured_data_type_changed",
                **common,
                evidence={"source": sorted(source_types), "destination": sorted(destination_types)},
                confidence="medium",
            )
            finding(
                "structured_data_profile_regression",
                **common,
                evidence={"removed_types": sorted(source_types - destination_types)},
                confidence="medium",
            )
        if source_ids != destination_ids:
            finding(
                "structured_data_entity_id_changed",
                **common,
                evidence={"source": sorted(source_ids), "destination": sorted(destination_ids)},
                confidence="medium",
            )
        if source_ids & destination_ids and source_types != destination_types:
            finding(
                "structured_data_identity_conflict",
                **common,
                evidence={"shared_identifiers": sorted(source_ids & destination_ids)},
                confidence="low",
            )
        source_formats = {str(row.get("format")) for row in rows}
        destination_formats = {str(row.get("format")) for row in targets}
        if source_formats != destination_formats:
            finding(
                "structured_data_format_changed",
                **common,
                evidence={
                    "source": sorted(source_formats),
                    "destination": sorted(destination_formats),
                    "informational": True,
                },
                confidence="medium",
            )


def _add_sitewide_findings(
    resources: dict[str, list[dict[str, Any]]],
    inventory_count: int,
    configuration: MigrationQaConfiguration,
    finding: Any,
) -> None:
    counts = Counter(item["code"] for item in resources["findings"])
    groups = {
        "sitewide_legacy_host_references": (
            "internal_link_to_legacy_url",
            "image_legacy_host_reference",
            "legacy_url_in_destination_sitemap",
        ),
        "sitewide_staging_host_references": (
            "internal_link_to_staging_host",
            "image_staging_host_reference",
        ),
        "sitewide_redirect_dependency": ("internal_link_to_redirect", "image_redirect_dependency"),
        "sitewide_redirect_chain_pattern": ("redirect_chain",),
        "sitewide_temporary_redirect_pattern": ("redirect_temporary",),
        "sitewide_noindex_regression": ("destination_noindex_regression",),
        "sitewide_canonical_host_mismatch": ("canonical_points_to_wrong_host",),
        "sitewide_metadata_loss": (
            "title_missing_after_migration",
            "meta_description_missing_after_migration",
        ),
        "sitewide_sitemap_regression": (
            "destination_url_missing_from_sitemap",
            "legacy_url_in_destination_sitemap",
        ),
        "sitewide_structured_data_loss": ("structured_data_removed",),
        "sitewide_image_host_regression": (
            "image_legacy_host_reference",
            "image_staging_host_reference",
        ),
        "sitewide_unmapped_source_urls": ("mapping_unmapped",),
        "sitewide_destination_errors": (
            "destination_404",
            "destination_410",
            "destination_other_4xx",
            "destination_5xx",
        ),
    }
    threshold = max(2, int(inventory_count * configuration.sitewide_issue_ratio + 0.999999))
    for code, source_codes in groups.items():
        occurrence = sum(counts[item] for item in source_codes)
        state = (
            "small_inventory"
            if inventory_count < configuration.minimum_sitewide_pages
            else "threshold_reached"
            if occurrence >= threshold
            else "below_threshold"
        )
        resources["sitewide"].append(
            {
                "id": stable_identity(
                    resources["mappings"][0]["project_id"] if resources["mappings"] else "none",
                    "sitewide",
                    code,
                ),
                "project_id": resources["mappings"][0]["project_id"]
                if resources["mappings"]
                else "",
                "category": "sitewide",
                "metric_name": code,
                "numerator": occurrence,
                "denominator": inventory_count,
                "ratio": f"{occurrence / inventory_count:.6f}" if inventory_count else "0.000000",
                "state": state,
                "evidence_json": stable_json(
                    {
                        "source_codes": source_codes,
                        "threshold": threshold,
                        "minimum_inventory": configuration.minimum_sitewide_pages,
                    }
                ),
                "created_at": resources["mappings"][0]["created_at"]
                if resources["mappings"]
                else None,
            }
        )
        if state == "threshold_reached":
            finding(
                code,
                evidence={
                    "occurrences": occurrence,
                    "inventory": inventory_count,
                    "threshold": threshold,
                },
                occurrence_count=occurrence,
                affected_page_count=min(occurrence, inventory_count),
            )


def _build_recommendations(project_id: str, resources: dict[str, list[dict[str, Any]]]) -> None:
    grouped: dict[tuple[str, str, str | None, str | None], list[dict[str, Any]]] = defaultdict(list)
    for item in resources["findings"]:
        action = _ACTION_BY_CODE[item["code"]]
        scope = (
            "sitewide"
            if item["category"] == "sitewide"
            else "page"
            if item.get("destination_url")
            else "mapping"
            if item.get("mapping_id")
            else "project"
        )
        grouped[(action, scope, item.get("source_url"), item.get("destination_url"))].append(item)
    for sequence, ((action, scope, source_url, destination_url), items) in enumerate(
        sorted(
            grouped.items(),
            key=lambda value: tuple("" if item is None else item for item in value[0]),
        )
    ):
        confidence = min((item["confidence"] for item in items), key=_CONFIDENCE_RANK.__getitem__)
        severity = max((item["severity"] for item in items), key=_SEVERITY_RANK.__getitem__)
        resources["recommendations"].append(
            {
                "stable_id": stable_identity(
                    project_id,
                    "recommendation",
                    action,
                    scope,
                    source_url or "",
                    destination_url or "",
                ),
                "project_id": project_id,
                "action": action,
                "severity": severity,
                "confidence": confidence,
                "requires_human_review": any(item["requires_human_review"] for item in items),
                "scope": scope,
                "source_url": source_url,
                "destination_url": destination_url,
                "occurrence_count": sum(int(item["occurrence_count"]) for item in items),
                "affected_page_count": len(
                    {
                        value
                        for item in items
                        for value in (item.get("source_url"), item.get("destination_url"))
                        if value
                    }
                ),
                "supporting_finding_ids_json": stable_json([item["stable_id"] for item in items]),
                "supporting_evidence_json": stable_json(
                    [_json_object(item["bounded_evidence_json"]) for item in items]
                ),
                "reason": action.replace("_", " ").capitalize(),
                "sequence": sequence,
                "created_at": items[0]["created_at"],
            }
        )


def _page_index(pages: tuple[dict[str, Any], ...]) -> dict[str, dict[str, Any]]:
    return {
        str(url): page
        for page in pages
        for url in (page.get("requested_url"), page.get("final_url"))
        if url
    }


def _content_signature(page: dict[str, Any]) -> tuple[Any, ...]:
    return (
        page.get("title_normalized_hash"),
        page.get("description_normalized_hash"),
        page.get("content_type_category"),
        page.get("canonical_url"),
        page.get("indexability_state"),
    )


def _content_score(source: dict[str, Any], destination: dict[str, Any]) -> float:
    source_values = _content_signature(source)
    destination_values = _content_signature(destination)
    comparable = [
        (left, right)
        for left, right in zip(source_values, destination_values, strict=True)
        if left is not None and right is not None
    ]
    return sum(left == right for left, right in comparable) / len(comparable) if comparable else 0.0


def _text_similarity(left: Any, right: Any) -> float:
    if not isinstance(left, str) or not isinstance(right, str):
        return 0.0
    return SequenceMatcher(
        None, " ".join(left.lower().split()), " ".join(right.lower().split())
    ).ratio()


def _material_change(left: Any, right: Any, ratio: float) -> bool:
    return _text_similarity(left, right) < 1 - ratio


def _origin(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""


def _is_staging_host(host: str) -> bool:
    labels = set(host.lower().split("."))
    return bool(labels & {"staging", "stage", "dev", "development", "test", "preview"})


def _evidence_ids(page: dict[str, Any] | None) -> tuple[str, ...]:
    return (str(page["evidence_id"]),) if page and page.get("evidence_id") else ()


def _json_list(value: Any) -> list[Any]:
    try:
        parsed = json.loads(str(value))
        return parsed if isinstance(parsed, list) else []
    except TypeError, ValueError, json.JSONDecodeError:
        return []


def _json_object(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value))
        return parsed if isinstance(parsed, dict) else {}
    except TypeError, ValueError, json.JSONDecodeError:
        return {}


def _json_union(rows: list[dict[str, Any]], key: str) -> set[str]:
    result: set[str] = set()
    for row in rows:
        value = _json_list(row.get(key))
        result.update(str(item) for item in value)
    return result


def _deduplicate_candidates(
    candidates: list[tuple[str, str, str, dict[str, Any]]],
) -> list[tuple[str, str, str, dict[str, Any]]]:
    priority = {
        name: index
        for index, name in enumerate(
            (
                "explicit_redirect_map",
                "explicit_proposed_destination",
                "observed_redirect",
                "exact_normalized_url",
                "configured_origin_substitution",
                "path_match",
                "canonical_hint",
                "content_similarity_hint",
            )
        )
    }
    selected: dict[tuple[str, str], tuple[str, str, str, dict[str, Any]]] = {}
    for item in candidates:
        selected[(item[0], item[1])] = item
    return sorted(selected.values(), key=lambda item: (priority[item[0]], item[1]))
