"""Deterministic contracts for structured-data audits."""

# ruff: noqa: ANN401, E501, PLR2004, SIM905, TRY003

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

STRUCTURED_DATA_AUDIT_VERSION = "seo-toolkit-structured-data-audit-v1"
STRUCTURED_DATA_POLICY_VERSION = "seo-toolkit-structured-data-policy-v1"
STRUCTURED_DATA_PROFILE_VERSION = "seo-toolkit-structured-data-profiles-v1"
STRUCTURED_DATA_API_VERSION = "seo-toolkit-structured-data-api-v1"


class StructuredDataLifecycle(StrEnum):
    ACCEPTED = "accepted"
    CLAIMING = "claiming"
    BUILDING_INVENTORY = "building_inventory"
    ANALYZING_ENTITIES = "analyzing_entities"
    EVALUATING_PROFILES = "evaluating_profiles"
    ANALYZING_CONSISTENCY = "analyzing_consistency"
    BUILDING_RECOMMENDATIONS = "building_recommendations"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StructuredDataExportFormat(StrEnum):
    INVENTORY_CSV = "structured_data_inventory_csv"
    ENTITY_CSV = "entity_inventory_csv"
    PROPERTY_CSV = "property_findings_csv"
    DUPLICATE_CSV = "duplicate_groups_csv"
    PAGE_CSV = "page_summaries_csv"
    RECOMMENDATIONS_CSV = "recommendations_csv"
    JSON = "json"
    MARKDOWN = "markdown"


FINDING_CODES = frozenset(
    """json_ld_invalid_json json_ld_empty_block json_ld_scalar_root json_ld_missing_context
    json_ld_unrecognized_context json_ld_missing_type json_ld_invalid_type
    json_ld_duplicate_entity_id json_ld_duplicate_block json_ld_truncated
    json_ld_unsupported_script_type microdata_missing_itemtype microdata_empty_itemscope
    microdata_unresolved_itemref microdata_property_outside_scope microdata_invalid_itemid
    rdfa_missing_vocabulary_context rdfa_property_without_subject rdfa_invalid_prefix_mapping
    rdfa_unsupported_pattern entity_missing_identifier entity_conflicting_types
    entity_duplicate_on_page entity_inconsistent_across_pages property_missing_value
    property_empty_value property_duplicate_value property_url_invalid property_reference_unresolved
    page_multiple_primary_entities page_structured_data_on_non_html_content
    page_structured_data_on_error_status page_structured_data_on_nonindexable_page
    sitewide_schema_inconsistency""".split()
)

RECOMMENDATION_ACTIONS = frozenset(
    """fix_invalid_json_ld remove_empty_structured_data_block add_missing_context add_missing_type
    review_unknown_type resolve_duplicate_entity_id consolidate_duplicate_entity
    resolve_conflicting_entity_types resolve_inconsistent_entity_values
    add_missing_required_profile_property fix_empty_property fix_invalid_property_url
    resolve_unresolved_reference review_multiple_primary_entities review_nonindexable_page_schema
    review_error_page_schema review_schema_format_mix review_sitewide_schema_inconsistency
    review_local_business_subtype review_organization_identity review_breadcrumb_structure
    review_article_publisher review_product_offer_relationship review_external_context
    review_truncated_evidence""".split()
)

RECOGNIZED_TYPES = frozenset(
    """Organization LocalBusiness ProfessionalService MedicalBusiness Physician Dentist Hotel
    LodgingBusiness Restaurant Product Offer Service WebSite WebPage AboutPage ContactPage
    CollectionPage Article BlogPosting NewsArticle FAQPage QAPage HowTo BreadcrumbList ItemList
    Person Event Place PostalAddress AggregateRating Review ImageObject VideoObject SearchAction
    SiteNavigationElement""".split()
)

PROFILE_REQUIRED_PROPERTIES: dict[str, tuple[str, ...]] = {
    "Organization": ("name", "url"),
    "LocalBusiness": ("name", "address"),
    "WebSite": ("name", "url"),
    "WebPage": ("name", "url"),
    "Article": ("headline", "author", "publisher", "datePublished"),
    "BlogPosting": ("headline", "author", "publisher", "datePublished"),
    "BreadcrumbList": ("itemListElement",),
    "Product": ("name", "offers"),
    "Offer": ("price", "priceCurrency"),
    "FAQPage": ("mainEntity",),
    "Event": ("name", "startDate", "location"),
    "Person": ("name",),
    "Hotel": ("name", "address"),
    "LodgingBusiness": ("name", "address"),
    "Restaurant": ("name", "address"),
    "Service": ("name",),
}


@dataclass(frozen=True, slots=True)
class StructuredDataAuditConfiguration:
    enabled: bool = False
    default_page_size: int = 50
    maximum_page_size: int = 200
    maximum_export_rows: int = 100_000
    retention_days: int = 180
    minimum_sitewide_pages: int = 3

    def __post_init__(self) -> None:
        if not 1 <= self.default_page_size <= self.maximum_page_size <= 1_000:
            raise ValueError("structured data audit page sizes are invalid")
        if not 1 <= self.maximum_export_rows <= 1_000_000:
            raise ValueError("structured data audit export limit is invalid")
        if not 1 <= self.retention_days <= 3_650:
            raise ValueError("structured data audit retention is invalid")
        if not 1 <= self.minimum_sitewide_pages <= 10_000:
            raise ValueError("structured data audit sitewide threshold is invalid")

    def snapshot(self) -> dict[str, Any]:
        return asdict(self)


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def stable_identity(*values: object) -> str:
    return hashlib.sha256("\0".join(str(value) for value in values).encode()).hexdigest()


def audit_identity(run_id: str, configuration: StructuredDataAuditConfiguration) -> str:
    return f"structured-data-audit-{stable_identity(run_id, stable_json(configuration.snapshot()))[:24]}"


def encode_cursor(kind: str, fingerprint: str, offset: int) -> str:
    return (
        base64.urlsafe_b64encode(stable_json({"f": fingerprint, "k": kind, "o": offset}).encode())
        .decode()
        .rstrip("=")
    )


def decode_cursor(value: str, kind: str, fingerprint: str) -> int:
    try:
        payload = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        offset = int(payload["o"])
    except KeyError, TypeError, ValueError, json.JSONDecodeError:
        raise ValueError("structured_data_audit_invalid_cursor") from None
    if payload != {"f": fingerprint, "k": kind, "o": payload["o"]}:
        raise ValueError("structured_data_audit_cursor_filter_mismatch")
    if offset < 0:
        raise ValueError("structured_data_audit_invalid_cursor")
    return offset
