"""Durable network-free broken-link and redirect analysis service."""

# ruff: noqa: ANN401, E501, FBT001, PLR0913, PLR0915, PLR2004, SIM113

from __future__ import annotations

import asyncio
import csv
import io
import json
from collections import defaultdict
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from musimack_tools.crawl.normalization import normalize_url
from musimack_tools.crawl.scope import create_scope_policy, evaluate_scope
from musimack_tools.domain.artifacts import ArtifactType
from musimack_tools.domain.link_audit import (
    LINK_ANALYSIS_POLICY_VERSION,
    LINK_AUDIT_EXPORT_VERSION,
    LINK_AUDIT_VERSION,
    REDIRECT_ANALYSIS_POLICY_VERSION,
    BrokenLinkReason,
    BrokenLinkState,
    Confidence,
    ExportFormat,
    LinkAuditConfiguration,
    LinkAuditLifecycle,
    RecommendationAction,
    RedirectReason,
    RedirectState,
    Severity,
    TargetClassification,
    TargetEvidence,
    audit_identity,
    classify_target,
    stable_identity,
    stable_json,
)
from musimack_tools.domain.urls import CrawlScopePolicy, UrlNormalizationError

if TYPE_CHECKING:
    from musimack_tools.artifacts.service import ArtifactService
    from musimack_tools.persistence.link_audit_repository import SQLAlchemyLinkAuditRepository


class LinkAuditService:
    def __init__(
        self,
        configuration: LinkAuditConfiguration,
        repository: SQLAlchemyLinkAuditRepository,
        artifacts: ArtifactService | None = None,
    ) -> None:
        self.configuration = configuration
        self._repository = repository
        self._artifacts = artifacts
        self._repository.reconcile_interrupted()

    def evidence_status(self, run_id: str) -> dict[str, Any]:
        context = self._repository.run_context(run_id)
        if context is None:
            raise ValueError("link_audit_run_not_found")
        scope = self._repository.run_scope_snapshot(run_id)
        return {
            "run_id": run_id,
            "terminal": context[2],
            "page_evidence_count": context[3],
            "link_evidence_count": context[4],
            "scope_available": scope is not None,
            "compatible": context[2] and context[3] > 0 and context[4] > 0 and scope is not None,
        }

    def create_audit(self, run_id: str) -> dict[str, Any]:
        if not self.configuration.enabled:
            raise ValueError("link_audit_disabled")
        job_id, seed, _terminal, _pages, _links = self._context(run_id)
        self._scope(run_id, seed)
        identifier = audit_identity(run_id, self.configuration)
        return self._repository.create(identifier, job_id, run_id, seed, self.configuration)

    async def execute_audit(self, audit_id: str) -> dict[str, Any]:
        audit = self.get(audit_id)
        if audit["state"] in {
            LinkAuditLifecycle.COMPLETED.value,
            LinkAuditLifecycle.COMPLETED_WITH_WARNINGS.value,
            LinkAuditLifecycle.FAILED.value,
            LinkAuditLifecycle.CANCELLED.value,
        }:
            raise ValueError("link_audit_already_terminal")
        if not self._repository.claim_execution(audit_id):
            raise ValueError("link_audit_already_executing")
        try:
            return self._execute_claimed(audit_id, audit)
        except asyncio.CancelledError:
            self._repository.transition(
                audit_id, LinkAuditLifecycle.CANCELLED, "link_audit_cancelled"
            )
            raise
        except Exception:
            self._repository.fail_if_running(audit_id, "link_audit_execution_failed")
            raise

    def _execute_claimed(self, audit_id: str, audit: dict[str, Any]) -> dict[str, Any]:
        run_id = str(audit["run_id"])
        scope = self._scope(run_id, str(audit["seed_url"]))
        links = self._repository.source_links(run_id)
        pages = self._repository.pages(run_id)
        if not links:
            raise ValueError("link_audit_link_evidence_unavailable")
        if not pages:
            raise ValueError("link_audit_page_evidence_unavailable")
        self._repository.transition(audit_id, LinkAuditLifecycle.BUILDING_GRAPH)
        page_by_identity: dict[str, dict[str, Any]] = {}
        page_by_evidence_id: dict[str, dict[str, Any]] = {}
        for source_page in pages:
            page_by_evidence_id[str(source_page["evidence_id"])] = source_page
            page_by_identity[str(source_page["requested_url_identity"])] = source_page
            if source_page.get("final_url_identity"):
                page_by_identity.setdefault(str(source_page["final_url_identity"]), source_page)
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for link in links:
            key = str(
                link.get("target_url_identity")
                or stable_identity(link.get("link_type"), link.get("raw_href"), link.get("link_id"))
            )
            grouped[key].append(link)
        self._repository.transition(audit_id, LinkAuditLifecycle.CLASSIFYING_LINKS)
        parsed_page_count = sum(bool(item.get("parsed_as_html")) for item in pages)
        target_rows: list[dict[str, Any]] = []
        chain_sequence = 0
        finding_sequence = 0
        recommendation_sequence = 0
        for target_sequence, (identity, occurrences) in enumerate(sorted(grouped.items())):
            representative = occurrences[0]
            target_url = str(
                representative.get("resolved_url")
                or representative.get("raw_href")
                or "(invalid href)"
            )
            page = page_by_identity.get(str(representative.get("target_url_identity") or ""))
            sources = {str(item["source_evidence_id"]) for item in occurrences}
            anchors = {str(item["anchor_text"]) for item in occurrences if item.get("anchor_text")}
            depths = [int(item["source_crawl_depth"]) for item in occurrences]
            sitewide = (
                parsed_page_count >= self.configuration.minimum_sitewide_crawl_pages
                and len(sources) >= self.configuration.minimum_sitewide_source_pages
                and len(sources) / max(parsed_page_count, 1) >= self.configuration.sitewide_ratio
            )
            classification = self._classify_occurrences(
                representative,
                page,
                page_by_evidence_id.get(str(representative["source_evidence_id"])),
                scope,
            )
            if sitewide and classification.broken_state is BrokenLinkState.BROKEN_INTERNAL_LINK:
                classification = replace(classification, severity=Severity.CRITICAL)
            target_id = stable_identity(audit_id, identity)
            target_values = {
                "target_id": target_id,
                "target_url": target_url[:4096],
                "target_url_identity": identity,
                "representative_link_id": representative["link_id"],
                "page_evidence_id": page.get("evidence_id") if page else None,
                "internal": representative.get("internal"),
                "in_scope": representative.get("in_scope"),
                "http_status": page.get("http_status") if page else None,
                "fetch_state": page.get("evidence_state") if page else None,
                "content_type": page.get("content_type") if page else None,
                "broken_state": classification.broken_state.value,
                "redirect_state": classification.redirect_state.value,
                "primary_reason": classification.broken_reason.value,
                "redirect_reason": classification.redirect_reason.value,
                "severity": classification.severity.value,
                "action": classification.action.value,
                "confidence": classification.confidence.value,
                "final_target": classification.final_destination,
                "redirect_hop_count": len(page.get("redirects", ())) if page else 0,
                "unique_source_page_count": len(sources),
                "total_occurrence_count": len(occurrences),
                "unique_anchor_count": len(anchors),
                "minimum_source_depth": min(depths),
                "maximum_source_depth": max(depths),
                "sitewide_candidate": sitewide,
                "target_sequence": target_sequence,
                "analysis_version": LINK_ANALYSIS_POLICY_VERSION,
            }
            target_rows.append(self._repository.persist_target(audit_id, target_values))
            redirects = tuple(page.get("redirects", ())) if page else ()
            chain_id: str | None = None
            if redirects or classification.redirect_state is RedirectState.REDIRECT_LOOP:
                self._repository.transition(audit_id, LinkAuditLifecycle.EXPANDING_REDIRECTS)
                nodes = _chain_nodes(target_url, redirects)
                loop = classification.redirect_state is RedirectState.REDIRECT_LOOP
                chain_id = stable_identity(audit_id, *nodes)
                self._repository.persist_chain(
                    audit_id,
                    {
                        "chain_id": chain_id,
                        "target_id": target_id,
                        "entry_url": target_url,
                        "final_url": classification.final_destination,
                        "chain_state": classification.redirect_state.value,
                        "hop_count": len(redirects),
                        "loop": loop,
                        "nodes_json": stable_json(nodes),
                        "edges_json": stable_json(redirects),
                        "severity": classification.severity.value,
                        "source_occurrence_count": len(occurrences),
                        "chain_sequence": chain_sequence,
                        "chain_version": REDIRECT_ANALYSIS_POLICY_VERSION,
                    },
                )
                chain_sequence += 1
            if classification.severity is not Severity.INFO:
                self._repository.persist_finding(
                    audit_id,
                    {
                        "finding_id": stable_identity(audit_id, "finding", finding_sequence),
                        "target_id": target_id,
                        "chain_id": chain_id,
                        "stable_code": (
                            classification.redirect_reason.value
                            if classification.redirect_state is not RedirectState.NO_REDIRECT
                            else classification.broken_reason.value
                        ),
                        "severity": classification.severity.value,
                        "safe_message": _safe_message(classification),
                        "context_json": stable_json(
                            {
                                "unique_source_pages": len(sources),
                                "total_occurrences": len(occurrences),
                                "sitewide_candidate": sitewide,
                            }
                        ),
                        "finding_sequence": finding_sequence,
                        "created_at": datetime.now(UTC),
                    },
                )
                finding_sequence += 1
            self._repository.persist_recommendation(
                audit_id,
                {
                    "recommendation_id": stable_identity(
                        audit_id, "recommendation", recommendation_sequence
                    ),
                    "target_id": target_id,
                    "source_url": target_url,
                    "suggested_destination": classification.final_destination,
                    "action": classification.action.value,
                    "confidence": classification.confidence.value,
                    "reason_code": (
                        classification.redirect_reason.value
                        if classification.redirect_state is not RedirectState.NO_REDIRECT
                        else classification.broken_reason.value
                    ),
                    "severity": classification.severity.value,
                    "human_review_required": classification.confidence is not Confidence.HIGH
                    or classification.action
                    in {
                        RecommendationAction.CREATE_REDIRECT,
                        RecommendationAction.REPLACE_REDIRECT,
                        RecommendationAction.REVIEW,
                    },
                    "supporting_evidence_json": stable_json(
                        {
                            "target_status": page.get("http_status") if page else None,
                            "redirect_chain": redirects,
                            "destination_working": bool(
                                page
                                and page.get("http_status")
                                and 200 <= page["http_status"] < 300
                            ),
                            "same_scope": representative.get("in_scope"),
                        }
                    ),
                    "unique_source_page_count": len(sources),
                    "total_occurrence_count": len(occurrences),
                    "recommendation_sequence": recommendation_sequence,
                },
            )
            recommendation_sequence += 1
        self._repository.transition(audit_id, LinkAuditLifecycle.DETECTING_LOOPS)
        self._repository.transition(audit_id, LinkAuditLifecycle.BUILDING_RECOMMENDATIONS)
        return self._repository.finalize(audit_id)

    def _classify_occurrences(
        self,
        link: dict[str, Any],
        page: dict[str, Any] | None,
        source_page: dict[str, Any] | None,
        scope: CrawlScopePolicy,
    ) -> TargetClassification:
        link_type = str(link.get("link_type"))
        if link_type != "http":
            reason = {
                "mailto": BrokenLinkReason.MAILTO_LINK,
                "tel": BrokenLinkReason.TEL_LINK,
                "javascript": BrokenLinkReason.JAVASCRIPT_LINK,
                "data": BrokenLinkReason.DATA_LINK,
                "fragment": BrokenLinkReason.FRAGMENT_ONLY_LINK,
                "invalid": BrokenLinkReason.INVALID_HREF,
            }.get(link_type, BrokenLinkReason.UNSUPPORTED_SCHEME)
            return TargetClassification(
                BrokenLinkState.EXTERNAL_LINK_NOT_AUDITED,
                reason,
                RedirectState.NO_REDIRECT,
                RedirectReason.NONE,
                Severity.INFO,
                RecommendationAction.NO_ACTION,
                Confidence.HIGH,
                None,
            )
        redirects = tuple(page.get("redirects", ())) if page else ()
        final = page.get("final_url") if page else None
        final_in_scope: bool | None = None
        final_internal: bool | None = None
        if final:
            try:
                normalized_final = normalize_url(str(final))
                final_in_scope = evaluate_scope(scope, normalized_final).allowed
                normalized_target = normalize_url(
                    str(link.get("resolved_url") or link.get("raw_href") or "")
                )
                final_internal = normalized_final.hostname == normalized_target.hostname
            except UrlNormalizationError:
                final_in_scope = False
                final_internal = False
        loop = bool(page and page.get("redirect_loop")) or _has_normalized_loop(redirects)
        return classify_target(
            TargetEvidence(
                target_url=str(link.get("resolved_url") or link.get("raw_href") or ""),
                http_status=page.get("http_status") if page else None,
                fetch_failed=bool(page and page.get("fetch_failed")),
                failure_code=page.get("failure_code") if page else None,
                content_type_category=page.get("content_type_category") if page else None,
                in_scope=link.get("in_scope"),
                internal=link.get("internal"),
                source_available=bool(source_page and not source_page.get("fetch_failed")),
                source_partial=bool(
                    source_page
                    and source_page.get("evidence_state") in {"partial", "truncated", "cancelled"}
                ),
                redirect_hops=redirects,
                redirect_loop=loop,
                final_url=str(final) if final else None,
                final_status=page.get("http_status") if page else None,
                final_content_type_category=page.get("content_type_category") if page else None,
                final_in_scope=final_in_scope,
                final_internal=final_internal,
                chain_too_long=len(redirects) > self.configuration.maximum_redirect_chain_depth,
            )
        )

    def get(self, audit_id: str) -> dict[str, Any]:
        value = self._repository.get(audit_id)
        if value is None:
            raise ValueError("link_audit_not_found")
        return value

    def list_audits(
        self, offset: int = 0, page_size: int | None = None
    ) -> tuple[dict[str, Any], ...]:
        return self._repository.list_audits(offset, self._size(page_size))

    def summary(self, audit_id: str) -> dict[str, Any]:
        audit = self.get(audit_id)
        return {
            key: audit[key]
            for key in (
                "link_occurrence_count",
                "source_target_pair_count",
                "target_count",
                "working_target_count",
                "broken_target_count",
                "redirect_target_count",
                "unverified_target_count",
                "redirect_chain_count",
                "redirect_loop_count",
                "recommendation_count",
                "warning_count",
            )
        }

    def list_targets(
        self,
        audit_id: str,
        offset: int = 0,
        page_size: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        self.get(audit_id)
        return self._repository.list_targets(audit_id, offset, self._size(page_size), filters)

    def list_occurrences(
        self,
        audit_id: str,
        offset: int = 0,
        page_size: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        self.get(audit_id)
        return self._repository.list_occurrences(audit_id, offset, self._size(page_size), filters)

    def list_chains(
        self,
        audit_id: str,
        offset: int = 0,
        page_size: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        self.get(audit_id)
        return self._repository.list_chains(audit_id, offset, self._size(page_size), filters)

    def list_loops(
        self, audit_id: str, offset: int = 0, page_size: int | None = None
    ) -> tuple[dict[str, Any], ...]:
        return self.list_chains(audit_id, offset, page_size, {"loop": True})

    def list_findings(
        self,
        audit_id: str,
        offset: int = 0,
        page_size: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        self.get(audit_id)
        return self._repository.list_findings(audit_id, offset, self._size(page_size), filters)

    def list_recommendations(
        self,
        audit_id: str,
        offset: int = 0,
        page_size: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        self.get(audit_id)
        return self._repository.list_recommendations(
            audit_id, offset, self._size(page_size), filters
        )

    def create_export(self, audit_id: str, export_format: ExportFormat) -> dict[str, Any]:
        audit = self.get(audit_id)
        if audit["state"] not in {
            LinkAuditLifecycle.COMPLETED.value,
            LinkAuditLifecycle.COMPLETED_WITH_WARNINGS.value,
        }:
            raise ValueError("link_audit_export_conflict")
        if self._artifacts is None or not self._artifacts.configuration.enabled:
            raise ValueError("link_audit_export_failed")
        targets = list(
            self._repository.list_targets(audit_id, 0, self.configuration.maximum_export_rows + 1)
        )
        occurrences = list(
            self._repository.list_occurrences(
                audit_id, 0, self.configuration.maximum_export_rows + 1
            )
        )
        chains = list(
            self._repository.list_chains(audit_id, 0, self.configuration.maximum_export_rows + 1)
        )
        recommendations = list(
            self._repository.list_recommendations(
                audit_id, 0, self.configuration.maximum_export_rows + 1
            )
        )
        truncated = any(
            len(values) > self.configuration.maximum_export_rows
            for values in (targets, occurrences, chains, recommendations)
        )
        targets = targets[: self.configuration.maximum_export_rows]
        occurrences = occurrences[: self.configuration.maximum_export_rows]
        chains = chains[: self.configuration.maximum_export_rows]
        recommendations = recommendations[: self.configuration.maximum_export_rows]
        content, rows = _export_bytes(
            audit, export_format, targets, occurrences, chains, recommendations, truncated
        )
        kind = {
            ExportFormat.BROKEN_LINKS_CSV: ArtifactType.CSV_EXPORT,
            ExportFormat.REDIRECT_CHAINS_CSV: ArtifactType.CSV_EXPORT,
            ExportFormat.REDIRECT_MAP_CSV: ArtifactType.CSV_EXPORT,
            ExportFormat.JSON: ArtifactType.RUN_SUMMARY_JSON,
            ExportFormat.MARKDOWN: ArtifactType.RUN_SUMMARY_MARKDOWN,
        }[export_format]
        extension = (
            "csv"
            if export_format.value.endswith("_csv")
            else "md"
            if export_format is ExportFormat.MARKDOWN
            else "json"
        )
        artifact = self._artifacts.store_bytes(
            job_id=str(audit["job_id"]),
            run_id=str(audit["run_id"]),
            artifact_type=kind,
            filename=f"link-audit-{audit_id}-{export_format.value}.{extension}",
            content=content,
        )
        return self._repository.upsert_export(
            audit_id, export_format.value, artifact.artifact_id, rows, truncated
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
            raise ValueError("link_audit_run_not_found")
        if not context[2]:
            raise ValueError("link_audit_run_not_terminal")
        if context[3] == 0:
            raise ValueError("link_audit_page_evidence_unavailable")
        if context[4] == 0:
            raise ValueError("link_audit_link_evidence_unavailable")
        return context

    def _scope(self, run_id: str, seed: str) -> CrawlScopePolicy:
        snapshot = self._repository.run_scope_snapshot(run_id)
        if snapshot is None:
            raise ValueError("link_audit_scope_unavailable")
        mode, approved_hosts = snapshot
        return create_scope_policy(normalize_url(seed), mode=mode, approved_hosts=approved_hosts)

    def _size(self, value: int | None) -> int:
        size = value or self.configuration.default_page_size
        if not 1 <= size <= self.configuration.maximum_page_size:
            raise ValueError("link_audit_invalid_page_size")
        return size


def _has_normalized_loop(redirects: tuple[dict[str, Any], ...]) -> bool:
    seen: set[str] = set()
    for value in _chain_nodes("", redirects):
        try:
            identity = normalize_url(value).normalized
        except UrlNormalizationError:
            identity = value
        if identity in seen:
            return True
        seen.add(identity)
    return False


def _chain_nodes(entry: str, redirects: tuple[dict[str, Any], ...]) -> tuple[str, ...]:
    values = [entry] if entry else []
    for hop in redirects:
        source = str(hop.get("source_url") or "")
        target = str(hop.get("target_url") or "")
        if source and (not values or values[-1] != source):
            values.append(source)
        if target:
            values.append(target)
    return tuple(values)


def _safe_message(value: TargetClassification) -> str:
    if value.redirect_state is RedirectState.REDIRECT_LOOP:
        return "An internal link enters a redirect loop."
    if value.redirect_state is RedirectState.REDIRECT_TO_BROKEN_TARGET:
        return "An internal link redirects to a broken destination."
    if value.broken_state is BrokenLinkState.BROKEN_INTERNAL_LINK:
        return "An internal link resolves to a known broken destination."
    if value.broken_state is BrokenLinkState.UNVERIFIED_INTERNAL_LINK:
        return "An internal link target was not verified in the selected crawl evidence."
    return "A link or redirect requires review."


def _csv_bytes(rows: list[dict[str, Any]], columns: tuple[str, ...]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _csv_safe(row.get(key)) for key in columns})
    return stream.getvalue().encode("utf-8")


def _csv_safe(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        value = stable_json(value)
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return f"'{value}"
    return value


def _export_bytes(
    audit: dict[str, Any],
    export_format: ExportFormat,
    targets: list[dict[str, Any]],
    occurrences: list[dict[str, Any]],
    chains: list[dict[str, Any]],
    recommendations: list[dict[str, Any]],
    truncated: bool,
) -> tuple[bytes, int]:
    if export_format is ExportFormat.BROKEN_LINKS_CSV:
        targets_by_identity = {str(row["target_url_identity"]): row for row in targets}
        rows = []
        for occurrence in occurrences:
            target = targets_by_identity.get(str(occurrence.get("target_url_identity")))
            if (
                target is None
                or target["broken_state"] != BrokenLinkState.BROKEN_INTERNAL_LINK.value
            ):
                continue
            rows.append(
                {
                    "audit_id": audit["audit_id"],
                    "run_id": audit["run_id"],
                    **occurrence,
                    **target,
                    "reason_code": target["primary_reason"],
                    "evidence_version": audit["link_evidence_version"],
                    "analysis_version": audit["link_policy_version"],
                }
            )
        columns: tuple[str, ...] = (
            "audit_id",
            "run_id",
            "source_requested_url",
            "source_url_identity",
            "source_status",
            "source_indexability",
            "raw_href",
            "resolved_url",
            "target_url_identity",
            "anchor_text",
            "link_sequence",
            "internal",
            "in_scope",
            "http_status",
            "fetch_state",
            "content_type",
            "broken_state",
            "redirect_state",
            "redirect_hop_count",
            "final_target",
            "severity",
            "action",
            "reason_code",
            "confidence",
            "unique_source_page_count",
            "total_occurrence_count",
            "sitewide_candidate",
            "evidence_version",
            "analysis_version",
            "discovery_sequence",
        )
        return _csv_bytes(rows, columns), len(rows)
    if export_format is ExportFormat.REDIRECT_CHAINS_CSV:
        columns = (
            "entry_url",
            "final_url",
            "chain_state",
            "hop_count",
            "loop",
            "nodes_json",
            "severity",
            "source_occurrence_count",
            "chain_sequence",
        )
        return _csv_bytes(chains, columns), len(chains)
    if export_format is ExportFormat.REDIRECT_MAP_CSV:
        targets_by_id = {str(row["target_id"]): row for row in targets}
        chains_by_target = {str(row["target_id"]): row for row in chains}
        columns = (
            "source_url",
            "current_destination",
            "suggested_destination",
            "current_chain",
            "hop_count",
            "loop",
            "target_status",
            "action",
            "confidence",
            "reason_code",
            "unique_source_page_count",
            "human_review_required",
        )
        rows = []
        for recommendation in recommendations:
            if recommendation["action"] == RecommendationAction.NO_ACTION.value:
                continue
            target = targets_by_id[str(recommendation["target_id"])]
            chain = chains_by_target.get(str(recommendation["target_id"]), {})
            rows.append(
                {
                    **recommendation,
                    "current_destination": target.get("final_target"),
                    "current_chain": chain.get("nodes_json"),
                    "hop_count": chain.get("hop_count", 0),
                    "loop": chain.get("loop", False),
                    "target_status": target.get("http_status"),
                }
            )
        return _csv_bytes(rows, columns), len(rows)
    if export_format is ExportFormat.JSON:
        payload = {
            "version": LINK_AUDIT_EXPORT_VERSION,
            "audit": audit,
            "thresholds": json.loads(str(audit["configuration_json"])),
            "targets": targets,
            "occurrences": occurrences,
            "redirect_chains": chains,
            "recommendations": recommendations,
            "truncated": truncated,
            "evidence_versions": {
                "audit": LINK_AUDIT_VERSION,
                "link_policy": LINK_ANALYSIS_POLICY_VERSION,
                "redirect_policy": REDIRECT_ANALYSIS_POLICY_VERSION,
            },
        }
        return json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode(), len(
            targets
        )
    sections = [
        "# Broken-Link and Redirect Audit",
        f"Audit: `{audit['audit_id']}`",
        f"Source run: `{audit['run_id']}`",
        "## Configuration and thresholds",
        f"```json\n{audit['configuration_json']}\n```",
        "## Summary",
        f"- Targets: {audit['target_count']}",
        f"- Broken targets: {audit['broken_target_count']}",
        f"- Redirect targets: {audit['redirect_target_count']}",
        f"- Redirect loops: {audit['redirect_loop_count']}",
        "## Critical findings",
        *[
            f"- {row['target_url']} — {row['primary_reason']}"
            for row in targets
            if row["severity"] == "critical"
        ],
        "## Broken internal links",
        *[
            f"- {row['target_url']} — {row['primary_reason']}"
            for row in targets
            if row["broken_state"] == "broken_internal_link"
        ],
        "## Redirect chains and loops",
        *[f"- {row['entry_url']} → {row.get('final_url') or '(unresolved)'}" for row in chains],
        "## Sitewide candidates",
        *[f"- {row['target_url']}" for row in targets if row["sitewide_candidate"]],
        "## Redirect-map recommendations",
        *[
            f"- {row['source_url']} → {row.get('suggested_destination') or '(review)'} ({row['action']})"
            for row in recommendations
            if row["action"] != "no_action"
        ],
        "## Methodology and limitations",
        "Selected-run durable page, source-link, and redirect evidence only. External links and fragment targets are not fetched or validated.",
        "## Version information",
        f"- {LINK_AUDIT_EXPORT_VERSION}",
    ]
    return ("\n".join(sections) + "\n").encode(), len(targets)
