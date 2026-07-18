"""Versioned, deterministic policy for evidence-backed website migration QA."""

# ruff: noqa: ANN401, E501, PLR2004, SIM905, TRY300, TRY301

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

MIGRATION_QA_API_VERSION = "1.0"
MIGRATION_QA_POLICY_VERSION = "1.0"
MIGRATION_QA_EVIDENCE_VERSION = "1.0"
MIGRATION_QA_EXPORT_SCHEMA = "musimack-website-migration-qa"


class MigrationQaMode(StrEnum):
    PRE_LAUNCH = "pre_launch"
    POST_LAUNCH = "post_launch"


class MigrationType(StrEnum):
    DOMAIN = "domain"
    PROTOCOL = "protocol"
    SUBDOMAIN = "subdomain"
    CMS = "cms"
    PLATFORM = "platform"
    URL_STRUCTURE = "url_structure"
    REDESIGN = "redesign"
    CONSOLIDATION = "consolidation"
    SPLIT = "split"
    INTERNATIONALIZATION = "internationalization"
    OTHER = "other"


class MigrationQaState(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MigrationQaReadiness(StrEnum):
    READY = "ready"
    READY_WITH_WARNINGS = "ready_with_warnings"
    INCOMPATIBLE = "incompatible"
    EXPIRED = "expired"
    MISSING_EVIDENCE = "missing_evidence"
    INVALID_CONFIGURATION = "invalid_configuration"


class MigrationQaExportFormat(StrEnum):
    FINDINGS_CSV = "findings_csv"
    REDIRECTS_CSV = "redirects_csv"
    MAPPINGS_CSV = "mappings_csv"
    COMPARISONS_CSV = "comparisons_csv"
    RECOMMENDATIONS_CSV = "recommendations_csv"
    SITEWIDE_CSV = "sitewide_csv"
    JSON = "json"
    MARKDOWN = "markdown"


FINDING_CODES_BY_CATEGORY: dict[str, frozenset[str]] = {
    "inventory": frozenset(
        "inventory_invalid_url inventory_unsupported_scheme inventory_out_of_scope "
        "inventory_duplicate_source inventory_conflicting_destination inventory_field_too_long".split()
    ),
    "mapping": frozenset(
        "mapping_unmapped mapping_ambiguous mapping_many_to_one mapping_one_to_many "
        "mapping_destination_collision mapping_conflicting_explicit".split()
    ),
    "redirect": frozenset(
        """
        redirect_missing redirect_wrong_destination redirect_temporary redirect_chain redirect_loop
        redirect_to_error redirect_to_nonindexable redirect_to_external redirect_to_out_of_scope
        redirect_status_mismatch redirect_query_dropped redirect_query_unexpectedly_preserved
        redirect_fragment_policy_mismatch redirect_many_to_one_review redirect_one_to_many_review
        redirect_destination_collision redirect_map_duplicate_source redirect_map_conflicting_destination
        redirect_map_loop redirect_map_chain redirect_map_invalid_url
        """.split()
    ),
    "destination": frozenset(
        """
        destination_missing destination_404 destination_410 destination_other_4xx destination_5xx
        destination_redirecting destination_non_html destination_noindex destination_blocked_by_robots
        destination_canonical_elsewhere destination_canonical_missing destination_canonical_invalid
        destination_status_unknown
        """.split()
    ),
    "metadata": frozenset(
        """
        title_missing_after_migration title_materially_changed
        meta_description_missing_after_migration meta_description_materially_changed
        canonical_target_changed canonical_regression robots_regression indexability_regression
        content_type_changed language_changed source_metadata_unavailable
        """.split()
    ),
    "content": frozenset(
        """
        content_likely_preserved content_materially_changed content_missing content_similarity_low
        content_similarity_indeterminate content_consolidated content_split_review
        """.split()
    ),
    "canonical": frozenset(
        """
        canonical_points_to_legacy_url canonical_points_to_wrong_host canonical_points_to_redirect
        canonical_points_to_error canonical_self_reference_regression canonical_conflicts_with_redirect
        """.split()
    ),
    "indexability": frozenset(
        """
        destination_noindex_regression destination_robots_block_regression legacy_url_still_indexable
        duplicate_source_and_destination_indexable
        """.split()
    ),
    "internal_links": frozenset(
        """
        internal_link_to_legacy_url internal_link_to_redirect internal_link_to_broken_destination
        internal_link_to_staging_host internal_link_host_mismatch destination_orphan_candidate
        navigation_target_regression source_link_target_unmapped redirect_dependency_sitewide
        """.split()
    ),
    "sitemap": frozenset(
        """
        legacy_url_in_destination_sitemap destination_url_missing_from_sitemap redirecting_url_in_sitemap
        broken_url_in_sitemap nonindexable_url_in_sitemap canonical_conflict_in_sitemap
        sitemap_host_mismatch sitemap_evidence_unavailable
        """.split()
    ),
    "images": frozenset(
        """
        image_missing_after_migration image_broken_after_migration image_legacy_host_reference
        image_staging_host_reference image_alt_missing_after_migration image_alt_materially_changed
        image_redirect_dependency image_dimension_regression image_loading_regression
        """.split()
    ),
    "structured_data": frozenset(
        """
        structured_data_removed structured_data_type_changed structured_data_entity_id_changed
        structured_data_identity_conflict structured_data_profile_regression
        structured_data_invalid_after_migration structured_data_nonindexable_destination
        structured_data_format_changed
        """.split()
    ),
    "sitewide": frozenset(
        """
        sitewide_legacy_host_references sitewide_staging_host_references sitewide_redirect_dependency
        sitewide_redirect_chain_pattern sitewide_temporary_redirect_pattern sitewide_noindex_regression
        sitewide_canonical_host_mismatch sitewide_metadata_loss sitewide_sitemap_regression
        sitewide_structured_data_loss sitewide_image_host_regression sitewide_unmapped_source_urls
        sitewide_destination_errors
        """.split()
    ),
    "readiness": frozenset(
        "readiness_missing_evidence readiness_incompatible_evidence readiness_expired_evidence "
        "readiness_invalid_configuration".split()
    ),
}
FINDING_CODES = frozenset().union(*FINDING_CODES_BY_CATEGORY.values())

RECOMMENDATION_ACTIONS = frozenset(
    """
    add_missing_redirect correct_redirect_destination replace_temporary_redirect shorten_redirect_chain
    resolve_redirect_loop fix_redirect_to_error review_many_to_one_mapping review_one_to_many_mapping
    resolve_mapping_conflict map_unmatched_source_url restore_missing_destination_page
    fix_destination_error remove_destination_noindex review_robots_block correct_destination_canonical
    update_internal_legacy_links replace_internal_redirect_links fix_broken_internal_links
    remove_staging_host_references update_destination_sitemap remove_legacy_urls_from_sitemap
    restore_missing_metadata review_material_metadata_change review_content_continuity
    review_canonical_conflict review_indexability_regression restore_image_reference
    restore_image_alt_text review_image_regression restore_structured_data
    review_structured_data_change review_sitewide_migration_pattern verify_manual_mapping
    review_query_string_policy review_fragment_policy
    """.split()
)

MAPPING_METHODS = frozenset(
    """
    explicit_redirect_map explicit_proposed_destination observed_redirect exact_normalized_url
    configured_origin_substitution path_match canonical_hint content_similarity_hint
    manual_review_candidate unmapped
    """.split()
)
MAPPING_CARDINALITIES = frozenset("one_to_one many_to_one one_to_many unmapped ambiguous".split())
CONFIDENCE_STATES = frozenset("high medium low indeterminate".split())


@dataclass(frozen=True, slots=True)
class MigrationQaConfiguration:
    enabled: bool = False
    default_page_size: int = 50
    maximum_page_size: int = 200
    maximum_inventory_rows: int = 50_000
    maximum_redirect_rows: int = 50_000
    maximum_export_rows: int = 100_000
    maximum_input_bytes: int = 10_000_000
    retention_days: int = 30
    preserve_query_parameters: bool = True
    compare_fragments: bool = False
    minimum_sitewide_pages: int = 10
    material_content_change_ratio: float = 0.35
    maximum_field_characters: int = 4096
    evidence_max_age_days: int = 365
    sitewide_issue_ratio: float = 0.20
    compare_internal_links: bool = False
    compare_sitemaps: bool = False
    compare_images: bool = False
    compare_structured_data: bool = False

    def __post_init__(self) -> None:
        if not 1 <= self.default_page_size <= self.maximum_page_size <= 1_000:
            raise ValueError("migration_qa_invalid_page_size")
        if (
            min(
                self.maximum_inventory_rows,
                self.maximum_redirect_rows,
                self.maximum_export_rows,
                self.maximum_input_bytes,
                self.retention_days,
                self.minimum_sitewide_pages,
                self.maximum_field_characters,
                self.evidence_max_age_days,
            )
            < 1
        ):
            raise ValueError("migration_qa_invalid_configuration")
        if not 0 <= self.material_content_change_ratio <= 1:
            raise ValueError("migration_qa_invalid_configuration")
        if not 0 < self.sitewide_issue_ratio <= 1:
            raise ValueError("migration_qa_invalid_configuration")

    def snapshot(self) -> dict[str, Any]:
        return asdict(self)


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def stable_identity(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def encode_cursor(kind: str, fingerprint: str, offset: int) -> str:
    raw = stable_json({"kind": kind, "fingerprint": fingerprint, "offset": offset}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str, kind: str, fingerprint: str) -> int:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        value = json.loads(raw)
        if value["kind"] != kind or value["fingerprint"] != fingerprint:
            raise ValueError
        offset = int(value["offset"])
        if offset < 0:
            raise ValueError
        return offset
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("migration_qa_cursor_mismatch") from error


_ERROR_CODES = frozenset(
    """
    redirect_loop redirect_to_error redirect_map_loop destination_404 destination_410
    destination_5xx content_missing canonical_points_to_error internal_link_to_broken_destination
    broken_url_in_sitemap image_broken_after_migration structured_data_invalid_after_migration
    """.split()
)
_INFO_CODES = frozenset("content_likely_preserved structured_data_format_changed".split())
_REVIEW_CODES = frozenset(
    """
    mapping_ambiguous mapping_many_to_one mapping_one_to_many redirect_many_to_one_review
    redirect_one_to_many_review content_materially_changed content_similarity_low
    content_similarity_indeterminate content_consolidated content_split_review
    title_materially_changed meta_description_materially_changed canonical_target_changed
    language_changed destination_orphan_candidate image_alt_materially_changed
    image_dimension_regression image_loading_regression structured_data_type_changed
    structured_data_entity_id_changed structured_data_identity_conflict
    structured_data_profile_regression structured_data_format_changed
    """.split()
)


def classify_migration_finding(
    code: str,
    evidence: dict[str, Any],
    *,
    confidence: str | None = None,
) -> dict[str, Any]:
    """Return the explicit policy projection for one accepted finding code."""
    if code not in FINDING_CODES:
        raise ValueError("migration_qa_unknown_finding_code")
    category = next(
        category
        for category, category_codes in FINDING_CODES_BY_CATEGORY.items()
        if code in category_codes
    )
    selected_confidence = confidence or (
        "indeterminate"
        if code in {"content_similarity_indeterminate", "readiness_missing_evidence"}
        else "high"
    )
    if selected_confidence not in CONFIDENCE_STATES:
        raise ValueError("migration_qa_invalid_confidence")
    return {
        "code": code,
        "category": category,
        "severity": "error"
        if code in _ERROR_CODES
        else "info"
        if code in _INFO_CODES
        else "warning",
        "confidence": selected_confidence,
        "requires_human_review": code in _REVIEW_CODES
        or selected_confidence in {"low", "indeterminate"},
        "evidence": evidence,
    }
