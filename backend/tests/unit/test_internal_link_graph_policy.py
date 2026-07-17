"""Focused Phase 23 graph, metric, reachability, anchor, and opportunity policy tests."""

# ruff: noqa: ANN401, SLF001

from __future__ import annotations

from typing import Any

import pytest

from musimack_tools.domain.internal_link import (
    GENERIC_ANCHORS,
    InternalLinkConfiguration,
)
from musimack_tools.internal_link.service import InternalLinkAuditService


class RecordingRepository:
    def __init__(self) -> None:
        self.anchors: list[dict[str, Any]] = []
        self.opportunities: list[dict[str, Any]] = []
        self.findings: list[dict[str, Any]] = []

    def reconcile_interrupted(self) -> int:
        return 0

    def persist_anchor(self, _audit_id: str, values: dict[str, Any]) -> dict[str, Any]:
        self.anchors.append(values)
        return values

    def persist_opportunity(self, _audit_id: str, values: dict[str, Any]) -> dict[str, Any]:
        self.opportunities.append(values)
        return values

    def persist_finding(self, _audit_id: str, values: dict[str, Any]) -> dict[str, Any]:
        self.findings.append(values)
        return values


def _service(
    **configuration: Any,
) -> tuple[InternalLinkAuditService, RecordingRepository]:
    repository = RecordingRepository()
    defaults: dict[str, Any] = {
        "enabled": True,
        "minimum_hub_destinations": 2,
        "minimum_authority_referrers": 2,
        "minimum_sitewide_pages": 2,
        "low_inlink_threshold": 1,
    }
    defaults.update(configuration)
    return (
        InternalLinkAuditService(InternalLinkConfiguration(**defaults), repository),  # type: ignore[arg-type]
        repository,
    )


def _page(identity: str, **values: Any) -> dict[str, Any]:
    return {
        "evidence_id": f"e-{identity}",
        "requested_url": f"https://example.test/{identity}",
        "requested_url_identity": identity,
        "final_url": f"https://example.test/{identity}",
        "final_url_identity": identity,
        "canonical_url_identity": None,
        "canonical_conflicting": False,
        "redirect_count": 0,
        "fetch_failed": False,
        "http_status": 200,
        "content_type_category": "html",
        "parsed_as_html": True,
        "robots_allowed": True,
        "meta_robots_json": "[]",
        "x_robots_json": "[]",
        "crawl_depth": 1,
        "discovery_sequence": 1,
        **values,
    }


def _link(source: str, target: str | None, **values: Any) -> dict[str, Any]:
    return {
        "link_id": values.pop("link_id", f"{source}-{target}"),
        "source_url_identity": source,
        "source_requested_url": f"https://example.test/{source}",
        "target_url_identity": target,
        "raw_href": values.pop("raw_href", f"/{target or ''}"),
        "resolved_url": values.pop("resolved_url", f"https://example.test/{target or ''}"),
        "link_type": "http",
        "internal": True,
        "in_scope": True,
        "nofollow": False,
        "anchor_text": values.pop("anchor_text", target or ""),
        "fragment": values.pop("fragment", None),
        **values,
    }


def _edge(source: str, target: str, **values: Any) -> dict[str, Any]:
    return {
        "source_identity": source,
        "target_identity": target,
        "source_url": f"https://example.test/{source}",
        "target_url": f"https://example.test/{target}",
        "redirect_adjusted_identity": None,
        "canonical_adjusted_identity": None,
        "raw_occurrence_count": 1,
        "nofollow_occurrence_count": 0,
        "sitewide": False,
        "edge_state": "direct",
        **values,
    }


def test_node_eligibility_classifies_supported_excluded_and_ambiguous_pages() -> None:
    service, _ = _service()
    pages = (
        _page("eligible"),
        _page("noindex", meta_robots_json='["noindex"]'),
        _page("redirect", redirect_count=1, final_url_identity="eligible"),
        _page("canonical", canonical_url_identity="eligible"),
        _page("ambiguous", canonical_url_identity="eligible", canonical_conflicting=True),
        _page("non-html", content_type_category="image", parsed_as_html=False),
        _page("failed", fetch_failed=True, http_status=None),
    )

    nodes = service._nodes(pages)

    assert nodes["eligible"]["eligibility"] == "eligible"
    assert nodes["noindex"]["eligibility"] == "excluded_noindex"
    assert nodes["redirect"]["eligibility"] == "redirect_source"
    assert nodes["canonical"]["eligibility"] == "canonical_duplicate"
    assert nodes["ambiguous"]["eligibility"] == "eligible"
    assert nodes["non-html"]["eligibility"] == "excluded_non_html"
    assert nodes["failed"]["eligibility"] == "unverified"


def test_edge_construction_preserves_occurrences_scope_fragments_and_ordering() -> None:
    service, _ = _service(sitewide_source_ratio=0.3)
    nodes = service._nodes(
        (
            _page("a", discovery_sequence=0, crawl_depth=0),
            _page("b"),
            _page("redirect", redirect_count=1, final_url_identity="b"),
            _page("canonical", canonical_url_identity="b"),
            _page("ambiguous", canonical_url_identity="b", canonical_conflicting=True),
        )
    )
    links = (
        _link("a", "b", link_id="1", raw_href="/b#one", fragment="one"),
        _link("a", "b", link_id="2", raw_href="/b#two", fragment="two", nofollow=True),
        _link("a", "redirect", link_id="3"),
        _link("a", "canonical", link_id="4"),
        _link("a", "ambiguous", link_id="5"),
        _link("a", "external", link_id="6", internal=False),
        _link("a", "outside", link_id="7", in_scope=False),
        _link("a", None, link_id="8", link_type="mailto"),
        _link("a", "historical", link_id="9", in_scope=None),
    )

    edges, raw_by_target, outgoing = service._edges(nodes, links)

    assert [(row["source_identity"], row["target_identity"]) for row in edges] == sorted(
        (row["source_identity"], row["target_identity"]) for row in edges
    )
    direct = next(row for row in edges if row["target_identity"] == "b")
    assert direct["raw_occurrence_count"] == 2
    assert direct["nofollow_occurrence_count"] == 1
    assert {row["fragment"] for row in raw_by_target["b"]} == {"one", "two"}
    assert {row["raw_href"] for row in raw_by_target["b"]} == {"/b#one", "/b#two"}
    assert direct["sitewide"]
    assert (
        next(row for row in edges if row["target_identity"] == "redirect")[
            "redirect_adjusted_identity"
        ]
        == "b"
    )
    assert (
        next(row for row in edges if row["target_identity"] == "canonical")[
            "canonical_adjusted_identity"
        ]
        == "b"
    )
    assert (
        next(row for row in edges if row["target_identity"] == "ambiguous")[
            "canonical_adjusted_identity"
        ]
        is None
    )
    assert {"external", "outside"}.isdisjoint(raw_by_target)
    assert "historical" in raw_by_target
    assert len(outgoing["a"]) == len(links)


def test_reachability_supports_multiple_seeds_shortest_paths_redirects_and_nofollow() -> None:
    service, _ = _service()
    nodes = service._nodes(
        tuple(
            _page(name, discovery_sequence=index, crawl_depth=0 if index == 0 else index)
            for index, name in enumerate(
                ("seed", "a", "b", "deep", "redirected", "nofollow", "orphan")
            )
        )
    )
    edges = [
        _edge("seed", "a"),
        _edge("seed", "b"),
        _edge("a", "deep"),
        _edge("b", "deep"),
        _edge(
            "deep",
            "old",
            redirect_adjusted_identity="redirected",
            edge_state="redirect_adjusted",
        ),
        _edge("seed", "nofollow", nofollow_occurrence_count=1),
    ]

    result = service._reachability(nodes, edges, "seed")

    assert result["seed"]["distance"] == 0
    assert result["a"]["distance"] == 1
    assert result["deep"]["distance"] == 2
    assert result["deep"]["predecessor"] == "a"
    assert result["redirected"]["redirect_dependent"]
    assert result["nofollow"]["nofollow_only"]
    assert not result["orphan"]["reachable"]
    multiple = service._reachability(nodes, edges, ("seed", "b"))
    assert multiple["seed"]["distance"] == 0
    assert multiple["b"]["distance"] == 0
    with pytest.raises(ValueError, match="seed_unavailable"):
        service._reachability(nodes, edges, ())


def test_metrics_assert_every_required_count_state_and_ordering() -> None:
    service, _ = _service(maximum_graph_depth=1)
    raw_pages = (
        _page("seed", discovery_sequence=0, crawl_depth=0),
        _page("a", discovery_sequence=1, crawl_depth=4),
        _page("b", discovery_sequence=2),
        _page("redirect", discovery_sequence=3, redirect_count=1, final_url_identity="a"),
        _page("broken", discovery_sequence=4, http_status=404),
        _page("orphan", discovery_sequence=5),
        _page("sitemap", discovery_sequence=6, in_sitemap=True),
        _page("unverified", discovery_sequence=7, fetch_failed=True, http_status=None),
    )
    nodes = service._nodes(raw_pages)
    links = (
        _link("seed", "a", link_id="1", anchor_text="Guide"),
        _link("seed", "a", link_id="2", anchor_text="guide"),
        _link("b", "a", link_id="3", nofollow=True, anchor_text="https://example.test/a"),
        _link("seed", "redirect", link_id="4"),
        _link("a", "broken", link_id="5"),
        _link("seed", "external", link_id="6", internal=False),
    )
    edges, raw_by_target, outgoing = service._edges(nodes, links)
    for edge in edges:
        if edge["source_identity"] == "seed" and edge["target_identity"] == "a":
            edge["sitewide"] = True
    reachability = service._reachability(nodes, edges, "seed")
    anchors = {
        "a": {
            "unique": 2,
            "dominant": "guide",
            "share": 0.75,
            "url_count": 1,
        }
    }

    metrics = service._metrics(nodes, edges, links, raw_by_target, outgoing, reachability, anchors)
    by_id = {row["page_identity"]: row for row in metrics}
    a = by_id["a"]

    assert [row["discovery_sequence"] for row in metrics] == sorted(
        row["discovery_sequence"] for row in metrics
    )
    assert a["inbound_occurrences"] == 4
    assert a["unique_referring_pages"] == 2
    assert a["direct_inlinks"] == 3
    assert a["redirect_adjusted_inlinks"] == 1
    assert a["nofollow_inlinks"] == 1
    assert a["sitewide_inlinks"] == 2
    assert a["non_sitewide_inlinks"] == 2
    assert a["unique_anchor_count"] == 2
    assert a["dominant_anchor_share"] == 0.75
    assert a["url_anchor_count"] == 1
    assert a["crawl_depth"] == 4
    assert a["graph_depth"] == 1
    assert a["reachable"]
    assert a["discovery_sequence"] == 1
    assert by_id["seed"]["outbound_occurrences"] == 4
    assert by_id["seed"]["unique_destination_pages"] == 3
    assert by_id["seed"]["nofollow_outlinks"] == 0
    assert by_id["seed"]["redirecting_outlinks"] == 1
    assert by_id["seed"]["external_outlinks"] == 1
    assert by_id["a"]["broken_outlinks"] == 1
    assert by_id["seed"]["orphan_state"] == "seed_page"
    assert by_id["orphan"]["orphan_state"] == "true_orphan_candidate"
    assert by_id["sitemap"]["orphan_state"] == "sitemap_discovered_without_inlinks"
    assert by_id["unverified"]["orphan_state"] == "unverified_orphan_state"
    assert by_id["broken"]["orphan_state"] == "excluded_not_orphan"


def test_hub_authority_thresholds_burdens_sitewide_nofollow_and_small_crawls() -> None:
    service, _ = _service(maximum_outlinks=3)
    nodes = service._nodes(
        tuple(
            _page(name, discovery_sequence=index)
            for index, name in enumerate(("hub", "a", "b", "authority", "broken"))
        )
    )
    nodes["broken"]["http_status"] = 404
    reach = {
        name: {
            "reachable": True,
            "distance": index,
            "predecessor": None,
            "redirect_dependent": False,
            "nofollow_only": False,
            "path": (),
        }
        for index, name in enumerate(nodes)
    }
    links = (
        _link("hub", "a", link_id="1"),
        _link("hub", "b", link_id="2"),
        _link("a", "authority", link_id="3"),
        _link("b", "authority", link_id="4"),
    )
    edges, raw, outgoing = service._edges(nodes, links)
    metrics = service._metrics(nodes, edges, links, raw, outgoing, reach, {})
    by_id = {row["page_identity"]: row for row in metrics}
    assert by_id["hub"]["hub_state"] == "candidate"
    assert by_id["authority"]["authority_state"] == "candidate"

    below_edges = [_edge("hub", "a")]
    below = service._metrics(
        nodes,
        below_edges,
        tuple(links[:1]),
        {"a": [links[0]]},
        {"hub": [links[0]]},
        reach,
        {},
    )
    assert (
        next(row for row in below if row["page_identity"] == "hub")["hub_state"] == "not_candidate"
    )

    burden_links = (*links, _link("hub", "broken", link_id="5"))
    burden_edges, burden_raw, burden_out = service._edges(nodes, burden_links)
    burden = service._metrics(nodes, burden_edges, burden_links, burden_raw, burden_out, reach, {})
    assert (
        next(row for row in burden if row["page_identity"] == "hub")["hub_state"] == "not_candidate"
    )

    nofollow_edges = [
        _edge("a", "authority", nofollow_occurrence_count=1),
        _edge("b", "authority", nofollow_occurrence_count=1),
    ]
    nofollow_metrics = service._metrics(
        nodes,
        nofollow_edges,
        tuple(links[2:]),
        {"authority": list(links[2:])},
        {"a": [links[2]], "b": [links[3]]},
        reach,
        {},
    )
    assert (
        next(row for row in nofollow_metrics if row["page_identity"] == "authority")[
            "authority_state"
        ]
        == "not_candidate"
    )

    tiny, _ = _service(minimum_sitewide_pages=10)
    tiny_metrics = tiny._metrics(nodes, edges, links, raw, outgoing, reach, {})
    assert {row["hub_state"] for row in tiny_metrics} == {"insufficient_sample"}
    assert {row["authority_state"] for row in tiny_metrics} == {"insufficient_sample"}


def test_anchor_analysis_covers_normalization_vocabulary_thresholds_and_targets() -> None:
    service, repository = _service(dominant_anchor_share=0.8)
    nodes = service._nodes(
        (
            _page("target"),
            _page("redirect", redirect_count=1, final_url_identity="target"),
            _page("broken", http_status=404),
            _page("other"),
        )
    )
    occurrences = [
        _link("a", "target", link_id="1", anchor_text="  Useful\n Guide  "),
        _link("b", "target", link_id="2", anchor_text="USEFUL GUIDE"),
        _link("c", "target", link_id="3", anchor_text="click here"),
        _link("d", "target", link_id="4", anchor_text=""),
        _link("e", "target", link_id="5", anchor_text="https://example.test/target"),
        _link("a", "redirect", link_id="6", anchor_text="old"),
        _link("a", "broken", link_id="7", anchor_text="broken"),
        _link("a", "other", link_id="8", anchor_text="click here"),
    ]
    raw = {
        target: [row for row in occurrences if row["target_url_identity"] == target]
        for target in ("target", "redirect", "broken", "other")
    }

    aggregate = service._anchors("audit", nodes, tuple(occurrences), raw)

    states = {row["anchor_state"] for row in repository.anchors}
    assert {"empty_anchor", "generic_anchor", "url_as_anchor"} <= states
    assert "redirecting_anchor_target" in states
    assert "broken_anchor_target" in states
    assert aggregate["target"]["unique"] == 4
    assert aggregate["target"]["url_count"] == 1
    useful = next(row for row in repository.anchors if row["normalized_anchor"] == "useful guide")
    assert useful["occurrence_count"] == 2
    assert useful["representative_anchor"] == "  Useful\n Guide  "
    assert tuple(row["anchor_sequence"] for row in repository.anchors) == tuple(
        range(len(repository.anchors))
    )
    assert {"click here", "read more", "learn more", "more", "here", "this page"} <= GENERIC_ANCHORS

    threshold_service, threshold_repo = _service(dominant_anchor_share=0.8)
    at_threshold = [
        _link(
            str(index), "target", link_id=str(index), anchor_text="same" if index < 4 else "other"
        )
        for index in range(5)
    ]
    threshold_service._anchors("at", nodes, tuple(at_threshold), {"target": at_threshold})
    assert all(row["anchor_state"] != "over_concentrated_anchor" for row in threshold_repo.anchors)
    above = [
        _link(
            str(index), "target", link_id=f"x{index}", anchor_text="same" if index < 5 else "other"
        )
        for index in range(6)
    ]
    threshold_service._anchors("above", nodes, tuple(above), {"target": above})
    assert any(row["anchor_state"] == "over_concentrated_anchor" for row in threshold_repo.anchors)


def test_opportunities_are_evidence_bound_conservative_and_deterministic() -> None:
    service, repository = _service()
    metrics = [
        {
            "page_identity": "hub",
            "requested_url": "https://example.test/hub",
            "hub_state": "candidate",
            "orphan_state": "not_orphan",
            "primary_state": "hub_candidate",
            "inbound_occurrences": 2,
            "outbound_occurrences": 2,
            "graph_depth": 1,
            "dominant_anchor": "useful",
            "dominant_anchor_share": 1.0,
        },
        {
            "page_identity": "orphan",
            "requested_url": "https://example.test/orphan",
            "hub_state": "not_candidate",
            "orphan_state": "true_orphan_candidate",
            "primary_state": "orphan_candidate",
            "inbound_occurrences": 0,
            "outbound_occurrences": 0,
            "graph_depth": None,
            "dominant_anchor": None,
            "dominant_anchor_share": 0.0,
        },
        {
            "page_identity": "weak",
            "requested_url": "https://example.test/weak",
            "hub_state": "not_candidate",
            "orphan_state": "not_orphan",
            "primary_state": "low_inlink_count",
            "inbound_occurrences": 1,
            "outbound_occurrences": 0,
            "graph_depth": 2,
            "dominant_anchor": "click here",
            "dominant_anchor_share": 1.0,
        },
        {
            "page_identity": "utility",
            "requested_url": "https://example.test/utility",
            "hub_state": "not_candidate",
            "orphan_state": "not_orphan",
            "primary_state": "high_outlink_count",
            "inbound_occurrences": 1,
            "outbound_occurrences": 101,
            "graph_depth": 1,
            "dominant_anchor": "https://example.test/utility",
            "dominant_anchor_share": 1.0,
        },
    ]
    nodes = {
        "old": _page("old", redirect_count=1, final_url_identity="weak"),
        "weak": {**_page("weak"), "eligibility": "eligible"},
        "broken": {
            **_page("broken", http_status=404, canonical_url_identity="weak"),
            "canonical_identity": "weak",
            "eligibility": "excluded_broken",
        },
        "unknown": {
            **_page("unknown", http_status=404),
            "canonical_identity": None,
            "eligibility": "excluded_broken",
        },
    }
    edges = [
        _edge(
            "hub",
            "old",
            redirect_adjusted_identity="weak",
            edge_state="redirect_adjusted",
        ),
        _edge("hub", "broken"),
        _edge("hub", "unknown"),
    ]

    service._persist_opportunities("audit", metrics, edges, nodes)

    by_type = {row["opportunity_type"]: row for row in repository.opportunities}
    assert by_type["link_orphan_from_hub"]["source_identity"] == "hub"
    assert by_type["link_orphan_from_hub"]["confidence"] == "medium"
    assert by_type["strengthen_low_inlink_page"]["action"] == "strengthen_existing_link"
    assert by_type["reduce_excessive_outlinks"]["confidence"] == "low"
    assert by_type["promote_hub_page"]["action"] == "promote_as_hub"
    assert by_type["replace_redirecting_link"]["confidence"] == "high"
    broken = [
        row for row in repository.opportunities if row["opportunity_type"] == "replace_broken_link"
    ]
    assert {row["confidence"] for row in broken} == {"high", "low"}
    assert all(row["human_review_required"] for row in repository.opportunities)
    assert all(
        row["source_identity"] is None or row["source_identity"] in {"hub", "weak", "utility"}
        for row in repository.opportunities
    )
    serialized = str(repository.opportunities).casefold()
    assert all(term not in serialized for term in ("embedding", "semantic", "topic", "pagerank"))
    assert tuple(row["opportunity_sequence"] for row in repository.opportunities) == tuple(
        range(len(repository.opportunities))
    )
