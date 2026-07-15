"""Tests for X-Robots-Tag and combined indexability evidence."""

from __future__ import annotations

from musimack_tools.crawl.indexability import IndexabilityEvidenceParser
from musimack_tools.domain.html import MetaRobotsRecord, RobotsDirective
from musimack_tools.domain.indexability import (
    IndexabilityConflictKind,
    IndexabilityWarningCode,
)


def _meta(*names: str, agent: str = "robots") -> MetaRobotsRecord:
    directives = tuple(
        RobotsDirective(name=name, value=None, raw_value=name, known=True) for name in names
    )
    return MetaRobotsRecord(agent, ", ".join(names), directives, 0)


def test_single_generic_header_preserves_raw_value_and_order() -> None:
    evidence = IndexabilityEvidenceParser().parse_x_robots_tag(("noindex",))

    assert evidence.records[0].raw_value == "noindex"
    assert evidence.records[0].agent_name is None
    assert evidence.records[0].directives[0].name == "noindex"


def test_repeated_headers_remain_separate_and_ordered() -> None:
    evidence = IndexabilityEvidenceParser().parse_x_robots_tag(("noindex", "nofollow"))

    assert [item.raw_value for item in evidence.records] == ["noindex", "nofollow"]
    assert [item.occurrence_index for item in evidence.records] == [0, 1]


def test_noindex_and_nofollow_are_parsed_from_one_header() -> None:
    evidence = IndexabilityEvidenceParser().parse_x_robots_tag(("noindex, nofollow",))

    assert [item.name for item in evidence.records[0].directives] == ["noindex", "nofollow"]


def test_none_directive_is_recognized_without_computing_a_verdict() -> None:
    evidence = IndexabilityEvidenceParser().parse_x_robots_tag(("none",))

    assert evidence.records[0].directives[0].known is True
    assert evidence.records[0].directives[0].name == "none"


def test_parameterized_directives_preserve_values() -> None:
    evidence = IndexabilityEvidenceParser().parse_x_robots_tag(
        ("max-snippet: 50, max-image-preview: large, unavailable_after: 25 Jun 2027",)
    )

    assert [(item.name, item.value) for item in evidence.records[0].directives] == [
        ("max-snippet", "50"),
        ("max-image-preview", "large"),
        ("unavailable_after", "25 Jun 2027"),
    ]


def test_unknown_directive_is_preserved_with_warning() -> None:
    evidence = IndexabilityEvidenceParser().parse_x_robots_tag(("future-directive",))

    assert evidence.records[0].directives[0].known is False
    assert IndexabilityWarningCode.UNKNOWN_X_ROBOTS_DIRECTIVE in {
        item.code for item in evidence.warnings
    }


def test_empty_header_is_preserved_with_warning() -> None:
    evidence = IndexabilityEvidenceParser().parse_x_robots_tag(("  ",))

    assert evidence.records[0].raw_value == "  "
    assert IndexabilityWarningCode.EMPTY_X_ROBOTS_TAG in {item.code for item in evidence.warnings}


def test_invalid_syntax_is_controlled_evidence() -> None:
    evidence = IndexabilityEvidenceParser().parse_x_robots_tag((": noindex",))

    assert evidence.records[0].directives == ()
    assert IndexabilityWarningCode.INVALID_X_ROBOTS_TAG in {item.code for item in evidence.warnings}


def test_crawler_specific_prefix_applies_to_all_header_directives() -> None:
    evidence = IndexabilityEvidenceParser().parse_x_robots_tag(("googlebot: noindex, nofollow",))

    assert evidence.records[0].agent_name == "googlebot"
    assert [item.name for item in evidence.records[0].directives] == ["noindex", "nofollow"]


def test_generic_and_crawler_specific_records_remain_separate() -> None:
    evidence = IndexabilityEvidenceParser().parse_x_robots_tag(
        ("index, follow", "googlebot: noindex, nofollow")
    )

    assert [item.agent_name for item in evidence.records] == [None, "googlebot"]


def test_conflicting_generic_header_directives_emit_warning() -> None:
    evidence = IndexabilityEvidenceParser().parse_x_robots_tag(("index, noindex",))

    assert IndexabilityWarningCode.CONFLICTING_X_ROBOTS_DIRECTIVES in {
        item.code for item in evidence.warnings
    }


def test_conflicting_directives_across_repeated_headers_emit_warning() -> None:
    evidence = IndexabilityEvidenceParser().parse_x_robots_tag(("index", "noindex"))

    assert IndexabilityWarningCode.CONFLICTING_X_ROBOTS_DIRECTIVES in {
        item.code for item in evidence.warnings
    }


def test_meta_header_index_conflict_retains_both_sources() -> None:
    parser = IndexabilityEvidenceParser()
    header = parser.parse_x_robots_tag(("noindex",))

    combined = parser.combine((_meta("index"),), header)

    assert combined.meta_robots[0].directives[0].name == "index"
    assert combined.x_robots_tag.records[0].directives[0].name == "noindex"
    assert combined.conflicts[0].kind is IndexabilityConflictKind.INDEX
    assert IndexabilityWarningCode.META_HEADER_INDEX_CONFLICT in {
        item.code for item in combined.warnings
    }


def test_meta_header_follow_conflict_is_detected() -> None:
    parser = IndexabilityEvidenceParser()
    combined = parser.combine(
        (_meta("follow"),),
        parser.parse_x_robots_tag(("nofollow",)),
    )

    assert combined.conflicts[0].kind is IndexabilityConflictKind.FOLLOW


def test_parameterized_conflict_preserves_every_value() -> None:
    parser = IndexabilityEvidenceParser()
    meta = MetaRobotsRecord(
        "robots",
        "max-snippet: 10",
        (
            RobotsDirective(
                name="max-snippet",
                value="10",
                raw_value="max-snippet: 10",
                known=True,
            ),
        ),
        0,
    )
    combined = parser.combine((meta,), parser.parse_x_robots_tag(("max-snippet: 20",)))

    assert combined.conflicts[0].kind is IndexabilityConflictKind.PARAMETER
    assert combined.conflicts[0].observed_values == ("10", "20")


def test_crawler_specific_difference_is_evidence_not_a_generic_verdict() -> None:
    parser = IndexabilityEvidenceParser()
    combined = parser.combine(
        (),
        parser.parse_x_robots_tag(("index", "googlebot: noindex")),
    )

    assert any(
        item.kind is IndexabilityConflictKind.CRAWLER_SPECIFIC for item in combined.conflicts
    )
    assert IndexabilityWarningCode.CRAWLER_SPECIFIC_DIRECTIVE_DIFFERENCE in {
        item.code for item in combined.warnings
    }
