"""Focused Phase 23 export schema, ordering, safety, and version tests."""

# ruff: noqa: FBT003, RUF015

from __future__ import annotations

import csv
import io
import json

import pytest

from musimack_tools.domain.internal_link import (
    INTERNAL_LINK_EXPORT_VERSION,
    InternalLinkExportFormat,
)
from musimack_tools.internal_link.service import _csv_safe, _export_bytes


def _audit() -> dict[str, object]:
    return {
        "audit_id": "audit-1",
        "run_id": "run-1",
        "configuration_json": '{"enabled":true}',
        "seed_snapshot_json": '["https://example.test/"]',
        "state": "completed",
        "eligible_page_count": 2,
        "reachable_count": 1,
        "orphan_candidate_count": 1,
        "deep_page_count": 0,
        "hub_candidate_count": 1,
        "authority_candidate_count": 1,
    }


def _pages() -> list[dict[str, object]]:
    return [
        {
            "audit_id": "audit-1",
            "requested_url": "=DANGEROUS",
            "page_identity": "a",
            "eligibility": "eligible",
            "primary_state": "orphan_candidate",
            "orphan_state": "true_orphan_candidate",
            "inbound_occurrences": 0,
            "unique_referring_pages": 0,
            "outbound_occurrences": 0,
            "unique_destination_pages": 0,
            "crawl_depth": 2,
            "graph_depth": None,
            "reachable": False,
            "hub_state": "not_candidate",
            "authority_state": "not_candidate",
            "dominant_anchor": None,
            "dominant_anchor_share": 0.0,
            "severity": "high",
            "page_sequence": 0,
        },
        {
            "audit_id": "audit-1",
            "requested_url": "https://example.test/hub",
            "page_identity": "b",
            "eligibility": "eligible",
            "primary_state": "hub_candidate",
            "orphan_state": "not_orphan",
            "inbound_occurrences": 3,
            "unique_referring_pages": 2,
            "outbound_occurrences": 10,
            "unique_destination_pages": 10,
            "crawl_depth": 1,
            "graph_depth": 1,
            "reachable": True,
            "hub_state": "candidate",
            "authority_state": "candidate",
            "dominant_anchor": "hub",
            "dominant_anchor_share": 1.0,
            "severity": "info",
            "page_sequence": 1,
        },
    ]


def _anchors() -> list[dict[str, object]]:
    return [
        {
            "target_url": "https://example.test/a",
            "normalized_anchor": "click here",
            "representative_anchor": "Click Here",
            "occurrence_count": 2,
            "source_page_count": 2,
            "share": 1.0,
            "anchor_state": "generic_anchor",
            "severity": "low",
            "anchor_sequence": 0,
        }
    ]


def _opportunities() -> list[dict[str, object]]:
    return [
        {
            "source_url": "https://example.test/hub",
            "target_url": "https://example.test/a",
            "opportunity_type": "link_orphan_from_hub",
            "action": "add_internal_link",
            "confidence": "medium",
            "severity": "high",
            "reason_code": "defensible_hub_source",
            "human_review_required": True,
            "opportunity_sequence": 0,
        }
    ]


@pytest.mark.parametrize(
    ("export_format", "expected_header"),
    (
        (InternalLinkExportFormat.PAGE_METRICS_CSV, "audit_id,requested_url"),
        (InternalLinkExportFormat.ORPHANS_CSV, "requested_url,orphan_state"),
        (InternalLinkExportFormat.HUBS_AUTHORITIES_CSV, "requested_url,hub_state"),
        (InternalLinkExportFormat.ANCHORS_CSV, "target_url,normalized_anchor"),
        (InternalLinkExportFormat.OPPORTUNITIES_CSV, "source_url,target_url"),
    ),
)
def test_each_csv_has_stable_columns_rows_and_formula_defense(
    export_format: InternalLinkExportFormat, expected_header: str
) -> None:
    content, count = _export_bytes(
        _audit(),
        export_format,
        _pages(),
        _anchors(),
        _opportunities(),
        [],
        [],
        False,
    )
    text = content.decode()
    rows = list(csv.reader(io.StringIO(text)))

    assert text.startswith(expected_header)
    assert count >= 1
    assert rows[0] == list(csv.reader([text.splitlines()[0]]))[0]
    if export_format in {
        InternalLinkExportFormat.PAGE_METRICS_CSV,
        InternalLinkExportFormat.ORPHANS_CSV,
    }:
        assert "'=DANGEROUS" in text
    assert text.endswith("\n")


def test_json_is_complete_versioned_and_stably_ordered() -> None:
    first, count = _export_bytes(
        _audit(),
        InternalLinkExportFormat.JSON,
        _pages(),
        _anchors(),
        _opportunities(),
        [{"edge_sequence": 0}],
        [{"sequence": 0}],
        False,
    )
    second, _ = _export_bytes(
        _audit(),
        InternalLinkExportFormat.JSON,
        _pages(),
        _anchors(),
        _opportunities(),
        [{"edge_sequence": 0}],
        [{"sequence": 0}],
        False,
    )
    payload = json.loads(first)

    assert first == second
    assert count == 2
    assert payload["version"] == INTERNAL_LINK_EXPORT_VERSION
    assert list(payload) == [
        "anchors",
        "audit",
        "configuration",
        "edges",
        "evidence_versions",
        "opportunities",
        "pages",
        "reachability",
        "seeds",
        "truncated",
        "version",
    ]
    assert payload["pages"][0]["page_sequence"] == 0
    assert payload["opportunities"][0]["opportunity_sequence"] == 0


def test_markdown_has_required_sections_and_stable_order() -> None:
    content, count = _export_bytes(
        _audit(),
        InternalLinkExportFormat.MARKDOWN,
        _pages(),
        _anchors(),
        _opportunities(),
        [],
        [],
        False,
    )
    text = content.decode()
    sections = (
        "# Internal-Link Analysis",
        "## Configuration",
        "## Summary",
        "## Orphan Candidates",
        "## Hub and Authority Candidates",
        "## Anchor Findings",
        "## Opportunities",
        "## Methodology and limitations",
    )

    assert count == 2
    assert all(section in text for section in sections)
    assert [text.index(section) for section in sections] == sorted(
        text.index(section) for section in sections
    )
    assert "No semantic similarity" in text


def test_csv_safety_handles_all_formula_prefixes_and_structured_values() -> None:
    assert [_csv_safe(value) for value in ("=x", "+x", "-x", "@x")] == [
        "'=x",
        "'+x",
        "'-x",
        "'@x",
    ]
    assert _csv_safe({"b": 2, "a": 1}) == '{"a":1,"b":2}'
