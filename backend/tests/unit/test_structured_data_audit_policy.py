"""Direct Phase 25 structured-data policy and export contract coverage."""

# ruff: noqa: FBT001, PLR0913, TC001

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from musimack_tools.domain.structured_data_audit import (
    FINDING_CODES,
    PROFILE_REQUIRED_PROPERTIES,
    RECOGNIZED_TYPES,
    RECOMMENDATION_ACTIONS,
    STRUCTURED_DATA_PROFILE_VERSION,
    StructuredDataAuditConfiguration,
    StructuredDataExportFormat,
)
from musimack_tools.persistence.structured_data_repository import (
    SQLAlchemyStructuredDataAuditRepository,
)
from musimack_tools.structured_data_audit.service import (
    _CSV_SCHEMAS,
    _MARKDOWN_SECTIONS,
    StructuredDataAuditService,
    _csv,
    _profile_state,
)

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _service() -> StructuredDataAuditService:
    class PolicyRepository:
        def reconcile_interrupted(self) -> int:
            return 0

    return StructuredDataAuditService(
        StructuredDataAuditConfiguration(enabled=True, minimum_sitewide_pages=2),
        cast("SQLAlchemyStructuredDataAuditRepository", PolicyRepository()),
    )


class _ReadinessRepository:
    def __init__(
        self,
        context: tuple[str, str, bool, int, int] | None,
        versions: tuple[str, ...] = ("seo-toolkit-structured-data-evidence-v1",),
        *,
        expired: bool = False,
    ) -> None:
        self.context = context
        self.versions = versions
        self.expired = expired

    def reconcile_interrupted(self) -> int:
        return 0

    def run_context(self, _run_id: str) -> tuple[str, str, bool, int, int] | None:
        return self.context

    def evidence_versions(self, _run_id: str) -> tuple[str, ...]:
        return self.versions

    def pages(self, _run_id: str) -> tuple[dict[str, Any], ...]:
        return ({"retention_state": "expired" if self.expired else "active"},)

    def create(
        self, audit_id: str, job_id: str, run_id: str, _configuration: object
    ) -> dict[str, Any]:
        return {"audit_id": audit_id, "job_id": job_id, "run_id": run_id, "state": "accepted"}


def _evidence(
    sequence: int,
    *,
    page: str = "https://example.test/",
    format_name: str = "json_ld",
    raw: str = "{}",
    parse_status: str = "parsed",
    contexts: tuple[str, ...] = ("https://schema.org",),
    types: tuple[str, ...] = ("Organization",),
    identifiers: tuple[str, ...] = (),
    properties: dict[str, list[str]] | None = None,
    references: tuple[str, ...] = (),
    diagnostics: tuple[str, ...] = (),
    fingerprint: str | None = None,
    raw_fingerprint: str | None = None,
    normalized: bool = True,
    truncated: bool = False,
    script_type: str | None = "application/ld+json",
) -> dict[str, Any]:
    return {
        "block_id": f"block-{sequence}",
        "source_requested_url": page,
        "source_final_url": page,
        "source_locator": f"node[{sequence}]",
        "format": format_name,
        "raw_value": raw,
        "parse_status": parse_status,
        "parse_error": "JSONDecodeError:1:2" if parse_status != "parsed" else None,
        "contexts_json": json.dumps(contexts),
        "types_json": json.dumps(types),
        "identifiers_json": json.dumps(identifiers),
        "properties_json": json.dumps(properties or {}),
        "references_json": json.dumps(references),
        "diagnostics_json": json.dumps(diagnostics),
        "normalized_fingerprint": fingerprint if normalized else None,
        "raw_fingerprint": raw_fingerprint or fingerprint or f"fingerprint-{sequence}",
        "value_truncated": truncated,
        "script_type": script_type,
    }


def _page(
    url: str,
    *,
    content_type: str = "text/html; charset=utf-8",
    status: int = 200,
    indexability: str = "indexable",
) -> dict[str, Any]:
    return {
        "requested_url": url,
        "final_url": url,
        "content_type": content_type,
        "http_status": status,
        "indexability_state": indexability,
    }


def _taxonomy_fixture() -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
    root = "https://example.test/"
    review = "https://example.test/review"
    error = "https://example.test/error"
    evidence = (
        _evidence(1, raw="{", parse_status="invalid", contexts=(), types=()),
        _evidence(2, raw=" ", parse_status="invalid", contexts=(), types=()),
        _evidence(3, raw='"scalar"', contexts=(), types=()),
        _evidence(
            4,
            raw='{"@context":"https://external.test","@type":"Mystery"}',
            contexts=("https://external.test",),
            types=("Mystery",),
            script_type="application/json+ld",
        ),
        _evidence(5, truncated=True),
        _evidence(51, types=("bad type",)),
        _evidence(
            6,
            format_name="microdata",
            raw="{}",
            contexts=(),
            types=(),
            properties={},
            references=("missing",),
            diagnostics=(
                "microdata_property_outside_scope",
                "microdata_invalid_itemid",
                "microdata_unresolved_itemref:missing",
            ),
            script_type=None,
        ),
        _evidence(
            7,
            format_name="rdfa",
            contexts=(),
            types=("Person",),
            properties={"name": ["Ada"]},
            diagnostics=("rdfa_invalid_prefix_mapping", "rdfa_unsupported_pattern"),
            script_type=None,
        ),
        _evidence(
            8,
            identifiers=("#shared",),
            properties={"name": ["Example"], "url": ["https://example.test"]},
            fingerprint="duplicate-json",
        ),
        _evidence(
            9,
            types=("Product",),
            identifiers=("#shared",),
            properties={"name": ["Widget"], "offers": ["[reference]"]},
        ),
        _evidence(
            10,
            identifiers=("#shared",),
            properties={"name": ["Example"], "url": ["https://example.test"]},
            fingerprint="duplicate-json",
        ),
        _evidence(
            11,
            types=("Product",),
            properties={"name": ["", ""], "url": ["/relative"]},
            references=("#missing",),
            diagnostics=("property_missing_value:name",),
        ),
        _evidence(
            12,
            page=review,
            types=("LocalBusiness",),
            properties={"name": ["Shop"], "address": ["One", "Two"]},
        ),
        _evidence(
            13,
            page=review,
            format_name="microdata",
            contexts=(),
            types=("Thing",),
            properties={"name": ["Repeated"]},
            fingerprint="duplicate-microdata",
            script_type=None,
        ),
        _evidence(
            14,
            page=review,
            format_name="microdata",
            contexts=(),
            types=("Thing",),
            properties={"name": ["Repeated"]},
            fingerprint="duplicate-microdata",
            script_type=None,
        ),
        _evidence(
            15,
            page=review,
            types=("BreadcrumbList",),
            properties={},
        ),
        _evidence(
            16,
            page=review,
            types=("Article",),
            properties={
                "headline": ["Story"],
                "author": ["[structured]"],
                "datePublished": ["bad-date"],
            },
        ),
        _evidence(
            17,
            page=error,
            identifiers=("#shared",),
            properties={"name": ["Different"], "url": ["https://other.test"]},
        ),
    )
    pages = (
        _page(root),
        _page(review),
        _page(
            error,
            content_type="application/pdf",
            status=500,
            indexability="non_indexable",
        ),
    )
    return evidence, pages


def test_every_finding_and_recommendation_is_behaviorally_reachable_with_metadata() -> None:
    evidence, pages = _taxonomy_fixture()
    resources = _service()._analyze("audit-policy", evidence, pages)  # noqa: SLF001
    findings = resources["parse-findings"] + resources["consistency-findings"]
    assert {item["code"] for item in findings} == FINDING_CODES
    for item in findings:
        assert item["confidence"] in {"high", "medium", "low", "indeterminate"}
        assert isinstance(item["requires_human_review"], bool)
        linked = json.loads(item["evidence_json"])
        assert set(linked) == {"block_ids", "entity_ids", "page_urls"}
    recommendations = resources["recommendations"]
    assert {item["action"] for item in recommendations} == RECOMMENDATION_ACTIONS
    assert [item["id"] for item in recommendations] == sorted(
        item["id"] for item in recommendations
    )
    for item in recommendations:
        assert item["confidence"] in {"high", "medium", "low", "indeterminate"}
        assert item["requires_human_review"] is True
        assert item["scope"] in {"page", "entity", "site"}
        assert item["occurrence_count"] >= 1
        assert item["affected_page_count"] >= 0
        assert isinstance(json.loads(item["supporting_finding_ids_json"]), list)
        assert isinstance(json.loads(item["supporting_evidence_json"]), dict)
        assert "</script>" not in item["explanation"]


@pytest.mark.parametrize(
    ("case", "context", "versions", "expired", "ready", "error"),
    (
        (
            "compatible",
            ("job", "completed", True, 1, 1),
            ("seo-toolkit-structured-data-evidence-v1",),
            False,
            True,
            None,
        ),
        (
            "failed-partial",
            ("job", "failed", True, 1, 1),
            ("seo-toolkit-structured-data-evidence-v1",),
            False,
            True,
            None,
        ),
        (
            "nonterminal",
            ("job", "running", False, 1, 1),
            ("seo-toolkit-structured-data-evidence-v1",),
            False,
            False,
            "structured_data_audit_run_not_terminal",
        ),
        (
            "missing-pages",
            ("job", "completed", True, 0, 1),
            ("seo-toolkit-structured-data-evidence-v1",),
            False,
            False,
            "structured_data_audit_page_evidence_unavailable",
        ),
        (
            "missing-evidence",
            ("job", "completed", True, 1, 0),
            (),
            False,
            False,
            "structured_data_audit_evidence_unavailable",
        ),
        (
            "unsupported-version",
            ("job", "completed", True, 1, 1),
            ("legacy",),
            False,
            False,
            "structured_data_audit_evidence_version_unsupported",
        ),
        (
            "expired",
            ("job", "completed", True, 1, 1),
            ("seo-toolkit-structured-data-evidence-v1",),
            True,
            False,
            "structured_data_audit_evidence_expired",
        ),
    ),
)
def test_readiness_contract_has_no_silent_empty_audit(
    case: str,
    context: tuple[str, str, bool, int, int],
    versions: tuple[str, ...],
    expired: bool,
    ready: bool,
    error: str | None,
) -> None:
    del case
    repository = _ReadinessRepository(context, versions, expired=expired)
    service = StructuredDataAuditService(
        StructuredDataAuditConfiguration(enabled=True),
        cast("SQLAlchemyStructuredDataAuditRepository", repository),
    )
    assert service.evidence_status("run")["ready"] is ready
    if error is None:
        assert service.create_audit("run")["state"] == "accepted"
    else:
        with pytest.raises(ValueError, match=error):
            service.create_audit("run")


def test_readiness_missing_run_is_typed() -> None:
    service = StructuredDataAuditService(
        StructuredDataAuditConfiguration(enabled=True),
        cast("SQLAlchemyStructuredDataAuditRepository", _ReadinessRepository(None)),
    )
    with pytest.raises(ValueError, match="structured_data_audit_run_not_found"):
        service.evidence_status("missing")


@pytest.mark.parametrize("code", sorted(FINDING_CODES))
def test_each_finding_code_has_direct_behavioral_evidence(code: str) -> None:
    evidence, pages = _taxonomy_fixture()
    resources = _service()._analyze("audit-finding-matrix", evidence, pages)  # noqa: SLF001
    matching = [
        item
        for name in ("parse-findings", "consistency-findings")
        for item in resources[name]
        if item["code"] == code
    ]
    assert matching, code
    assert all(item["confidence"] for item in matching)
    assert all(json.loads(item["evidence_json"]) is not None for item in matching)


@pytest.mark.parametrize("action", sorted(RECOMMENDATION_ACTIONS))
def test_each_recommendation_action_has_direct_behavioral_evidence(action: str) -> None:
    evidence, pages = _taxonomy_fixture()
    resources = _service()._analyze("audit-recommendation-matrix", evidence, pages)  # noqa: SLF001
    matching = [item for item in resources["recommendations"] if item["action"] == action]
    assert matching, action
    assert all(item["requires_human_review"] is True for item in matching)
    assert all(item["occurrence_count"] >= 1 for item in matching)


@pytest.mark.parametrize("entity_type", sorted(RECOGNIZED_TYPES))
def test_each_recognized_type_is_not_labeled_invalid_or_unknown(entity_type: str) -> None:
    resources = _service()._analyze(  # noqa: SLF001
        f"audit-recognized-{entity_type}",
        (_evidence(1, types=(entity_type,)),),
        (_page("https://example.test/"),),
    )
    assert "json_ld_invalid_type" not in {
        item["code"] for item in resources["consistency-findings"]
    }
    assert "review_unknown_type" not in {item["action"] for item in resources["recommendations"]}


@pytest.mark.parametrize(
    ("entity_type", "expect_invalid", "expect_review"),
    (
        ("CustomType", False, True),
        ("https://external.test/Custom", False, True),
        ("bad type", True, True),
        ("@invalid", True, True),
    ),
)
def test_unknown_external_and_malformed_type_boundaries(
    entity_type: str, expect_invalid: bool, expect_review: bool
) -> None:
    resources = _service()._analyze(  # noqa: SLF001
        "audit-type-boundary",
        (_evidence(1, types=(entity_type,)),),
        (_page("https://example.test/"),),
    )
    codes = {item["code"] for item in resources["consistency-findings"]}
    actions = {item["action"] for item in resources["recommendations"]}
    assert ("json_ld_invalid_type" in codes) is expect_invalid
    assert ("review_unknown_type" in actions) is expect_review


@pytest.mark.parametrize("profile_name", sorted(PROFILE_REQUIRED_PROPERTIES))
def test_each_profile_is_versioned_and_non_certifying(profile_name: str) -> None:
    valid_values = {
        "name": ["Example"],
        "url": ["https://example.test"],
        "address": ["1 Main Street"],
        "headline": ["Story"],
        "author": ["[reference]"],
        "publisher": ["[reference]"],
        "datePublished": ["2026-01-02"],
        "itemListElement": ["[reference]"],
        "offers": ["[reference]"],
        "price": ["12.50"],
        "priceCurrency": ["USD"],
        "mainEntity": ["[reference]"],
        "startDate": ["2026-01-02"],
        "location": ["[reference]"],
    }
    target: list[dict[str, Any]] = []
    _service()._profiles(  # noqa: SLF001
        target,
        "audit-profile",
        f"entity-{profile_name}",
        profile_name,
        valid_values,
        _NOW,
    )
    assert target
    assert {item["profile_name"] for item in target} == {profile_name}
    assert {item["profile_version"] for item in target} == {STRUCTURED_DATA_PROFILE_VERSION}
    assert all("does not certify" in item["explanation"] for item in target)


def test_new_findings_do_not_emit_for_neighboring_supported_evidence() -> None:
    evidence = (
        _evidence(
            1,
            properties={"name": ["Example"], "url": ["https://example.test"]},
            identifiers=("#org",),
        ),
        _evidence(
            2,
            format_name="microdata",
            contexts=(),
            types=("Person",),
            identifiers=("https://example.test/#person",),
            properties={"name": ["Ada"]},
            script_type=None,
        ),
        _evidence(
            3,
            format_name="rdfa",
            contexts=("schema: https://schema.org/",),
            types=("Person",),
            identifiers=("#person",),
            properties={"name": ["Ada"]},
            script_type=None,
        ),
    )
    resources = _service()._analyze(  # noqa: SLF001
        "audit-valid", evidence, (_page("https://example.test/"),)
    )
    codes = {
        item["code"]
        for name in ("parse-findings", "consistency-findings")
        for item in resources[name]
    }
    assert not codes & {
        "microdata_property_outside_scope",
        "microdata_invalid_itemid",
        "rdfa_invalid_prefix_mapping",
        "rdfa_unsupported_pattern",
        "entity_conflicting_types",
        "property_missing_value",
        "page_structured_data_on_non_html_content",
    }


@pytest.mark.parametrize(
    "property_name",
    (
        "name",
        "url",
        "telephone",
        "address",
        "logo",
        "itemListElement",
        "publisher",
        "author",
        "productID",
        "priceCurrency",
        "serviceType",
    ),
)
def test_cross_page_consistency_compares_retained_values_without_selecting_authority(
    property_name: str,
) -> None:
    first = "https://example.test/one"
    second = "https://example.test/two"
    resources = _service()._analyze(  # noqa: SLF001
        "audit-consistency",
        (
            _evidence(
                1,
                page=first,
                identifiers=("#shared",),
                properties={property_name: ["value-one"]},
            ),
            _evidence(
                2,
                page=second,
                identifiers=("#shared",),
                properties={property_name: ["value-two"]},
            ),
        ),
        (_page(first), _page(second)),
    )
    finding = next(
        item
        for item in resources["consistency-findings"]
        if item["code"] == "entity_inconsistent_across_pages"
    )
    assert finding["requires_human_review"] is True
    assert "value-one" not in finding["explanation"]
    assert "value-two" not in finding["explanation"]


def test_matching_entities_and_small_crawls_do_not_emit_sitewide_inconsistency() -> None:
    first = "https://example.test/one"
    second = "https://example.test/two"
    service = StructuredDataAuditService(
        StructuredDataAuditConfiguration(enabled=True, minimum_sitewide_pages=3),
        _service()._repository,  # noqa: SLF001
    )
    resources = service._analyze(  # noqa: SLF001
        "audit-small-crawl",
        (
            _evidence(1, page=first, identifiers=("#shared",), properties={"name": ["Same"]}),
            _evidence(2, page=second, identifiers=("#shared",), properties={"name": ["Same"]}),
        ),
        (_page(first), _page(second)),
    )
    codes = {item["code"] for item in resources["consistency-findings"]}
    assert "entity_inconsistent_across_pages" not in codes
    assert "sitewide_schema_inconsistency" not in codes


def test_duplicate_groups_record_safe_normalization_and_raw_fallback_without_semantic_claims() -> (
    None
):
    evidence = (
        _evidence(1, fingerprint="normalized", raw_fingerprint="raw-one"),
        _evidence(2, fingerprint="normalized", raw_fingerprint="raw-two"),
        _evidence(3, fingerprint="raw-fallback", normalized=False),
        _evidence(4, fingerprint="raw-fallback", normalized=False),
    )
    groups = _service()._analyze(  # noqa: SLF001
        "audit-duplicates", evidence, (_page("https://example.test/"),)
    )["duplicate-groups"]
    assert [group["id"] for group in groups] == sorted(group["id"] for group in groups)
    by_basis = {group["comparison_basis"]: group for group in groups}
    assert by_basis["normalized"]["normalized_fingerprint"] == "normalized"
    assert by_basis["normalized"]["raw_fingerprint"] == "raw-one"
    assert by_basis["raw_fallback"]["normalized_fingerprint"] is None
    assert by_basis["raw_fallback"]["raw_fingerprint"] == "raw-fallback"
    assert {group["classification"] for group in groups} == {"on_page_duplicate"}


@pytest.mark.parametrize(
    ("case", "property_name", "values", "applicable", "expected"),
    (
        ("present", "name", ["Example"], True, "present"),
        ("missing", "name", None, True, "missing"),
        ("empty", "name", [""], True, "empty"),
        ("invalid", "url", ["/relative"], True, "invalid"),
        ("conflicting", "name", ["One", "Two"], True, "conflicting"),
        ("not-applicable", "name", ["Example"], False, "not_applicable"),
        ("indeterminate", "publisher", ["[structured]"], True, "indeterminate"),
    ),
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_profile_state_policy(
    case: str,
    property_name: str,
    values: object,
    applicable: bool,
    expected: str,
) -> None:
    del case
    assert _profile_state(property_name, values, applicable=applicable) == expected


@pytest.mark.parametrize("prefix", ("=", "+", "-", "@"))
def test_csv_formula_prefixes_are_protected_without_changing_numbers(prefix: str) -> None:
    content = _csv(
        [{"id": f"{prefix}formula", "audit_id": 17}],
        ("id", "audit_id"),
    )
    assert f"'{prefix}formula" in content
    assert ",17" in content


@pytest.mark.parametrize("export_format", tuple(_CSV_SCHEMAS), ids=lambda value: value.value)
def test_every_csv_export_has_a_fixed_empty_schema(
    export_format: StructuredDataExportFormat,
) -> None:
    content = _csv([], _CSV_SCHEMAS[export_format])
    assert content.splitlines() == [",".join(_CSV_SCHEMAS[export_format])]


def test_markdown_contract_lists_every_required_section() -> None:
    assert _MARKDOWN_SECTIONS == (
        "Executive Summary",
        "Scope",
        "Evidence Readiness",
        "Format Distribution",
        "Type Distribution",
        "Parse and Syntax Findings",
        "Entity Consistency Findings",
        "Page-Level Findings",
        "Sitewide Findings",
        "Duplicate Groups",
        "Profile Observations",
        "Recommendations",
        "Limitations",
        "Human-Review Notes",
    )
