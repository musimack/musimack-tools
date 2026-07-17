"""Durable, network-free internal-link graph analysis."""

# ruff: noqa: ANN401, ARG002, C901, E501, FBT001, PLR0911, PLR0912, PLR0913, PLR0915, PLR2004

from __future__ import annotations

import asyncio
import csv
import io
import json
from collections import Counter, defaultdict, deque
from typing import TYPE_CHECKING, Any

from musimack_tools.domain.artifacts import ArtifactType
from musimack_tools.domain.internal_link import (
    ANCHOR_ORDERING,
    AUDIT_ORDERING,
    EDGE_ORDERING,
    FINDING_ORDERING,
    GENERIC_ANCHORS,
    INTERNAL_LINK_EXPORT_VERSION,
    INTERNAL_LINK_GRAPH_VERSION,
    INTERNAL_LINK_POLICY_VERSION,
    OPPORTUNITY_ORDERING,
    PAGE_ORDERING,
    AnchorState,
    CandidateState,
    Confidence,
    EligibilityState,
    InternalLinkConfiguration,
    InternalLinkExportFormat,
    InternalLinkLifecycle,
    OpportunityAction,
    OpportunityType,
    OrphanState,
    PageAnalysisState,
    Severity,
    audit_identity,
    decode_cursor,
    encode_cursor,
    filter_fingerprint,
    is_url_anchor,
    normalize_anchor,
    stable_identity,
    stable_json,
)

if TYPE_CHECKING:
    from musimack_tools.artifacts.service import ArtifactService
    from musimack_tools.persistence.internal_link_repository import SQLAlchemyInternalLinkRepository


class InternalLinkAuditService:
    def __init__(
        self,
        configuration: InternalLinkConfiguration,
        repository: SQLAlchemyInternalLinkRepository,
        artifacts: ArtifactService | None = None,
    ) -> None:
        self.configuration = configuration
        self._repository = repository
        self._artifacts = artifacts
        self._repository.reconcile_interrupted()

    def evidence_status(self, run_id: str) -> dict[str, Any]:
        context = self._repository.run_context(run_id)
        scope = self._repository.run_scope_snapshot(run_id)
        if context is None:
            raise ValueError("internal_link_run_not_found")
        return {
            "run_id": run_id,
            "terminal": context[2],
            "page_evidence_count": context[3],
            "link_evidence_count": context[4],
            "scope_available": scope is not None,
            "seed_available": bool(context[1]),
            "compatible": context[2] and context[3] > 0 and context[4] > 0 and scope is not None,
        }

    def create_audit(self, run_id: str) -> dict[str, Any]:
        if not self.configuration.enabled:
            raise ValueError("internal_link_audit_disabled")
        job_id, seed, _terminal, _pages, _links = self._context(run_id)
        scope = self._repository.run_scope_snapshot(run_id)
        if scope is None:
            raise ValueError("internal_link_scope_unavailable")
        identifier = audit_identity(run_id, self.configuration)
        return self._repository.create(
            identifier,
            job_id,
            run_id,
            seed,
            {"mode": scope[0].value, "approved_hosts": scope[1]},
            self.configuration,
        )

    async def execute_audit(self, audit_id: str) -> dict[str, Any]:
        audit = self.get(audit_id)
        if audit["state"] in _TERMINAL:
            raise ValueError("internal_link_audit_already_terminal")
        if not self._repository.claim_execution(audit_id):
            raise ValueError("internal_link_audit_already_executing")
        try:
            return self._execute_claimed(audit_id, audit)
        except asyncio.CancelledError:
            self._repository.transition(
                audit_id, InternalLinkLifecycle.CANCELLED, "internal_link_audit_cancelled"
            )
            raise
        except Exception:
            self._repository.fail_if_running(audit_id, "internal_link_audit_execution_failed")
            raise

    def _execute_claimed(self, audit_id: str, audit: dict[str, Any]) -> dict[str, Any]:
        run_id = str(audit["run_id"])
        pages = self._repository.pages(run_id)
        links = self._repository.source_links(run_id)
        if not pages:
            raise ValueError("internal_link_page_evidence_unavailable")
        if not links:
            raise ValueError("internal_link_link_evidence_unavailable")
        self._repository.transition(audit_id, InternalLinkLifecycle.BUILDING_GRAPH)
        nodes = self._nodes(pages)
        edges, raw_by_target, outgoing_raw = self._edges(nodes, links)
        for sequence, edge in enumerate(edges):
            self._repository.persist_edge(
                audit_id,
                {
                    **edge,
                    "edge_id": stable_identity(
                        audit_id, edge["source_identity"], edge["target_identity"]
                    ),
                    "edge_sequence": sequence,
                },
            )
        self._repository.transition(audit_id, InternalLinkLifecycle.COMPUTING_METRICS)
        seed_identity = self._seed_identity(nodes, str(audit["seed_url"]))
        self._repository.transition(audit_id, InternalLinkLifecycle.ANALYZING_REACHABILITY)
        reachability = self._reachability(nodes, edges, seed_identity)
        self._repository.transition(audit_id, InternalLinkLifecycle.ANALYZING_ANCHORS)
        anchor_data = self._anchors(audit_id, nodes, links, raw_by_target)
        metrics = self._metrics(
            nodes, edges, links, raw_by_target, outgoing_raw, reachability, anchor_data
        )
        for sequence, metric in enumerate(metrics):
            self._repository.persist_page(
                audit_id,
                {
                    **metric,
                    "metric_id": stable_identity(audit_id, metric["page_identity"]),
                    "page_sequence": sequence,
                },
            )
            reach = reachability[metric["page_identity"]]
            self._repository.persist_reachability(
                audit_id,
                {
                    "reachability_id": stable_identity(
                        audit_id, "reachability", metric["page_identity"]
                    ),
                    "page_identity": metric["page_identity"],
                    "seed_identity": seed_identity if reach["reachable"] else None,
                    "predecessor_identity": reach["predecessor"],
                    "distance": reach["distance"],
                    "reachable": reach["reachable"],
                    "redirect_dependent": reach["redirect_dependent"],
                    "nofollow_only": reach["nofollow_only"],
                    "path_json": stable_json(reach["path"]),
                    "sequence": sequence,
                },
            )
        self._persist_findings(audit_id, metrics, edges, anchor_data)
        self._repository.transition(audit_id, InternalLinkLifecycle.BUILDING_OPPORTUNITIES)
        self._persist_opportunities(audit_id, metrics, edges, nodes)
        return self._repository.finalize(audit_id)

    def _nodes(self, pages: tuple[dict[str, Any], ...]) -> dict[str, dict[str, Any]]:
        identities = {str(page["requested_url_identity"]) for page in pages}
        nodes: dict[str, dict[str, Any]] = {}
        for page in pages:
            identity = str(page["requested_url_identity"])
            canonical = str(page.get("canonical_url_identity") or "") or None
            eligibility = EligibilityState.ELIGIBLE
            reason: str | None = None
            if page.get("redirect_count") or page.get("final_url_identity") not in {None, identity}:
                eligibility, reason = EligibilityState.REDIRECT_SOURCE, "redirect_source"
            elif (
                canonical
                and canonical != identity
                and canonical in identities
                and not page.get("canonical_conflicting")
            ):
                eligibility, reason = EligibilityState.CANONICAL_DUPLICATE, "canonical_duplicate"
            elif page.get("fetch_failed") or page.get("http_status") is None:
                eligibility, reason = EligibilityState.UNVERIFIED, "fetch_unavailable"
            elif not 200 <= int(page["http_status"]) < 300:
                eligibility, reason = EligibilityState.EXCLUDED_BROKEN, "non_success_status"
            elif page.get("content_type_category") != "html" or not page.get("parsed_as_html"):
                eligibility, reason = EligibilityState.EXCLUDED_NON_HTML, "non_html"
            elif (
                page.get("robots_allowed") is False
                or "noindex" in str(page.get("meta_robots_json", "")).casefold()
                or "noindex" in str(page.get("x_robots_json", "")).casefold()
            ):
                eligibility, reason = EligibilityState.EXCLUDED_NOINDEX, "noindex"
            nodes[identity] = {
                **page,
                "page_identity": identity,
                "canonical_identity": canonical,
                "eligibility": eligibility.value,
                "exclusion_reason": reason,
            }
        return nodes

    def _edges(
        self,
        nodes: dict[str, dict[str, Any]],
        links: tuple[dict[str, Any], ...],
    ) -> tuple[
        list[dict[str, Any]], dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]
    ]:
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        raw_by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
        outgoing_raw: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for link in links:
            source = str(link["source_url_identity"])
            target = str(link.get("target_url_identity") or "")
            outgoing_raw[source].append(link)
            if (
                link.get("link_type") != "http"
                or link.get("internal") is not True
                # Historical accepted evidence can predate a populated in_scope
                # projection. The parser-owned internal flag is authoritative for
                # same-host HTTP links; an explicit out-of-scope decision still wins.
                or link.get("in_scope") is False
                or not target
            ):
                continue
            raw_by_target[target].append(link)
            grouped[(source, target)].append(link)
        eligible_count = sum(node["eligibility"] == "eligible" for node in nodes.values())
        target_sources: dict[str, set[str]] = defaultdict(set)
        for source, target in grouped:
            target_sources[target].add(source)
        result: list[dict[str, Any]] = []
        for (source, target), occurrences in sorted(grouped.items()):
            target_page = nodes.get(target)
            adjusted = None
            canonical = None
            state = "direct"
            if target_page and target_page.get("redirect_count"):
                adjusted = target_page.get("final_url_identity")
                state = "redirect_adjusted"
            if target_page and target_page.get("eligibility") == "canonical_duplicate":
                canonical = target_page.get("canonical_identity")
                state = "canonical_adjusted"
            anchors = sorted({normalize_anchor(item.get("anchor_text")) for item in occurrences})
            sitewide = (
                eligible_count >= self.configuration.minimum_sitewide_pages
                and len(target_sources[target]) / max(eligible_count, 1)
                >= self.configuration.sitewide_source_ratio
            )
            result.append(
                {
                    "source_identity": source,
                    "target_identity": target,
                    "source_url": str(occurrences[0]["source_requested_url"])[:4096],
                    "target_url": str(
                        occurrences[0].get("resolved_url") or occurrences[0].get("raw_href") or ""
                    )[:4096],
                    "redirect_adjusted_identity": adjusted,
                    "canonical_adjusted_identity": canonical,
                    "raw_occurrence_count": len(occurrences),
                    "nofollow_occurrence_count": sum(
                        bool(item.get("nofollow")) for item in occurrences
                    ),
                    "sitewide": sitewide,
                    "edge_state": state,
                    "anchor_summary_json": stable_json(anchors[:50]),
                }
            )
        return result, raw_by_target, outgoing_raw

    def _seed_identity(self, nodes: dict[str, dict[str, Any]], seed_url: str) -> str:
        for identity, page in nodes.items():
            if page["requested_url"] == seed_url or page.get("final_url") == seed_url:
                return identity
        raise ValueError("internal_link_seed_unavailable")

    def _reachability(
        self,
        nodes: dict[str, dict[str, Any]],
        edges: list[dict[str, Any]],
        seed: str | tuple[str, ...],
    ) -> dict[str, dict[str, Any]]:
        adjacency: dict[str, list[tuple[str, bool]]] = defaultdict(list)
        all_adjacency: dict[str, list[tuple[str, bool]]] = defaultdict(list)
        for edge in edges:
            target = str(
                edge.get("redirect_adjusted_identity")
                or edge.get("canonical_adjusted_identity")
                or edge["target_identity"]
            )
            pair = (target, edge["edge_state"] != "direct")
            all_adjacency[str(edge["source_identity"])].append(pair)
            if edge["nofollow_occurrence_count"] < edge["raw_occurrence_count"]:
                adjacency[str(edge["source_identity"])].append(pair)
        for values in (adjacency, all_adjacency):
            for key in values:
                values[key].sort()
        seeds = (seed,) if isinstance(seed, str) else tuple(sorted(set(seed)))
        if not seeds:
            raise ValueError("internal_link_seed_unavailable")
        distance = dict.fromkeys(seeds, 0)
        predecessor: dict[str, str | None] = dict.fromkeys(seeds)
        redirect_dependent = dict.fromkeys(seeds, False)
        queue = deque(seeds)
        while queue:
            source = queue.popleft()
            if distance[source] >= self.configuration.maximum_path_depth:
                continue
            for target, redirected in adjacency.get(source, ()):
                if (
                    target not in nodes
                    or nodes[target]["eligibility"] != "eligible"
                    or target in distance
                ):
                    continue
                distance[target] = distance[source] + 1
                predecessor[target] = source
                redirect_dependent[target] = redirect_dependent[source] or redirected
                queue.append(target)
        all_reachable = set(seeds)
        queue = deque(seeds)
        while queue:
            source = queue.popleft()
            for target, _redirected in all_adjacency.get(source, ()):
                if target in nodes and target not in all_reachable:
                    all_reachable.add(target)
                    queue.append(target)
        result: dict[str, dict[str, Any]] = {}
        for identity in sorted(nodes):
            path: list[str] = []
            cursor: str | None = identity if identity in distance else None
            while cursor is not None and len(path) <= self.configuration.maximum_path_depth:
                path.append(cursor)
                cursor = predecessor.get(cursor)
            result[identity] = {
                "reachable": identity in distance,
                "distance": distance.get(identity),
                "predecessor": predecessor.get(identity),
                "redirect_dependent": redirect_dependent.get(identity, False),
                "nofollow_only": identity in all_reachable and identity not in distance,
                "path": tuple(reversed(path)),
            }
        return result

    def _anchors(
        self,
        audit_id: str,
        nodes: dict[str, dict[str, Any]],
        links: tuple[dict[str, Any], ...],
        raw_by_target: dict[str, list[dict[str, Any]]],
    ) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        sequence = 0
        anchor_targets: dict[str, set[str]] = defaultdict(set)
        for target, occurrences in raw_by_target.items():
            for item in occurrences:
                anchor_targets[normalize_anchor(item.get("anchor_text"))].add(target)
        for target in sorted(raw_by_target):
            occurrences = raw_by_target[target]
            grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for item in occurrences:
                grouped[normalize_anchor(item.get("anchor_text"))].append(item)
            counts = Counter({anchor: len(items) for anchor, items in grouped.items()})
            dominant, dominant_count = counts.most_common(1)[0]
            result[target] = {
                "unique": len(grouped),
                "dominant": dominant or None,
                "share": dominant_count / len(occurrences),
                "url_count": sum(
                    is_url_anchor(anchor) for anchor in counts for _ in range(counts[anchor])
                ),
            }
            for anchor in sorted(grouped):
                items = grouped[anchor]
                share = len(items) / len(occurrences)
                state = AnchorState.HEALTHY
                severity = Severity.INFO
                if not anchor:
                    state, severity = AnchorState.EMPTY, Severity.MEDIUM
                elif anchor in GENERIC_ANCHORS:
                    state, severity = AnchorState.GENERIC, Severity.LOW
                elif is_url_anchor(anchor):
                    state, severity = AnchorState.URL, Severity.LOW
                elif share > self.configuration.dominant_anchor_share and len(occurrences) >= 3:
                    state, severity = AnchorState.CONCENTRATED, Severity.MEDIUM
                elif len(grouped) > 1:
                    state, severity = AnchorState.MULTIPLE_TO_TARGET, Severity.LOW
                elif len(anchor_targets[anchor]) > 1 and anchor:
                    state, severity = AnchorState.DUPLICATE_TO_TARGETS, Severity.LOW
                target_page = nodes.get(target)
                if target_page and target_page.get("redirect_count"):
                    state, severity = AnchorState.REDIRECTING_TARGET, Severity.MEDIUM
                elif (
                    target_page
                    and target_page.get("http_status")
                    and int(target_page["http_status"]) >= 400
                ):
                    state, severity = AnchorState.BROKEN_TARGET, Severity.HIGH
                self._repository.persist_anchor(
                    audit_id,
                    {
                        "anchor_id": stable_identity(audit_id, target, anchor),
                        "target_identity": target,
                        "target_url": str(
                            items[0].get("resolved_url") or items[0].get("raw_href") or ""
                        )[:4096],
                        "normalized_anchor": anchor,
                        "representative_anchor": str(items[0].get("anchor_text") or "")[:512]
                        or None,
                        "occurrence_count": len(items),
                        "source_page_count": len(
                            {str(item["source_url_identity"]) for item in items}
                        ),
                        "share": share,
                        "anchor_state": state.value,
                        "severity": severity.value,
                        "sample_sources_json": stable_json(
                            sorted({str(item["source_requested_url"]) for item in items})[:10]
                        ),
                        "anchor_sequence": sequence,
                    },
                )
                sequence += 1
        return result

    def _metrics(
        self,
        nodes: dict[str, dict[str, Any]],
        edges: list[dict[str, Any]],
        links: tuple[dict[str, Any], ...],
        raw_by_target: dict[str, list[dict[str, Any]]],
        outgoing_raw: dict[str, list[dict[str, Any]]],
        reachability: dict[str, dict[str, Any]],
        anchors: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        incoming_edges: dict[str, list[dict[str, Any]]] = defaultdict(list)
        outgoing_edges: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for edge in edges:
            analyzed_target = str(
                edge.get("redirect_adjusted_identity")
                or edge.get("canonical_adjusted_identity")
                or edge["target_identity"]
            )
            incoming_edges[analyzed_target].append(edge)
            outgoing_edges[str(edge["source_identity"])].append(edge)
        eligible_count = sum(node["eligibility"] == "eligible" for node in nodes.values())
        result: list[dict[str, Any]] = []
        for identity in sorted(nodes, key=lambda key: (int(nodes[key]["discovery_sequence"]), key)):
            page = nodes[identity]
            outgoing = outgoing_raw.get(identity, [])
            valid_inbound = incoming_edges.get(identity, [])
            valid_outbound = outgoing_edges.get(identity, [])
            inbound_occurrences = sum(int(edge["raw_occurrence_count"]) for edge in valid_inbound)
            reachable = reachability[identity]
            eligibility = str(page["eligibility"])
            redirect_in = sum(
                edge["raw_occurrence_count"]
                for edge in valid_inbound
                if edge["edge_state"] == "redirect_adjusted"
            )
            direct_in = sum(
                edge["raw_occurrence_count"]
                for edge in valid_inbound
                if edge["edge_state"] == "direct"
            )
            nofollow_in = sum(edge["nofollow_occurrence_count"] for edge in valid_inbound)
            sitewide_in = sum(
                edge["raw_occurrence_count"] for edge in valid_inbound if edge["sitewide"]
            )
            orphan = OrphanState.NOT_ORPHAN
            if eligibility != "eligible":
                orphan = (
                    OrphanState.EXCLUDED if eligibility != "unverified" else OrphanState.UNVERIFIED
                )
            elif reachable["distance"] == 0:
                orphan = OrphanState.SEED_PAGE
            elif not valid_inbound:
                orphan = (
                    OrphanState.SITEMAP_ONLY
                    if page.get("in_sitemap") is True
                    else OrphanState.TRUE_ORPHAN
                )
            elif direct_in == 0 and redirect_in > 0:
                orphan = OrphanState.REDIRECT_ONLY
            elif nofollow_in == sum(edge["raw_occurrence_count"] for edge in valid_inbound):
                orphan = OrphanState.NOFOLLOW_ONLY
            hub = CandidateState.INSUFFICIENT_SAMPLE
            authority = CandidateState.INSUFFICIENT_SAMPLE
            if eligible_count >= self.configuration.minimum_sitewide_pages:
                broken_outgoing = sum(
                    1
                    for item in outgoing
                    if (candidate := nodes.get(str(item.get("target_url_identity") or "")))
                    and candidate.get("http_status")
                    and int(candidate["http_status"]) >= 400
                )
                hub = (
                    CandidateState.CANDIDATE
                    if len({edge["target_identity"] for edge in valid_outbound})
                    >= self.configuration.minimum_hub_destinations
                    and len(outgoing) <= self.configuration.maximum_outlinks
                    and broken_outgoing == 0
                    and sum(
                        edge["raw_occurrence_count"]
                        for edge in valid_outbound
                        if edge["edge_state"] != "direct"
                    )
                    == 0
                    else CandidateState.NOT_CANDIDATE
                )
                non_sitewide_sources = {
                    edge["source_identity"]
                    for edge in valid_inbound
                    if not edge["sitewide"]
                    and edge["nofollow_occurrence_count"] < edge["raw_occurrence_count"]
                }
                authority = (
                    CandidateState.CANDIDATE
                    if len(non_sitewide_sources) >= self.configuration.minimum_authority_referrers
                    else CandidateState.NOT_CANDIDATE
                )
            state = PageAnalysisState.REACHABLE
            severity = Severity.INFO
            if eligibility == "redirect_source":
                state, severity = PageAnalysisState.REDIRECT_SOURCE, Severity.MEDIUM
            elif eligibility == "canonical_duplicate":
                state, severity = PageAnalysisState.CANONICAL_DUPLICATE, Severity.LOW
            elif eligibility == "unverified":
                state, severity = PageAnalysisState.UNVERIFIED_PAGE, Severity.MEDIUM
            elif eligibility != "eligible":
                state = PageAnalysisState.EXCLUDED_PAGE
            elif orphan in {OrphanState.TRUE_ORPHAN, OrphanState.SITEMAP_ONLY}:
                state, severity = PageAnalysisState.ORPHAN_CANDIDATE, Severity.HIGH
            elif (
                reachable["distance"] is not None
                and reachable["distance"] > self.configuration.maximum_graph_depth
            ):
                state, severity = PageAnalysisState.DEEP_PAGE, Severity.MEDIUM
            elif (
                len({edge["source_identity"] for edge in valid_inbound})
                < self.configuration.low_inlink_threshold
            ):
                state, severity = PageAnalysisState.LOW_INLINK_COUNT, Severity.MEDIUM
            elif len(outgoing) > self.configuration.maximum_outlinks:
                state, severity = PageAnalysisState.HIGH_OUTLINK_COUNT, Severity.MEDIUM
            elif hub is CandidateState.CANDIDATE:
                state = PageAnalysisState.HUB_CANDIDATE
            elif authority is CandidateState.CANDIDATE:
                state = PageAnalysisState.AUTHORITY_CANDIDATE
            anchor = anchors.get(
                identity, {"unique": 0, "dominant": None, "share": 0.0, "url_count": 0}
            )
            result.append(
                {
                    "page_evidence_id": page.get("evidence_id"),
                    "requested_url": str(page["requested_url"])[:4096],
                    "final_url": page.get("final_url"),
                    "page_identity": identity,
                    "canonical_identity": page.get("canonical_identity"),
                    "eligibility": eligibility,
                    "exclusion_reason": page.get("exclusion_reason"),
                    "primary_state": state.value,
                    "orphan_state": orphan.value,
                    "severity": severity.value,
                    "inbound_occurrences": inbound_occurrences,
                    "unique_referring_pages": len(
                        {str(edge["source_identity"]) for edge in valid_inbound}
                    ),
                    "outbound_occurrences": len(outgoing),
                    "unique_destination_pages": len(
                        {
                            str(item.get("target_url_identity"))
                            for item in outgoing
                            if item.get("target_url_identity")
                        }
                    ),
                    "direct_inlinks": direct_in,
                    "redirect_adjusted_inlinks": redirect_in,
                    "nofollow_inlinks": nofollow_in,
                    "nofollow_outlinks": sum(bool(item.get("nofollow")) for item in outgoing),
                    "redirecting_outlinks": sum(
                        edge["raw_occurrence_count"]
                        for edge in valid_outbound
                        if edge["edge_state"] == "redirect_adjusted"
                    ),
                    "broken_outlinks": sum(
                        1
                        for item in outgoing
                        if (target := nodes.get(str(item.get("target_url_identity") or "")))
                        and target.get("http_status")
                        and int(target["http_status"]) >= 400
                    ),
                    "external_outlinks": sum(item.get("internal") is False for item in outgoing),
                    "sitewide_inlinks": sitewide_in,
                    "non_sitewide_inlinks": max(0, inbound_occurrences - sitewide_in),
                    "crawl_depth": int(page["crawl_depth"]),
                    "graph_depth": reachable["distance"],
                    "reachable": reachable["reachable"],
                    "distinct_seed_paths": int(reachable["reachable"]),
                    "unique_anchor_count": anchor["unique"],
                    "dominant_anchor": anchor["dominant"],
                    "dominant_anchor_share": anchor["share"],
                    "url_anchor_count": anchor["url_count"],
                    "hub_state": hub.value,
                    "authority_state": authority.value,
                    "discovery_sequence": int(page["discovery_sequence"]),
                }
            )
        return result

    def _persist_findings(
        self,
        audit_id: str,
        metrics: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        anchors: dict[str, dict[str, Any]],
    ) -> None:
        sequence = 0
        for metric in metrics:
            if metric["severity"] == "info":
                continue
            self._repository.persist_finding(
                audit_id,
                {
                    "finding_id": stable_identity(audit_id, "page-finding", sequence),
                    "page_identity": metric["page_identity"],
                    "edge_id": None,
                    "stable_code": metric["primary_state"],
                    "severity": metric["severity"],
                    "safe_message": f"Internal-link page state: {metric['primary_state']}"[:512],
                    "context_json": stable_json(
                        {
                            "inlinks": metric["inbound_occurrences"],
                            "outlinks": metric["outbound_occurrences"],
                            "graph_depth": metric["graph_depth"],
                        }
                    ),
                    "finding_sequence": sequence,
                },
            )
            sequence += 1
        for edge in edges:
            if edge["edge_state"] == "direct":
                continue
            self._repository.persist_finding(
                audit_id,
                {
                    "finding_id": stable_identity(audit_id, "edge-finding", sequence),
                    "page_identity": edge["source_identity"],
                    "edge_id": stable_identity(
                        audit_id, edge["source_identity"], edge["target_identity"]
                    ),
                    "stable_code": edge["edge_state"],
                    "severity": "medium",
                    "safe_message": "Internal link does not point directly to its analyzed destination.",
                    "context_json": stable_json({"target": edge["target_url"]}),
                    "finding_sequence": sequence,
                },
            )
            sequence += 1

    def _persist_opportunities(
        self,
        audit_id: str,
        metrics: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        nodes: dict[str, dict[str, Any]],
    ) -> None:
        sequence = 0
        hubs = [item for item in metrics if item["hub_state"] == "candidate"]
        for metric in metrics:
            opportunity: (
                tuple[OpportunityType, OpportunityAction, Confidence, Severity, str | None] | None
            ) = None
            source: str | None = None
            if metric["orphan_state"] in {
                "true_orphan_candidate",
                "sitemap_discovered_without_inlinks",
            }:
                if hubs:
                    hub = sorted(
                        hubs, key=lambda item: (item["graph_depth"] or 999, item["requested_url"])
                    )[0]
                    opportunity = (
                        OpportunityType.LINK_ORPHAN_FROM_HUB,
                        OpportunityAction.ADD_INTERNAL_LINK,
                        Confidence.MEDIUM,
                        Severity.HIGH,
                        "defensible_hub_source",
                    )
                    source = str(hub["requested_url"])
                else:
                    opportunity = (
                        OpportunityType.REVIEW_ISOLATION,
                        OpportunityAction.REVIEW,
                        Confidence.LOW,
                        Severity.HIGH,
                        "no_defensible_source",
                    )
            elif metric["primary_state"] == "low_inlink_count":
                opportunity = (
                    OpportunityType.STRENGTHEN_LOW_INLINK,
                    OpportunityAction.STRENGTHEN_EXISTING_LINK,
                    Confidence.MEDIUM,
                    Severity.MEDIUM,
                    "low_unique_referrers",
                )
            elif metric["primary_state"] == "high_outlink_count":
                opportunity = (
                    OpportunityType.REDUCE_EXCESSIVE,
                    OpportunityAction.REDUCE_EXCESSIVE_LINKS,
                    Confidence.LOW,
                    Severity.MEDIUM,
                    "excessive_outlinks",
                )
            elif metric["hub_state"] == "candidate":
                opportunity = (
                    OpportunityType.PROMOTE_HUB,
                    OpportunityAction.PROMOTE_AS_HUB,
                    Confidence.MEDIUM,
                    Severity.INFO,
                    "strong_distribution_page",
                )
            if opportunity is None:
                continue
            kind, action, confidence, severity, reason = opportunity
            self._repository.persist_opportunity(
                audit_id,
                {
                    "opportunity_id": stable_identity(audit_id, "opportunity", sequence),
                    "source_identity": next(
                        (
                            item["page_identity"]
                            for item in metrics
                            if item["requested_url"] == source
                        ),
                        None,
                    ),
                    "source_url": source,
                    "target_identity": metric["page_identity"],
                    "target_url": metric["requested_url"],
                    "opportunity_type": kind.value,
                    "action": action.value,
                    "confidence": confidence.value,
                    "severity": severity.value,
                    "reason_code": reason,
                    "human_review_required": True,
                    "supporting_metrics_json": stable_json(
                        {
                            "inlinks": metric["inbound_occurrences"],
                            "outlinks": metric["outbound_occurrences"],
                            "graph_depth": metric["graph_depth"],
                        }
                    ),
                    "opportunity_sequence": sequence,
                },
            )
            sequence += 1
        for metric in metrics:
            dominant = str(metric.get("dominant_anchor") or "")
            if dominant and dominant not in GENERIC_ANCHORS and not is_url_anchor(dominant):
                continue
            if int(metric.get("inbound_occurrences") or 0) == 0:
                continue
            self._repository.persist_opportunity(
                audit_id,
                {
                    "opportunity_id": stable_identity(audit_id, "opportunity", sequence),
                    "source_identity": None,
                    "source_url": None,
                    "target_identity": metric["page_identity"],
                    "target_url": metric["requested_url"],
                    "opportunity_type": OpportunityType.IMPROVE_ANCHOR.value,
                    "action": OpportunityAction.REVIEW.value,
                    "confidence": Confidence.LOW.value,
                    "severity": Severity.LOW.value,
                    "reason_code": "generic_or_unavailable_anchor",
                    "human_review_required": True,
                    "supporting_metrics_json": stable_json(
                        {
                            "dominant_anchor": dominant or None,
                            "dominant_share": metric.get("dominant_anchor_share", 0),
                        }
                    ),
                    "opportunity_sequence": sequence,
                },
            )
            sequence += 1
        for edge in edges:
            if edge["edge_state"] == "redirect_adjusted":
                target = nodes.get(str(edge.get("redirect_adjusted_identity")))
                if target is not None:
                    self._repository.persist_opportunity(
                        audit_id,
                        {
                            "opportunity_id": stable_identity(audit_id, "opportunity", sequence),
                            "source_identity": edge["source_identity"],
                            "source_url": edge["source_url"],
                            "target_identity": str(edge["redirect_adjusted_identity"]),
                            "target_url": str(target["requested_url"]),
                            "opportunity_type": OpportunityType.REPLACE_REDIRECTING.value,
                            "action": OpportunityAction.UPDATE_LINK_DESTINATION.value,
                            "confidence": Confidence.HIGH.value,
                            "severity": Severity.MEDIUM.value,
                            "reason_code": "redirect_final_destination_known",
                            "human_review_required": True,
                            "supporting_metrics_json": stable_json(
                                {"original_target": edge["target_url"]}
                            ),
                            "opportunity_sequence": sequence,
                        },
                    )
                    sequence += 1
            original = nodes.get(str(edge["target_identity"]))
            if not original or not original.get("http_status"):
                continue
            if int(original["http_status"]) < 400:
                continue
            replacement_identity = original.get("canonical_identity") or original.get(
                "final_url_identity"
            )
            replacement = nodes.get(str(replacement_identity)) if replacement_identity else None
            deterministic = replacement is not None and replacement.get("eligibility") == "eligible"
            replacement_url = replacement.get("requested_url") if replacement is not None else None
            self._repository.persist_opportunity(
                audit_id,
                {
                    "opportunity_id": stable_identity(audit_id, "opportunity", sequence),
                    "source_identity": edge["source_identity"],
                    "source_url": edge["source_url"],
                    "target_identity": str(replacement_identity or edge["target_identity"]),
                    "target_url": str(replacement_url if deterministic else edge["target_url"]),
                    "opportunity_type": OpportunityType.REPLACE_BROKEN.value,
                    "action": OpportunityAction.REMOVE_OR_REPLACE_LINK.value,
                    "confidence": (
                        Confidence.HIGH.value if deterministic else Confidence.LOW.value
                    ),
                    "severity": Severity.HIGH.value,
                    "reason_code": (
                        "broken_target_replacement_known"
                        if deterministic
                        else "broken_target_no_deterministic_replacement"
                    ),
                    "human_review_required": True,
                    "supporting_metrics_json": stable_json({"original_target": edge["target_url"]}),
                    "opportunity_sequence": sequence,
                },
            )
            sequence += 1

    def get(self, audit_id: str) -> dict[str, Any]:
        value = self._repository.get(audit_id)
        if value is None:
            raise ValueError("internal_link_audit_not_found")
        return value

    def summary(self, audit_id: str) -> dict[str, Any]:
        return self.get(audit_id)

    def list_audits(
        self, cursor: str | None = None, page_size: int | None = None
    ) -> dict[str, Any]:
        size = self._size(page_size)
        fingerprint = filter_fingerprint({})
        offset = decode_cursor(cursor, "audits", AUDIT_ORDERING, fingerprint) if cursor else 0
        rows = self._repository.list_audits(offset, size + 1)
        return _page(rows, size, "audits", AUDIT_ORDERING, fingerprint, offset)

    def list_pages(
        self,
        audit_id: str,
        cursor: str | None = None,
        page_size: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._query(
            audit_id,
            "pages",
            PAGE_ORDERING,
            self._repository.list_pages,
            cursor,
            page_size,
            filters or {},
        )

    def list_edges(
        self,
        audit_id: str,
        cursor: str | None = None,
        page_size: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._query(
            audit_id,
            "edges",
            EDGE_ORDERING,
            self._repository.list_edges,
            cursor,
            page_size,
            filters or {},
        )

    def list_orphans(
        self, audit_id: str, cursor: str | None = None, page_size: int | None = None
    ) -> dict[str, Any]:
        return self.list_pages(
            audit_id,
            cursor,
            page_size,
            {"orphan": ("true_orphan_candidate", "sitemap_discovered_without_inlinks")},
        )

    def list_hubs(
        self, audit_id: str, cursor: str | None = None, page_size: int | None = None
    ) -> dict[str, Any]:
        return self.list_pages(audit_id, cursor, page_size, {"hub": "candidate"})

    def list_authorities(
        self, audit_id: str, cursor: str | None = None, page_size: int | None = None
    ) -> dict[str, Any]:
        return self.list_pages(audit_id, cursor, page_size, {"authority": "candidate"})

    def list_reachability(
        self, audit_id: str, cursor: str | None = None, page_size: int | None = None
    ) -> dict[str, Any]:
        return self._query(
            audit_id,
            "reachability",
            PAGE_ORDERING,
            self._repository.list_reachability,
            cursor,
            page_size,
            {},
        )

    def list_findings(
        self, audit_id: str, cursor: str | None = None, page_size: int | None = None
    ) -> dict[str, Any]:
        return self._query(
            audit_id,
            "findings",
            FINDING_ORDERING,
            self._repository.list_findings,
            cursor,
            page_size,
            {},
        )

    def list_anchors(
        self,
        audit_id: str,
        cursor: str | None = None,
        page_size: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._query(
            audit_id,
            "anchors",
            ANCHOR_ORDERING,
            self._repository.list_anchors,
            cursor,
            page_size,
            filters or {},
        )

    def list_opportunities(
        self,
        audit_id: str,
        cursor: str | None = None,
        page_size: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._query(
            audit_id,
            "opportunities",
            OPPORTUNITY_ORDERING,
            self._repository.list_opportunities,
            cursor,
            page_size,
            filters or {},
        )

    def _query(
        self,
        audit_id: str,
        kind: str,
        ordering: str,
        loader: Any,
        cursor: str | None,
        page_size: int | None,
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        self.get(audit_id)
        size = self._size(page_size)
        fingerprint = filter_fingerprint(filters)
        offset = decode_cursor(cursor, kind, ordering, fingerprint) if cursor else 0
        rows = (
            loader(audit_id, filters, offset, size + 1)
            if kind in {"pages", "edges", "anchors", "opportunities"}
            else loader(audit_id, offset, size + 1)
        )
        return _page(rows, size, kind, ordering, fingerprint, offset)

    def create_export(
        self, audit_id: str, export_format: InternalLinkExportFormat
    ) -> dict[str, Any]:
        audit = self.get(audit_id)
        if audit["state"] not in {"completed", "completed_with_warnings"}:
            raise ValueError("internal_link_export_conflict")
        if self._artifacts is None or not self._artifacts.configuration.enabled:
            raise ValueError("internal_link_export_failed")
        limit = self.configuration.maximum_export_rows
        pages = list(self._repository.list_pages(audit_id, {}, 0, limit + 1))
        anchors = list(self._repository.list_anchors(audit_id, {}, 0, limit + 1))
        opportunities = list(self._repository.list_opportunities(audit_id, {}, 0, limit + 1))
        edges = list(self._repository.list_edges(audit_id, {}, 0, limit + 1))
        reachability = list(self._repository.list_reachability(audit_id, 0, limit + 1))
        truncated = any(
            len(values) > limit for values in (pages, anchors, opportunities, edges, reachability)
        )
        content, row_count = _export_bytes(
            audit,
            export_format,
            pages[:limit],
            anchors[:limit],
            opportunities[:limit],
            edges[:limit],
            reachability[:limit],
            truncated,
        )
        extension = (
            "csv"
            if export_format.value.endswith("_csv")
            else "md"
            if export_format is InternalLinkExportFormat.MARKDOWN
            else "json"
        )
        artifact_type = (
            ArtifactType.CSV_EXPORT
            if extension == "csv"
            else ArtifactType.RUN_SUMMARY_MARKDOWN
            if extension == "md"
            else ArtifactType.RUN_SUMMARY_JSON
        )
        artifact = self._artifacts.store_bytes(
            job_id=str(audit["job_id"]),
            run_id=str(audit["run_id"]),
            artifact_type=artifact_type,
            filename=f"internal-link-{audit_id}-{export_format.value}.{extension}",
            content=content,
        )
        return self._repository.upsert_export(
            audit_id,
            stable_identity(audit_id, export_format.value),
            export_format.value,
            artifact.artifact_id,
            row_count,
            truncated,
        )

    def list_exports(self, audit_id: str) -> tuple[dict[str, Any], ...]:
        self.get(audit_id)
        return self._repository.list_exports(audit_id)

    def cleanup(self) -> int:
        return self._repository.cleanup()

    def diagnostics(self) -> dict[str, Any]:
        return self._repository.diagnostics()

    def _context(self, run_id: str) -> tuple[str, str, bool, int, int]:
        context = self._repository.run_context(run_id)
        if context is None:
            raise ValueError("internal_link_run_not_found")
        if not context[2]:
            raise ValueError("internal_link_run_not_terminal")
        if context[3] == 0:
            raise ValueError("internal_link_page_evidence_unavailable")
        if context[4] == 0:
            raise ValueError("internal_link_link_evidence_unavailable")
        return context

    def _size(self, value: int | None) -> int:
        size = value or self.configuration.default_page_size
        if not 1 <= size <= self.configuration.maximum_page_size:
            raise ValueError("internal_link_invalid_page_size")
        return size


_TERMINAL = {
    state.value
    for state in (
        InternalLinkLifecycle.COMPLETED,
        InternalLinkLifecycle.COMPLETED_WITH_WARNINGS,
        InternalLinkLifecycle.FAILED,
        InternalLinkLifecycle.CANCELLED,
    )
}


def _page(
    rows: tuple[dict[str, Any], ...],
    size: int,
    kind: str,
    ordering: str,
    fingerprint: str,
    offset: int,
) -> dict[str, Any]:
    has_more = len(rows) > size
    return {
        "items": rows[:size],
        "page_size": size,
        "next_cursor": encode_cursor(kind, ordering, fingerprint, offset + size)
        if has_more
        else None,
        "ordering": ordering,
    }


def _csv_safe(value: Any) -> Any:
    if isinstance(value, str) and value[:1] in {"=", "+", "-", "@"}:
        return "'" + value
    if isinstance(value, (dict, list, tuple)):
        return stable_json(value)
    return value


def _csv_bytes(rows: list[dict[str, Any]], columns: tuple[str, ...]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _csv_safe(row.get(key)) for key in columns})
    return stream.getvalue().encode()


def _export_bytes(
    audit: dict[str, Any],
    export_format: InternalLinkExportFormat,
    pages: list[dict[str, Any]],
    anchors: list[dict[str, Any]],
    opportunities: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    reachability: list[dict[str, Any]],
    truncated: bool,
) -> tuple[bytes, int]:
    if export_format is InternalLinkExportFormat.PAGE_METRICS_CSV:
        columns = (
            "audit_id",
            "requested_url",
            "page_identity",
            "eligibility",
            "primary_state",
            "orphan_state",
            "inbound_occurrences",
            "unique_referring_pages",
            "outbound_occurrences",
            "unique_destination_pages",
            "crawl_depth",
            "graph_depth",
            "reachable",
            "hub_state",
            "authority_state",
            "dominant_anchor",
            "dominant_anchor_share",
            "severity",
            "page_sequence",
        )
        return _csv_bytes(pages, columns), len(pages)
    if export_format is InternalLinkExportFormat.ORPHANS_CSV:
        rows = [
            row
            for row in pages
            if row["orphan_state"]
            in {"true_orphan_candidate", "sitemap_discovered_without_inlinks"}
        ]
        return _csv_bytes(
            rows,
            (
                "requested_url",
                "orphan_state",
                "crawl_depth",
                "graph_depth",
                "severity",
                "page_sequence",
            ),
        ), len(rows)
    if export_format is InternalLinkExportFormat.HUBS_AUTHORITIES_CSV:
        rows = [
            row
            for row in pages
            if row["hub_state"] == "candidate" or row["authority_state"] == "candidate"
        ]
        return _csv_bytes(
            rows,
            (
                "requested_url",
                "hub_state",
                "authority_state",
                "unique_referring_pages",
                "unique_destination_pages",
                "crawl_depth",
                "page_sequence",
            ),
        ), len(rows)
    if export_format is InternalLinkExportFormat.ANCHORS_CSV:
        return _csv_bytes(
            anchors,
            (
                "target_url",
                "normalized_anchor",
                "representative_anchor",
                "occurrence_count",
                "source_page_count",
                "share",
                "anchor_state",
                "severity",
                "anchor_sequence",
            ),
        ), len(anchors)
    if export_format is InternalLinkExportFormat.OPPORTUNITIES_CSV:
        return _csv_bytes(
            opportunities,
            (
                "source_url",
                "target_url",
                "opportunity_type",
                "action",
                "confidence",
                "severity",
                "reason_code",
                "human_review_required",
                "opportunity_sequence",
            ),
        ), len(opportunities)
    if export_format is InternalLinkExportFormat.JSON:
        return stable_json(
            {
                "version": INTERNAL_LINK_EXPORT_VERSION,
                "audit": audit,
                "configuration": json.loads(str(audit["configuration_json"])),
                "seeds": json.loads(str(audit["seed_snapshot_json"])),
                "pages": pages,
                "edges": edges,
                "reachability": reachability,
                "anchors": anchors,
                "opportunities": opportunities,
                "truncated": truncated,
                "evidence_versions": {
                    "graph": INTERNAL_LINK_GRAPH_VERSION,
                    "policy": INTERNAL_LINK_POLICY_VERSION,
                },
            }
        ).encode(), len(pages)
    lines = [
        "# Internal-Link Analysis",
        f"Audit: `{audit['audit_id']}`",
        f"Source run: `{audit['run_id']}`",
        "## Configuration",
        f"```json\n{audit['configuration_json']}\n```",
        "## Summary",
        f"- Eligible pages: {audit['eligible_page_count']}",
        f"- Reachable pages: {audit['reachable_count']}",
        f"- Orphan candidates: {audit['orphan_candidate_count']}",
        f"- Deep pages: {audit['deep_page_count']}",
        f"- Hub candidates: {audit['hub_candidate_count']}",
        f"- Authority candidates: {audit['authority_candidate_count']}",
        "## Orphan Candidates",
        *[
            f"- {row['requested_url']}"
            for row in pages
            if row["orphan_state"]
            in {"true_orphan_candidate", "sitemap_discovered_without_inlinks"}
        ],
        "## Deep and weak pages",
        *[
            f"- {row['requested_url']} — {row['primary_state']}"
            for row in pages
            if row["primary_state"] in {"deep_page", "low_inlink_count"}
        ],
        "## Hub and Authority Candidates",
        *[
            f"- {row['requested_url']} — hub={row['hub_state']}, authority={row['authority_state']}"
            for row in pages
            if row["hub_state"] == "candidate" or row["authority_state"] == "candidate"
        ],
        "## Anchor Findings",
        *[
            f"- {row['target_url']} — {row['anchor_state']}"
            for row in anchors
            if row["anchor_state"] != "healthy"
        ],
        "## Opportunities",
        *[
            f"- {row['target_url']} — {row['action']} ({row['confidence']})"
            for row in opportunities
        ],
        "## Methodology and limitations",
        "Deterministic analysis of retained crawl, page, link, redirect, canonical, scope, and indexability evidence. No semantic similarity, traffic data, ranking data, or live-site changes are used.",
        f"Versions: {INTERNAL_LINK_GRAPH_VERSION}; {INTERNAL_LINK_POLICY_VERSION}",
    ]
    return ("\n\n".join(lines) + "\n").encode(), len(pages)
