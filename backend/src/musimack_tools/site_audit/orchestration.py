"""CSA-04 orchestration over accepted crawl, evidence, and artifact authorities."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Protocol, cast

from musimack_tools.domain.application import (
    ApplicationOutcomeCode,
    CrawlLimitOverrides,
    CrawlProfileName,
    RawApplicationCrawlRequest,
    ScopeProfile,
)
from musimack_tools.domain.crawl import CrawlExclusionRule, ExclusionRuleType
from musimack_tools.domain.page_evidence import (
    MetadataPresence,
    PageEvidenceFilters,
    PageEvidenceListItem,
    PageEvidenceState,
)
from musimack_tools.domain.site_audit_orchestration import (
    SITE_AUDIT_ISSUE_DEFINITION_VERSION,
    SITE_AUDIT_ORCHESTRATION_VERSION,
    ArtifactPurpose,
    OrchestrationState,
    PriorityInputs,
    SiteAuditOrchestrationError,
    SiteAuditStage,
    StageState,
    priority_explanation,
    priority_key,
    stable_identifier,
    validate_snapshot_integrity,
)
from musimack_tools.domain.site_audit_persistence import (
    AuditLifecycle,
    Population,
    SiteAuditPersistenceError,
)
from musimack_tools.domain.site_audit_settings import (
    RuleAction,
    RuleMatchType,
    RuleScope,
    RuleSource,
    UrlGovernanceRule,
    normalize_governed_url,
    rule_matches,
)
from musimack_tools.site_audit.artifacts import generate_site_audit_artifacts
from musimack_tools.site_audit.specialists import (
    SiteAuditSpecialistGateway,
    SpecialistEvidence,
    SpecialistRequest,
)

_PATTERN_CANDIDATE_MINIMUM = 3
_HTTP_SUCCESS_MINIMUM = 200
_HTTP_SUCCESS_MAXIMUM = 300
_HTTP_ERROR_MINIMUM = 400
_PERSISTENCE_PAGE_SIZE = 500
_LINK_DISCOVERY_PAGE_SIZE = 200
_SPECIALIST_STAGES = (
    SiteAuditStage.METADATA,
    SiteAuditStage.EXISTING_SITEMAP,
    SiteAuditStage.BROKEN_LINKS,
    SiteAuditStage.INTERNAL_LINKS,
    SiteAuditStage.IMAGES,
    SiteAuditStage.STRUCTURED_DATA,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from musimack_tools.api.dependencies import InternalApiApplication
    from musimack_tools.artifacts.service import ArtifactService
    from musimack_tools.domain.application import (
        ApplicationCancellationResult,
        ApplicationJobStatus,
        ApplicationRecommendationPage,
        ApplicationResultProjection,
        ApplicationSubmissionResult,
    )
    from musimack_tools.persistence.page_evidence_repository import (
        SQLAlchemyPageEvidenceRepository,
    )
    from musimack_tools.persistence.site_audit_orchestration_repository import (
        SQLAlchemySiteAuditOrchestrationRepository,
    )
    from musimack_tools.persistence.site_audit_repository import SQLAlchemySiteAuditRepository


class SiteAuditCrawlGateway(Protocol):
    async def submit(self, request: RawApplicationCrawlRequest) -> ApplicationSubmissionResult: ...

    async def status(self, job_id: str) -> ApplicationJobStatus: ...

    async def result(self, job_id: str) -> ApplicationResultProjection: ...

    async def cancel(self, job_id: str) -> ApplicationCancellationResult: ...

    async def recommendations(
        self, job_id: str, *, offset: int, limit: int
    ) -> ApplicationRecommendationPage: ...


class ApplicationSiteAuditCrawlGateway:
    """Adapter retaining the accepted application validation and durable job path."""

    def __init__(self, application: InternalApiApplication) -> None:
        self._application = application

    async def submit(self, request: RawApplicationCrawlRequest) -> ApplicationSubmissionResult:
        return await self._application.submit(request)

    async def status(self, job_id: str) -> ApplicationJobStatus:
        return await self._application.get_job_status(job_id)

    async def result(self, job_id: str) -> ApplicationResultProjection:
        return await self._application.get_job_result(job_id)

    async def cancel(self, job_id: str) -> ApplicationCancellationResult:
        return await self._application.cancel_job(job_id)

    async def recommendations(
        self, job_id: str, *, offset: int, limit: int
    ) -> ApplicationRecommendationPage:
        return await self._application.get_job_recommendations(job_id, offset=offset, limit=limit)


class SiteAuditOrchestrationService:
    """Restart-safe coordinator; every durable write is idempotent or deterministic."""

    def __init__(  # noqa: PLR0913 - explicit authorities keep composition auditable.
        self,
        repository: SQLAlchemySiteAuditRepository,
        orchestration: SQLAlchemySiteAuditOrchestrationRepository,
        page_evidence: SQLAlchemyPageEvidenceRepository,
        crawl: SiteAuditCrawlGateway,
        artifacts: ArtifactService,
        specialists: SiteAuditSpecialistGateway | None = None,
    ) -> None:
        self._repository = repository
        self._orchestration = orchestration
        self._page_evidence = page_evidence
        self._crawl = crawl
        self._artifacts = artifacts
        self._specialists = specialists

    async def submit(self, audit_id: str, *, actor: str) -> dict[str, Any]:
        del actor  # Authorization is enforced by the private API boundary.
        audit = self._required_audit(audit_id)
        snapshot = self._required_snapshot(audit_id)
        validate_snapshot_integrity(snapshot)
        existing = self._orchestration.orchestration(audit_id)
        if existing is not None and existing.get("crawl_job_id"):
            return self.status(audit_id)
        if audit["lifecycle"] != AuditLifecycle.READY.value:
            raise SiteAuditOrchestrationError(
                "site_audit_not_ready", "Only a ready Site Audit may be submitted."
            )
        self._orchestration.initialize(audit_id, snapshot)
        audit = self._repository.transition(
            audit_id, AuditLifecycle.QUEUED, expected_revision=int(audit["revision"])
        )
        submitted = await self._crawl.submit(_crawl_request(audit, snapshot))
        status = submitted.status
        if status is None or status.job_id is None or status.run_id is None:
            self._orchestration.set_state(
                audit_id,
                OrchestrationState.FAILED,
                failure_code="site_audit_crawl_submission_failed",
                failure_explanation="The crawl could not be submitted.",
            )
            self._repository.transition(
                audit_id,
                AuditLifecycle.FAILED,
                expected_revision=int(audit["revision"]),
                failure_code="site_audit_crawl_submission_failed",
                failure_explanation="The crawl could not be submitted.",
            )
            raise SiteAuditOrchestrationError(
                "site_audit_crawl_submission_failed", "The crawl could not be submitted."
            )
        self._orchestration.attach_crawl(audit_id, status.job_id, status.run_id)
        return self.status(audit_id)

    async def reconcile(self, audit_id: str) -> dict[str, Any]:  # noqa: PLR0911
        parent = self._required_orchestration(audit_id)
        if parent["state"] in {
            OrchestrationState.COMPLETED.value,
            OrchestrationState.COMPLETED_WITH_WARNINGS.value,
            OrchestrationState.PARTIALLY_COMPLETED.value,
            OrchestrationState.CANCELLED.value,
            OrchestrationState.FAILED.value,
        } and not self._projection_repair_required(audit_id, parent):
            return self.status(audit_id)
        job_id = parent.get("crawl_job_id")
        if not isinstance(job_id, str):
            return self.status(audit_id)
        crawl_status = await self._crawl.status(job_id)
        if parent["cancellation_requested"]:
            await self._crawl.cancel(job_id)
            if crawl_status.terminal:
                self._orchestration.update_stage(
                    audit_id,
                    SiteAuditStage.CRAWL,
                    StageState.CANCELLED
                    if crawl_status.state in {"cancelled", "cancellation_requested"}
                    else StageState.COMPLETED,
                    source_count=crawl_status.urls_discovered,
                    projected_count=crawl_status.urls_fetched,
                )
                self._finish(audit_id, OrchestrationState.CANCELLED)
            return self.status(audit_id)
        if not crawl_status.terminal:
            self._start_parent_and_crawl(audit_id)
            return self.status(audit_id)
        if crawl_status.state in {"cancelled", "cancellation_requested"}:
            self._orchestration.update_stage(audit_id, SiteAuditStage.CRAWL, StageState.CANCELLED)
            self._finish(audit_id, OrchestrationState.CANCELLED)
            return self.status(audit_id)
        result = await self._crawl.result(job_id)
        if result.outcome is not ApplicationOutcomeCode.FOUND or result.run_lifecycle in {
            "failed",
            None,
        }:
            self._orchestration.update_stage(
                audit_id,
                SiteAuditStage.CRAWL,
                StageState.FAILED,
                failure_code="site_audit_crawl_failed",
                failure_explanation="The associated crawl failed.",
            )
            self._finish(
                audit_id,
                OrchestrationState.FAILED,
                failure_code="site_audit_crawl_failed",
                explanation="The associated crawl failed.",
            )
            return self.status(audit_id)
        self._start_parent_and_crawl(audit_id)
        self._orchestration.update_stage(
            audit_id,
            SiteAuditStage.CRAWL,
            StageState.PARTIAL
            if result.run_lifecycle in {"partially_completed", "completed_with_warnings"}
            else StageState.COMPLETED,
            source_count=dict(result.crawl_counts).get("unique_urls_discovered", 0),
            projected_count=dict(result.crawl_counts).get("urls_fetched", 0),
        )
        await self._project(audit_id, result.run_id or str(parent["crawl_run_id"]), job_id)
        return self.status(audit_id)

    async def reconcile_pending(self, *, maximum_parents: int = 25) -> int:
        """Run one bounded worker-owned parent scan; manual reconcile is recovery-only."""
        bounded = max(1, min(maximum_parents, 100))
        self._orchestration.recover_expired(limit=bounded)
        reconciled = 0
        for audit_id in self._orchestration.reconcilable(limit=bounded):
            try:
                await self.reconcile(audit_id)
                reconciled += 1
            except Exception:  # noqa: BLE001 - durable boundary records only safe failure.
                self._orchestration.record_reconciliation_failure(audit_id)
        return reconciled

    async def cancel(self, audit_id: str) -> dict[str, Any]:
        parent = self._orchestration.request_cancellation(audit_id)
        if parent.get("crawl_job_id"):
            await self._crawl.cancel(str(parent["crawl_job_id"]))
        audit = self._required_audit(audit_id)
        if audit["lifecycle"] in {AuditLifecycle.QUEUED.value, AuditLifecycle.RUNNING.value}:
            self._repository.transition(
                audit_id,
                AuditLifecycle.CANCEL_REQUESTED,
                expected_revision=int(audit["revision"]),
            )
        return self.status(audit_id)

    async def retry(self, audit_id: str) -> dict[str, Any]:
        self._orchestration.retry(audit_id)
        audit = self._required_audit(audit_id)
        if audit["lifecycle"] in {
            AuditLifecycle.RUNNING.value,
            AuditLifecycle.FAILED.value,
        }:
            audit = self._repository.transition(
                audit_id,
                AuditLifecycle.RECOVERY_REQUIRED,
                expected_revision=int(audit["revision"]),
            )
        if audit["lifecycle"] == AuditLifecycle.RECOVERY_REQUIRED.value:
            self._repository.transition(
                audit_id,
                AuditLifecycle.QUEUED,
                expected_revision=int(audit["revision"]),
            )
        return await self.reconcile(audit_id)

    def status(self, audit_id: str) -> dict[str, Any]:
        audit = self._required_audit(audit_id)
        parent = self._orchestration.orchestration(audit_id)
        return {
            "audit": audit,
            "orchestration": parent,
            "stages": self._orchestration.stages(audit_id) if parent else (),
            "modules": self._repository.module_statuses(audit_id),
            "specialists": self._orchestration.specialists(audit_id) if parent else (),
            "orchestration_version": SITE_AUDIT_ORCHESTRATION_VERSION,
        }

    def summary(self, audit_id: str) -> dict[str, Any]:
        value = self._repository.summary(audit_id)
        if value is None:
            raise SiteAuditOrchestrationError(
                "site_audit_projection_unavailable", "The Site Audit summary is unavailable."
            )
        return value

    def pages(self, audit_id: str, *, offset: int = 0, page_size: int = 50) -> dict[str, Any]:
        items, total = self._repository.urls(audit_id, offset=offset, page_size=page_size)
        return {"items": items, "offset": offset, "page_size": page_size, "total": total}

    def issues(self, audit_id: str, *, offset: int = 0, page_size: int = 50) -> dict[str, Any]:
        items = self._repository.issue_groups(audit_id, offset=offset, page_size=page_size)
        return {"items": items, "offset": offset, "page_size": page_size}

    def rules(self, audit_id: str, *, offset: int = 0, page_size: int = 50) -> dict[str, Any]:
        return {
            "items": self._repository.rule_matches(audit_id, offset=offset, page_size=page_size),
            "offset": offset,
            "page_size": page_size,
        }

    def artifact_associations(self, audit_id: str) -> tuple[dict[str, Any], ...]:
        return self._repository.artifact_associations(audit_id)

    def rebuild_summary(self, audit_id: str) -> dict[str, Any]:
        return self._repository.rebuild_summary(audit_id)

    async def _project(self, audit_id: str, run_id: str, job_id: str) -> None:
        pages = self._all_page_evidence(run_id)
        if not pages:
            self._orchestration.update_stage(
                audit_id,
                SiteAuditStage.INGEST,
                StageState.FAILED,
                failure_code="site_audit_evidence_unavailable",
                failure_explanation="Durable crawl page evidence is unavailable.",
            )
            self._finish(
                audit_id,
                OrchestrationState.FAILED,
                failure_code="site_audit_evidence_unavailable",
                explanation="Durable crawl page evidence is unavailable.",
            )
            return
        recommendations = await self._all_recommendations(job_id)
        self._ingest(audit_id, pages, recommendations)
        self._ingest_link_discoveries(audit_id, run_id)
        specialist_evidence = await self._resolve_specialists(audit_id, run_id)
        self._project_sitemap_inventory(audit_id, specialist_evidence)
        self._evaluate_rules(audit_id)
        self._classify_populations(audit_id)
        waiting = self._project_modules(
            audit_id, run_id, pages, recommendations, specialist_evidence
        )
        if waiting:
            return
        self._aggregate_issues(audit_id, pages)
        summary = self._repository.rebuild_summary(audit_id)
        counts = self._page_evidence.base_evidence_counts(run_id)
        summary = self._repository.set_specialist_summaries(
            audit_id,
            image_summary={
                "availability": "base_evidence",
                "occurrences": counts["image_occurrences"],
                "missing_alt": counts["images_missing_alt"],
                "empty_alt": counts["images_empty_alt"],
            },
            structured_data_summary={
                "availability": "base_evidence",
                "blocks": counts["structured_data_blocks"],
                "invalid": counts["structured_data_invalid"],
            },
        )
        self._orchestration.update_stage(
            audit_id, SiteAuditStage.SUMMARY, StageState.COMPLETED, projected_count=1
        )
        self._generate_artifacts(audit_id, pages, summary, job_id, run_id)
        stages = self._orchestration.stages(audit_id)
        required_failed = any(
            item["required"] and item["state"] in {"failed", "blocked", "unavailable"}
            for item in stages
        )
        partial = any(item["state"] == "partial" for item in stages)
        optional_problem = any(
            not item["required"] and item["state"] in {"partial", "failed", "unavailable"}
            for item in stages
        )
        final = (
            OrchestrationState.FAILED
            if required_failed
            else OrchestrationState.PARTIALLY_COMPLETED
            if partial
            else OrchestrationState.COMPLETED_WITH_WARNINGS
            if optional_problem
            else OrchestrationState.COMPLETED
        )
        self._finish(audit_id, final)

    def _ingest(
        self,
        audit_id: str,
        pages: tuple[PageEvidenceListItem, ...],
        recommendations: dict[str, str],
    ) -> None:
        snapshot = self._required_snapshot(audit_id)
        self._orchestration.update_stage(
            audit_id, SiteAuditStage.INGEST, StageState.RUNNING, lease_owner="reconciler"
        )
        for index, page in enumerate(pages):
            normalized_url = _inventory_url(snapshot, page.requested_url)
            existing = self._orchestration.find_url(audit_id, normalized_url)
            if existing is None:
                url_id = stable_identifier(audit_id, normalized_url)
                values = _url_values(page, recommendations.get(page.requested_url))
                existing = self._repository.add_url(
                    audit_id,
                    url_id,
                    sequence=page.discovery_sequence,
                    original_url=page.requested_url,
                    requested_url=page.requested_url,
                    normalized_url=normalized_url,
                    values=values,
                )
            url_id = str(existing["url_id"])
            try:
                self._repository.add_discovery(
                    audit_id,
                    url_id,
                    {
                        "discovery_id": stable_identifier(
                            audit_id, url_id, page.evidence_id, "crawl"
                        ),
                        "sequence": index,
                        "source_type": "crawl_evidence",
                        "source_evidence_id": page.evidence_id,
                        "original_observed_url": page.requested_url,
                        "relationship": {"crawl_depth": page.crawl_depth},
                    },
                )
            except SiteAuditPersistenceError as error:
                if error.code != "site_audit_discovery_conflict":
                    raise
            self._orchestration.update_stage(
                audit_id,
                SiteAuditStage.INGEST,
                StageState.RUNNING,
                checkpoint=index + 1,
                source_count=len(pages),
                projected_count=index + 1,
                lease_owner="reconciler",
            )
        self._orchestration.update_stage(
            audit_id,
            SiteAuditStage.INGEST,
            StageState.COMPLETED,
            checkpoint=len(pages),
            source_count=len(pages),
            projected_count=len(pages),
        )

    def _evaluate_rules(self, audit_id: str) -> None:
        snapshot = self._required_snapshot(audit_id)
        rules = tuple(_snapshot_rule(item) for item in snapshot.get("rules", ()))
        stored = tuple(snapshot.get("rules", ()))
        self._orchestration.update_stage(
            audit_id, SiteAuditStage.GOVERNANCE, StageState.RUNNING, lease_owner="reconciler"
        )
        urls = self._all_urls(audit_id)
        for index, url in enumerate(urls):
            matched = [
                (rule, record)
                for rule, record in zip(rules, stored, strict=True)
                if rule.enabled and rule_matches(rule, str(url["original_url"]))
            ]
            decisions = _governance_decisions(matched)
            if url.get("failure_code") == "scope_denied":
                decisions["discovery_decision"] = "scope_denied"
            elif (
                decisions["discovery_decision"] == "exclude_from_discovery"
                and url.get("fetch_state") == "not_fetched"
            ):
                decisions["enqueued_state"] = "not_enqueued"
            self._orchestration.update_url(audit_id, str(url["url_id"]), decisions)
            by_layer: dict[str, list[tuple[UrlGovernanceRule, dict[str, Any]]]] = {}
            for rule, record in matched:
                by_layer.setdefault(str(record["decision_layer"]), []).append((rule, record))
            for layer, matches in by_layer.items():
                ordered = sorted(
                    matches,
                    key=lambda item: (
                        -int(item[1]["priority"]),
                        -int(item[1]["specificity"]),
                        str(item[1]["stable_rule_id"]),
                    ),
                )
                conflict = len({item[0].action.value for item in ordered}) > 1
                for position, (rule, record) in enumerate(ordered):
                    match_id = stable_identifier(
                        audit_id, url["url_id"], record["snapshot_rule_id"], layer
                    )
                    try:
                        self._repository.add_rule_match(
                            audit_id,
                            str(url["url_id"]),
                            {
                                "match_id": match_id,
                                "snapshot_rule_id": record["snapshot_rule_id"],
                                "decision_layer": layer,
                                "primary_rule": position == 0 and not conflict,
                                "contributed": True,
                                "specificity": record["specificity"],
                                "priority": record["priority"],
                                "precedence_key": f"{position:04d}:{record['stable_rule_id']}",
                                "conflict_code": ("site_audit_rule_conflict" if conflict else None),
                                "reason": rule.reason,
                                "matched_original_url": url["original_url"],
                                "matched_normalized_url": url["normalized_url"],
                            },
                        )
                    except SiteAuditPersistenceError as error:
                        if error.code != "site_audit_rule_match_conflict_invalid":
                            raise
            self._orchestration.update_stage(
                audit_id,
                SiteAuditStage.GOVERNANCE,
                StageState.RUNNING,
                checkpoint=index + 1,
                source_count=len(urls),
                projected_count=index + 1,
                lease_owner="reconciler",
            )
        self._orchestration.update_stage(
            audit_id,
            SiteAuditStage.GOVERNANCE,
            StageState.COMPLETED,
            checkpoint=len(urls),
            source_count=len(urls),
            projected_count=len(urls),
        )

    def _ingest_link_discoveries(self, audit_id: str, run_id: str) -> None:
        snapshot = self._required_snapshot(audit_id)
        offset = 0
        retained_urls = self._all_urls(audit_id)
        next_sequence = max((int(item["sequence"]) for item in retained_urls), default=-1) + 1
        discovery_sequence = self._repository.next_discovery_sequence(audit_id)
        while True:
            links = self._page_evidence.list_link_discoveries(
                run_id, offset=offset, limit=_LINK_DISCOVERY_PAGE_SIZE
            )
            for link in links:
                resolved = link.get("resolved_url")
                if link.get("link_type") != "http" or not isinstance(resolved, str):
                    continue
                try:
                    normalized_url = _inventory_url(snapshot, resolved)
                except ValueError:
                    continue
                existing = self._orchestration.find_url(audit_id, normalized_url)
                if existing is None:
                    url_id = stable_identifier(audit_id, normalized_url)
                    existing = self._repository.add_url(
                        audit_id,
                        url_id,
                        sequence=next_sequence,
                        original_url=resolved,
                        requested_url=resolved,
                        normalized_url=normalized_url,
                        values={
                            "crawl_depth": cast("int", link["source_crawl_depth"]) + 1,
                            "failure_code": (
                                "scope_denied" if link.get("in_scope") is False else None
                            ),
                            "discovery_decision": (
                                "scope_denied" if link.get("in_scope") is False else "enqueue"
                            ),
                        },
                    )
                    next_sequence += 1
                url_id = str(existing["url_id"])
                try:
                    self._repository.add_discovery(
                        audit_id,
                        url_id,
                        {
                            "discovery_id": stable_identifier(
                                audit_id, url_id, str(link["link_id"]), "link"
                            ),
                            "sequence": discovery_sequence,
                            "source_type": "page_link",
                            "source_url": link["source_final_url"] or link["source_requested_url"],
                            "source_evidence_id": link["source_evidence_id"],
                            "discovered_at": link["created_at"],
                            "original_observed_url": link.get("raw_href") or resolved,
                            "relationship": {
                                "source_url": link["source_final_url"]
                                or link["source_requested_url"],
                                "resolved_url": resolved,
                                "nofollow": bool(link["nofollow"]),
                                "scope_reason_code": link.get("scope_reason_code"),
                                "evidence_version": link["evidence_version"],
                            },
                        },
                    )
                except SiteAuditPersistenceError as error:
                    if error.code != "site_audit_discovery_conflict":
                        raise
                discovery_sequence += 1
            if len(links) < _LINK_DISCOVERY_PAGE_SIZE:
                return
            offset += len(links)

    def _classify_populations(self, audit_id: str) -> None:
        self._orchestration.update_stage(
            audit_id, SiteAuditStage.POPULATIONS, StageState.RUNNING, lease_owner="reconciler"
        )
        urls = self._all_urls(audit_id)
        for index, url in enumerate(urls):
            populations = _populations(url)
            self._repository.set_populations(audit_id, str(url["url_id"]), populations)
            self._orchestration.update_stage(
                audit_id,
                SiteAuditStage.POPULATIONS,
                StageState.RUNNING,
                checkpoint=index + 1,
                source_count=len(urls),
                projected_count=index + 1,
                lease_owner="reconciler",
            )
        self._orchestration.update_stage(
            audit_id,
            SiteAuditStage.POPULATIONS,
            StageState.COMPLETED,
            checkpoint=len(urls),
            source_count=len(urls),
            projected_count=len(urls),
        )

    async def _resolve_specialists(
        self, audit_id: str, run_id: str
    ) -> dict[SiteAuditStage, SpecialistEvidence]:
        if self._specialists is None:
            return {}
        snapshot = self._required_snapshot(audit_id)
        configuration = snapshot["configuration"]
        configured = configuration.get("specialist_audit_ids", {})
        if not isinstance(configured, dict):
            configured = {}
        launch_value = configuration.get("launch_specialists", ())
        launch = (
            {stage.value for stage in _SPECIALIST_STAGES}
            if launch_value is True
            else {str(item) for item in launch_value}
            if isinstance(launch_value, (list, tuple))
            else set()
        )
        if configuration.get("existing_sitemap_mode", "new_or_reuse") != "unavailable":
            launch.add(SiteAuditStage.EXISTING_SITEMAP.value)
        associated = {
            str(item["module"]): item for item in self._orchestration.specialists(audit_id)
        }
        audit = self._required_audit(audit_id)
        approved_hosts = tuple(str(item) for item in configuration.get("approved_hosts", ()))
        result: dict[SiteAuditStage, SpecialistEvidence] = {}
        for stage in _SPECIALIST_STAGES:
            result[stage] = await self._specialists.resolve(
                SpecialistRequest(
                    module=stage,
                    run_id=run_id,
                    seed_url=str(audit["normalized_seed_url"]),
                    approved_hosts=approved_hosts,
                    associated=associated.get(stage.value),
                    configured_audit_id=(
                        str(configured[stage.value]) if configured.get(stage.value) else None
                    ),
                    allow_launch=stage.value in launch,
                )
            )
        return result

    def _project_sitemap_inventory(
        self,
        audit_id: str,
        specialists: dict[SiteAuditStage, SpecialistEvidence],
    ) -> None:
        evidence = specialists.get(SiteAuditStage.EXISTING_SITEMAP)
        if evidence is None or evidence.eligibility_state != "eligible":
            return
        snapshot = self._required_snapshot(audit_id)
        existing_urls = self._all_urls(audit_id)
        next_sequence = max((int(item["sequence"]) for item in existing_urls), default=-1) + 1
        seen: set[str] = set()
        discovery_sequence = self._repository.next_discovery_sequence(audit_id)
        for entry in evidence.entries:
            location = entry.get("normalized_identity")
            if (
                not isinstance(location, str)
                or entry.get("is_child_reference") is True
                or entry.get("duplicate") is True
                or location in seen
            ):
                continue
            seen.add(location)
            try:
                normalized_url = _inventory_url(snapshot, location)
            except ValueError:
                continue
            existing = self._orchestration.find_url(audit_id, normalized_url)
            if existing is None:
                url_id = stable_identifier(audit_id, normalized_url)
                existing = self._repository.add_url(
                    audit_id,
                    url_id,
                    sequence=next_sequence,
                    original_url=location,
                    requested_url=location,
                    normalized_url=normalized_url,
                    values={
                        "existing_sitemap_state": "present",
                        "discovery_decision": (
                            "enqueue" if entry.get("in_scope") is True else "scope_denied"
                        ),
                        "failure_code": (None if entry.get("in_scope") is True else "scope_denied"),
                    },
                )
                next_sequence += 1
            else:
                self._orchestration.update_url(
                    audit_id, str(existing["url_id"]), {"existing_sitemap_state": "present"}
                )
            try:
                self._repository.add_discovery(
                    audit_id,
                    str(existing["url_id"]),
                    {
                        "discovery_id": stable_identifier(
                            audit_id, existing["url_id"], entry.get("entry_id"), "sitemap"
                        ),
                        "sequence": discovery_sequence,
                        "source_type": "sitemap_entry",
                        "source_evidence_id": entry.get("document_id"),
                        "original_observed_url": entry.get("raw_location") or location,
                        "relationship": {
                            "specialist_audit_id": evidence.specialist_audit_id,
                            "validation_state": entry.get("validation_state"),
                            "in_scope": entry.get("in_scope"),
                        },
                    },
                )
            except SiteAuditPersistenceError as error:
                if error.code != "site_audit_discovery_conflict":
                    raise
            discovery_sequence += 1

    def _project_modules(
        self,
        audit_id: str,
        run_id: str,
        pages: tuple[PageEvidenceListItem, ...],
        recommendations: dict[str, str],
        specialists: dict[SiteAuditStage, SpecialistEvidence],
    ) -> bool:
        counts = self._page_evidence.base_evidence_counts(run_id)
        simple = {
            SiteAuditStage.STATUS_REDIRECTS: len(pages),
            SiteAuditStage.ROBOTS_INDEXABILITY: len(pages),
            SiteAuditStage.CANONICALS: len(pages),
            SiteAuditStage.SITEMAP_RECOMMENDATIONS: len(recommendations),
        }
        existing_stages = {item["stage"] for item in self._orchestration.stages(audit_id)}
        for stage, count in simple.items():
            if stage.value not in existing_stages:
                continue
            state = StageState.COMPLETED
            if stage is SiteAuditStage.SITEMAP_RECOMMENDATIONS and len(recommendations) < len(
                pages
            ):
                state = StageState.PARTIAL
            if stage is SiteAuditStage.METADATA and any(
                page.evidence_state is not PageEvidenceState.COMPLETE for page in pages
            ):
                state = StageState.PARTIAL
            self._orchestration.update_stage(
                audit_id,
                stage,
                state,
                source_count=len(pages),
                projected_count=count,
                failure_code=(
                    "site_audit_specialist_unavailable" if state is StageState.UNAVAILABLE else None
                ),
            )
            completeness = {
                StageState.COMPLETED: "complete",
                StageState.PARTIAL: "partial",
                StageState.UNAVAILABLE: "unavailable",
            }[state]
            self._repository.upsert_module_status(
                audit_id,
                {
                    "module": stage.value,
                    "execution_source": "base_evidence",
                    "lifecycle": state.value,
                    "completeness": completeness,
                    "partial": state is StageState.PARTIAL,
                    "result_count": count,
                    "failure_code": (
                        "site_audit_specialist_unavailable"
                        if state is StageState.UNAVAILABLE
                        else None
                    ),
                },
            )
            self._orchestration.upsert_specialist(
                audit_id,
                {
                    "module": stage.value,
                    "source_run_id": run_id,
                    "execution_source": "base_evidence",
                    "eligibility_state": "eligible",
                    "eligibility_reason": "same_crawl_run",
                    "freshness_state": "current",
                    "partial": state is StageState.PARTIAL,
                    "evidence_count": count,
                },
            )
        waiting = False
        base_counts = {
            SiteAuditStage.METADATA: sum(page.parsed_as_html for page in pages),
            SiteAuditStage.BROKEN_LINKS: counts["link_occurrences"],
            SiteAuditStage.INTERNAL_LINKS: counts["link_occurrences"],
            SiteAuditStage.IMAGES: counts["image_occurrences"],
            SiteAuditStage.STRUCTURED_DATA: counts["structured_data_blocks"],
        }
        base_supported = {
            SiteAuditStage.METADATA,
            SiteAuditStage.IMAGES,
            SiteAuditStage.STRUCTURED_DATA,
        }
        for stage in _SPECIALIST_STAGES:
            if stage.value not in existing_stages:
                continue
            evidence = specialists.get(stage)
            if evidence is None or evidence.eligibility_state != "eligible":
                if stage in base_supported:
                    evidence = SpecialistEvidence(
                        stage,
                        None,
                        "base_evidence",
                        "eligible",
                        "same_crawl_run",
                        "current",
                        "completed",
                        any(
                            page.evidence_state is not PageEvidenceState.COMPLETE for page in pages
                        ),
                        base_counts[stage],
                    )
                else:
                    evidence = evidence or SpecialistEvidence(
                        module=stage,
                        specialist_audit_id=None,
                        execution_source="unavailable",
                        eligibility_state="unavailable",
                        eligibility_reason="no_compatible_specialist_audit",
                        freshness_state="unknown",
                        lifecycle_state="unavailable",
                        partial=False,
                        evidence_count=0,
                    )
            state = _specialist_stage_state(evidence)
            waiting = waiting or state is StageState.RUNNING
            self._orchestration.update_stage(
                audit_id,
                stage,
                state,
                source_count=evidence.evidence_count,
                projected_count=evidence.evidence_count,
                failure_code=(
                    None
                    if state in {StageState.COMPLETED, StageState.PARTIAL, StageState.RUNNING}
                    else "site_audit_specialist_unavailable"
                    if state is StageState.UNAVAILABLE
                    else "site_audit_specialist_failed"
                ),
                failure_explanation=(
                    None
                    if state in {StageState.COMPLETED, StageState.PARTIAL, StageState.RUNNING}
                    else "No compatible specialist evidence is retained."
                    if state is StageState.UNAVAILABLE
                    else "The associated specialist audit failed."
                ),
                lease_owner="specialist-reconciler" if state is StageState.RUNNING else None,
            )
            self._repository.upsert_module_status(
                audit_id,
                {
                    "module": stage.value,
                    "execution_source": evidence.execution_source,
                    "lifecycle": state.value,
                    "completeness": (
                        "complete"
                        if state is StageState.COMPLETED
                        else "partial"
                        if state in {StageState.PARTIAL, StageState.RUNNING}
                        else state.value
                    ),
                    "partial": state is StageState.PARTIAL,
                    "result_count": evidence.evidence_count,
                    "failure_code": (
                        "site_audit_specialist_unavailable"
                        if state is StageState.UNAVAILABLE
                        else "site_audit_specialist_failed"
                        if state is StageState.FAILED
                        else None
                    ),
                },
            )
            self._orchestration.upsert_specialist(
                audit_id,
                {
                    "module": stage.value,
                    "specialist_audit_id": evidence.specialist_audit_id,
                    "source_run_id": run_id,
                    "execution_source": evidence.execution_source,
                    "eligibility_state": evidence.eligibility_state,
                    "eligibility_reason": evidence.eligibility_reason,
                    "freshness_state": evidence.freshness_state,
                    "partial": evidence.partial,
                    "evidence_count": evidence.evidence_count,
                },
            )
        return waiting

    def _aggregate_issues(self, audit_id: str, pages: tuple[PageEvidenceListItem, ...]) -> None:
        self._orchestration.update_stage(
            audit_id,
            SiteAuditStage.ISSUE_AGGREGATION,
            StageState.RUNNING,
            lease_owner="reconciler",
        )
        definitions = _finding_definitions(pages)
        urls_by_evidence = {
            str(item["evidence_id"]): item
            for item in self._all_urls(audit_id)
            if item.get("evidence_id")
        }
        grouped: dict[str, list[tuple[str, str]]] = {}
        for page, code, category, severity, explanation, impacts in definitions:
            url = urls_by_evidence.get(page.evidence_id)
            if url is None:
                continue
            finding_id = stable_identifier(audit_id, url["url_id"], code)
            if self._repository.finding(audit_id, finding_id) is None:
                self._repository.add_finding(
                    audit_id,
                    {
                        "finding_id": finding_id,
                        "url_id": url["url_id"],
                        "module": category,
                        "category": category,
                        "code": code,
                        "severity": severity,
                        "explanation": explanation,
                        "evidence_reference": page.evidence_id,
                        **impacts,
                    },
                )
            grouped.setdefault(code, []).append((finding_id, page.requested_url))
        for code, members in sorted(grouped.items()):
            finding = self._repository.finding(audit_id, members[0][0])
            if finding is None:
                continue
            group_id = stable_identifier(audit_id, SITE_AUDIT_ISSUE_DEFINITION_VERSION, code)
            inputs = PriorityInputs(
                security=code.startswith("security_"),
                severity=str(finding["severity"]),
                indexability_impact=bool(finding["indexability_impact"]),
                sitemap_impact=bool(finding["sitemap_impact"]),
                affected_count=len(members),
                pattern_state=(
                    "candidate" if len(members) >= _PATTERN_CANDIDATE_MINIMUM else "none"
                ),
            )
            self._repository.upsert_issue_group(
                audit_id,
                {
                    "group_id": group_id,
                    "category": finding["category"],
                    "code": code,
                    "remediation_key": code,
                    "applicable_population": "discovered",
                    "title": code.replace("_", " ").title(),
                    "explanation": finding["explanation"],
                    "severity": finding["severity"],
                    "affected_url_count": len(members),
                    "pattern_state": inputs.pattern_state,
                    "sitemap_impact": inputs.sitemap_impact,
                    "metadata_impact": bool(finding["metadata_impact"]),
                    "indexability_impact": inputs.indexability_impact,
                    "confidence": "high",
                    "determinacy": "determinate",
                    "priority_band": finding["severity"],
                    "priority_key": priority_key(inputs, code=code, group_id=group_id),
                    "priority_explanation": priority_explanation(inputs),
                    "recommended_action": _recommended_action(code),
                    "sample_urls": [url for _, url in members[:100]],
                },
            )
            for sequence, (finding_id, _url) in enumerate(members):
                if not self._repository.issue_membership_exists(group_id, finding_id):
                    self._repository.add_issue_membership(
                        audit_id,
                        group_id,
                        finding_id,
                        sequence=sequence,
                        reason="deterministic_issue_code",
                    )
        self._orchestration.update_stage(
            audit_id,
            SiteAuditStage.ISSUE_AGGREGATION,
            StageState.COMPLETED,
            source_count=len(definitions),
            projected_count=len(grouped),
        )

    def _generate_artifacts(
        self,
        audit_id: str,
        pages: tuple[PageEvidenceListItem, ...],
        summary: dict[str, Any],
        job_id: str,
        run_id: str,
    ) -> None:
        self._orchestration.update_stage(
            audit_id, SiteAuditStage.ARTIFACTS, StageState.RUNNING, lease_owner="reconciler"
        )
        audit = self._required_audit(audit_id)
        snapshot = self._required_snapshot(audit_id)
        urls = self._all_urls(audit_id)
        findings = self._all_findings(audit_id)
        groups = self._all_issue_groups(audit_id)
        matches = self._all_rule_matches(audit_id)
        safe_evidence = {
            page.evidence_id: self._page_evidence.get_safe_page_evidence(page.evidence_id) or {}
            for page in pages
        }
        existing = {
            item["purpose"]: item for item in self._repository.artifact_associations(audit_id)
        }
        generated = generate_site_audit_artifacts(
            audit=audit,
            snapshot=snapshot,
            summary=summary,
            urls=urls,
            findings=findings,
            issue_groups=groups,
            rule_matches=matches,
            evidence=safe_evidence,
        )
        for item in generated:
            if item.purpose.value in existing:
                continue
            record = self._artifacts.store_bytes(
                job_id=job_id,
                run_id=run_id,
                artifact_type=item.artifact_type,
                filename=item.filename,
                content=item.content,
            )
            self._repository.associate_artifact(
                audit_id,
                record.artifact_id,
                purpose=item.purpose.value,
                schema_version=item.schema_version,
                completeness="partial" if item.truncated or audit["partial"] else "complete",
                row_count=item.row_count,
                truncated=item.truncated,
            )
        self._orchestration.update_stage(
            audit_id,
            SiteAuditStage.ARTIFACTS,
            StageState.COMPLETED,
            source_count=len(generated),
            projected_count=len(self._repository.artifact_associations(audit_id)),
        )

    def _all_page_evidence(self, run_id: str) -> tuple[PageEvidenceListItem, ...]:
        items: list[PageEvidenceListItem] = []
        cursor: str | None = None
        while True:
            page = self._page_evidence.list_pages(
                PageEvidenceFilters(run_id=run_id), page_size=200, cursor=cursor
            )
            items.extend(page.items)
            cursor = page.next_cursor
            if cursor is None:
                return tuple(items)

    async def _all_recommendations(self, job_id: str) -> dict[str, str]:
        result: dict[str, str] = {}
        offset = 0
        while True:
            page = await self._crawl.recommendations(job_id, offset=offset, limit=500)
            for item in page.items:
                result[item.requested_url] = item.state
            if not page.has_more or not page.items:
                return result
            offset += len(page.items)

    def _all_urls(self, audit_id: str) -> tuple[dict[str, Any], ...]:
        items: list[dict[str, Any]] = []
        offset = 0
        while True:
            page, total = self._repository.urls(
                audit_id, page_size=_PERSISTENCE_PAGE_SIZE, offset=offset
            )
            items.extend(page)
            offset += len(page)
            if offset >= total or not page:
                return tuple(items)

    def _all_findings(self, audit_id: str) -> tuple[dict[str, Any], ...]:
        return _paged(
            lambda offset: self._repository.findings(
                audit_id, page_size=_PERSISTENCE_PAGE_SIZE, offset=offset
            )
        )

    def _all_issue_groups(self, audit_id: str) -> tuple[dict[str, Any], ...]:
        return _paged(
            lambda offset: self._repository.issue_groups(
                audit_id, page_size=_PERSISTENCE_PAGE_SIZE, offset=offset
            )
        )

    def _all_rule_matches(self, audit_id: str) -> tuple[dict[str, Any], ...]:
        return _paged(
            lambda offset: self._repository.rule_matches(
                audit_id, page_size=_PERSISTENCE_PAGE_SIZE, offset=offset
            )
        )

    def _start_parent_and_crawl(self, audit_id: str) -> None:
        parent = self._required_orchestration(audit_id)
        if parent["state"] in {
            OrchestrationState.QUEUED.value,
            OrchestrationState.RECOVERY_REQUIRED.value,
        }:
            self._orchestration.set_state(
                audit_id, OrchestrationState.RUNNING, current_stage=SiteAuditStage.CRAWL
            )
        stage = next(
            item
            for item in self._orchestration.stages(audit_id)
            if item["stage"] == SiteAuditStage.CRAWL.value
        )
        if stage["state"] in {StageState.PENDING.value, StageState.RUNNING.value}:
            self._orchestration.update_stage(
                audit_id,
                SiteAuditStage.CRAWL,
                StageState.RUNNING,
                lease_owner="durable-crawl-worker",
                lease_seconds=300,
            )
        audit = self._required_audit(audit_id)
        if audit["lifecycle"] == AuditLifecycle.QUEUED.value:
            self._repository.transition(
                audit_id, AuditLifecycle.RUNNING, expected_revision=int(audit["revision"])
            )

    def _finish(
        self,
        audit_id: str,
        state: OrchestrationState,
        *,
        failure_code: str | None = None,
        explanation: str | None = None,
    ) -> None:
        self._orchestration.set_state(
            audit_id,
            state,
            failure_code=failure_code,
            failure_explanation=explanation,
        )
        lifecycle = AuditLifecycle(state.value)
        audit = self._required_audit(audit_id)
        stages = self._orchestration.stages(audit_id)
        partial = state in {
            OrchestrationState.PARTIALLY_COMPLETED,
            OrchestrationState.COMPLETED_WITH_WARNINGS,
        }
        self._repository.set_completeness(
            audit_id,
            population="partial"
            if partial
            else "failed"
            if state is OrchestrationState.FAILED
            else "complete",
            modules=(
                "failed"
                if state is OrchestrationState.FAILED
                else "partial"
                if any(item["state"] in {"partial", "unavailable", "failed"} for item in stages)
                else "complete"
            ),
            partial=partial,
        )
        audit = self._required_audit(audit_id)
        if audit["lifecycle"] in {
            AuditLifecycle.RUNNING.value,
            AuditLifecycle.CANCEL_REQUESTED.value,
        }:
            self._repository.transition(
                audit_id,
                lifecycle,
                expected_revision=int(audit["revision"]),
                failure_code=failure_code,
                failure_explanation=explanation,
            )

    def _required_audit(self, audit_id: str) -> dict[str, Any]:
        value = self._repository.audit(audit_id)
        if value is None:
            raise SiteAuditOrchestrationError(
                "site_audit_not_found", "The Site Audit was not found."
            )
        return value

    def _required_snapshot(self, audit_id: str) -> dict[str, Any]:
        value = self._repository.snapshot(audit_id)
        if value is None:
            raise SiteAuditOrchestrationError(
                "site_audit_snapshot_missing", "The immutable Site Audit snapshot is unavailable."
            )
        return value

    def _required_orchestration(self, audit_id: str) -> dict[str, Any]:
        value = self._orchestration.orchestration(audit_id)
        if value is None:
            raise SiteAuditOrchestrationError(
                "site_audit_orchestration_not_found", "The Site Audit execution was not found."
            )
        return value

    def _projection_repair_required(self, audit_id: str, parent: dict[str, Any]) -> bool:
        if parent["state"] not in {
            OrchestrationState.COMPLETED.value,
            OrchestrationState.COMPLETED_WITH_WARNINGS.value,
            OrchestrationState.PARTIALLY_COMPLETED.value,
        }:
            return False
        return self._repository.summary(audit_id) is None or len(
            self._repository.artifact_associations(audit_id)
        ) < len(ArtifactPurpose)


def _crawl_request(audit: dict[str, Any], snapshot: dict[str, Any]) -> RawApplicationCrawlRequest:
    configuration = snapshot["configuration"]
    limits = configuration.get("crawl_limits", {})
    if not isinstance(limits, dict):
        limits = {}
    scope = configuration.get("scope_policy", {})
    scope_name = scope.get("mode", "exact_host") if isinstance(scope, dict) else str(scope)
    approved = configuration.get("approved_hosts", [])
    return RawApplicationCrawlRequest(
        seed_url=str(audit["normalized_seed_url"]),
        scope_profile=ScopeProfile(scope_name),
        approved_hosts=tuple(str(item) for item in approved),
        crawl_profile=CrawlProfileName(
            str(configuration.get("crawl_profile", CrawlProfileName.STANDARD_CRAWL.value))
        ),
        overrides=CrawlLimitOverrides(
            maximum_urls=_optional_int(limits.get("maximum_urls")),
            maximum_depth=_optional_int(limits.get("maximum_depth")),
            maximum_duration_seconds=_optional_float(limits.get("maximum_duration_seconds")),
            maximum_accepted_bytes=_optional_int(limits.get("maximum_accepted_bytes")),
            maximum_concurrency=_optional_int(limits.get("maximum_concurrency")),
            maximum_queue_size=_optional_int(limits.get("maximum_queue_size")),
            minimum_request_delay_seconds=_optional_float(
                limits.get("minimum_request_delay_seconds")
            ),
            maximum_redirect_hops=_optional_int(limits.get("maximum_redirect_hops")),
            maximum_response_bytes=_optional_int(limits.get("maximum_response_bytes")),
        ),
        recommendation_requested=True,
        xml_generation_requested=True,
        publication_requested=False,
        summary_writing_requested=False,
        caller_label=f"site-audit:{audit['audit_id']}",
        exclusion_rules=_discovery_exclusion_rules(snapshot),
        strip_query_parameters=_tracking_parameters(snapshot),
    )


def _inventory_url(snapshot: dict[str, Any], url: str) -> str:
    return str(
        normalize_governed_url(url, strip_parameters=set(_tracking_parameters(snapshot)))[
            "normalized_url"
        ]
    )


def _tracking_parameters(snapshot: dict[str, Any]) -> tuple[str, ...]:
    configuration = snapshot["configuration"]
    strip: set[str] = set()
    if configuration.get("tracking_parameters_accepted"):
        raw_parameters = configuration.get("tracking_parameters", ())
        if isinstance(raw_parameters, (list, tuple)):
            strip.update(str(item) for item in raw_parameters)
    for record in snapshot.get("rules", ()):
        if (
            isinstance(record, dict)
            and record.get("enabled")
            and record.get("action") == RuleAction.STRIP_QUERY_PARAMETER.value
        ):
            strip.add(str(record["match_value"]).split("=", 1)[0])
    raw_exceptions = configuration.get("tracking_parameter_exceptions", ())
    if isinstance(raw_exceptions, (list, tuple)):
        strip.difference_update(str(item) for item in raw_exceptions)
    return tuple(sorted(strip))


def _discovery_exclusion_rules(
    snapshot: dict[str, Any],
) -> tuple[CrawlExclusionRule, ...]:
    types = {
        RuleMatchType.EXACT_URL.value: ExclusionRuleType.EXACT_URL,
        RuleMatchType.EXACT_PATH.value: ExclusionRuleType.EXACT_PATH,
        RuleMatchType.PATH_STARTS_WITH.value: ExclusionRuleType.PATH_PREFIX,
        RuleMatchType.PATH_CONTAINS.value: ExclusionRuleType.PATH_CONTAINS,
        RuleMatchType.PATH_ENDS_WITH.value: ExclusionRuleType.PATH_SUFFIX,
        RuleMatchType.QUERY_PARAMETER_EXISTS.value: ExclusionRuleType.QUERY_PARAMETER,
        RuleMatchType.QUERY_PARAMETER_EQUALS.value: ExclusionRuleType.QUERY_PARAMETER_EQUALS,
    }
    return tuple(
        CrawlExclusionRule(types[str(record["match_type"])], str(record["match_value"]))
        for record in snapshot.get("rules", ())
        if isinstance(record, dict)
        and record.get("enabled")
        and record.get("action") == RuleAction.EXCLUDE_FROM_DISCOVERY.value
    )


def _url_values(page: PageEvidenceListItem, recommendation: str | None) -> dict[str, Any]:
    canonical = (
        "canonical"
        if page.canonical_presence is MetadataPresence.SINGLE
        and page.canonical_url in {page.requested_url, page.final_url}
        else "missing"
        if page.canonical_presence is MetadataPresence.MISSING
        else "indeterminate"
    )
    indexability = (
        "not_indexable"
        if page.robots_allowed is False
        else "indexable"
        if page.parsed_as_html
        and page.http_status is not None
        and _HTTP_SUCCESS_MINIMUM <= page.http_status < _HTTP_SUCCESS_MAXIMUM
        else "indeterminate"
    )
    return {
        "final_url": page.final_url,
        "enqueued_state": "enqueued",
        "fetch_state": "fetched" if page.fetch_outcome != "skipped" else "not_fetched",
        "parse_state": "parsed_html" if page.parsed_as_html else "not_html",
        "http_status": page.http_status,
        "content_type": page.content_type,
        "fetch_outcome": page.fetch_outcome,
        "redirect_state": "redirected" if page.redirect_count else "not_redirected",
        "robots_state": (
            "allowed"
            if page.robots_allowed is True
            else "blocked"
            if page.robots_allowed is False
            else "unavailable"
        ),
        "indexability_state": indexability,
        "canonical_state": canonical,
        "recommended_sitemap_state": recommendation or "indeterminate",
        "metadata_scoring_decision": "include_in_metadata_scoring",
        "sitemap_policy_decision": "evidence_derived",
        "crawl_depth": page.crawl_depth,
        "partial": page.evidence_state is not PageEvidenceState.COMPLETE,
        "failure_code": page.fetch_outcome
        if page.evidence_state is PageEvidenceState.FETCH_FAILED
        else None,
        "evidence_id": page.evidence_id,
    }


def _snapshot_rule(record: dict[str, Any]) -> UrlGovernanceRule:
    action = RuleAction(str(record["action"]))
    scope = {
        RuleAction.EXCLUDE_FROM_DISCOVERY: RuleScope.DISCOVERY,
        RuleAction.EXCLUDE_FROM_METADATA: RuleScope.METADATA,
        RuleAction.EXCLUDE_FROM_SITEMAP: RuleScope.SITEMAP,
        RuleAction.MARK_FOR_REVIEW: RuleScope(
            "sitemap" if record.get("decision_layer") == "sitemap" else "discovery"
        ),
        RuleAction.STRIP_QUERY_PARAMETER: RuleScope.NORMALIZATION,
    }[action]
    return UrlGovernanceRule(
        rule_id=str(record["stable_rule_id"]),
        name=str(record["stable_rule_id"]),
        description="",
        enabled=bool(record["enabled"]),
        match_type=RuleMatchType(str(record["match_type"])),
        match_value=str(record["match_value"]),
        case_sensitive=True,
        action=action,
        reason=str(record["explanation"]),
        reason_code=str(record["reason_code"]),
        source=RuleSource(str(record["rule_source"])),
        priority=int(record["priority"]),
        scope=scope,
        overrides_rule_ids=tuple(json.loads(str(record["overrides_rule_ids_json"]))),
        created_by="snapshot",
        created_at="1970-01-01T00:00:00+00:00",
        updated_at="1970-01-01T00:00:00+00:00",
    )


def _governance_decisions(  # noqa: C901
    matched: list[tuple[UrlGovernanceRule, dict[str, Any]]],
) -> dict[str, Any]:
    by_layer: dict[str, list[RuleAction]] = {}
    for rule, record in matched:
        by_layer.setdefault(str(record["decision_layer"]), []).append(rule.action)
    discovery = "enqueue"
    metadata = "include_in_metadata_scoring"
    sitemap = "evidence_derived"
    for layer, actions in by_layer.items():
        unique = set(actions)
        if len(unique) > 1:
            if layer == "discovery":
                discovery = "mark_review_before_enqueue"
            elif layer == "metadata":
                metadata = "indeterminate_for_metadata_scoring"
            elif layer == "sitemap":
                sitemap = "review"
            continue
        action = next(iter(unique))
        if action is RuleAction.EXCLUDE_FROM_DISCOVERY:
            discovery = "exclude_from_discovery"
        elif action is RuleAction.EXCLUDE_FROM_METADATA:
            metadata = "exclude_from_metadata_scoring"
        elif action is RuleAction.EXCLUDE_FROM_SITEMAP:
            sitemap = "exclude"
        elif action is RuleAction.MARK_FOR_REVIEW:
            discovery = "mark_review_before_enqueue"
            if layer == "sitemap":
                sitemap = "review"
    return {
        "discovery_decision": discovery,
        "metadata_scoring_decision": metadata,
        "sitemap_policy_decision": sitemap,
    }


def _populations(url: dict[str, Any]) -> tuple[Population, ...]:  # noqa: C901
    values = {Population.DISCOVERED}
    if url["enqueued_state"] == "enqueued":
        values.add(Population.ENQUEUED)
    if url["fetch_state"] == "fetched":
        values.add(Population.FETCHED)
    if url["parse_state"] == "parsed_html":
        values.add(Population.PARSED_HTML)
    if url["indexability_state"] == "indexable":
        values.add(Population.INDEXABLE)
    if url["canonical_state"] == "canonical":
        values.add(Population.CANONICAL)
    if {Population.PARSED_HTML, Population.INDEXABLE, Population.CANONICAL}.issubset(
        values
    ) and url["metadata_scoring_decision"] == "include_in_metadata_scoring":
        values.add(Population.METADATA_SCORING_ELIGIBLE)
    if url["recommended_sitemap_state"] == "include":
        values.add(Population.SITEMAP_ELIGIBLE)
    if url["parse_state"] == "not_html" and url["fetch_state"] == "fetched":
        values.add(Population.RESOURCE)
    if (
        url["discovery_decision"] != "enqueue"
        or url["metadata_scoring_decision"] == "exclude_from_metadata_scoring"
        or url["sitemap_policy_decision"] == "exclude"
    ):
        values.add(Population.EXCLUDED)
    if url["partial"]:
        values.add(Population.PARTIAL)
    if url["failure_code"]:
        values.add(Population.FAILED)
    if url["indexability_state"] == "indeterminate" or url["canonical_state"] == "indeterminate":
        values.add(Population.INDETERMINATE)
    return tuple(sorted(values, key=lambda item: item.value))


def _finding_definitions(
    pages: tuple[PageEvidenceListItem, ...],
) -> tuple[tuple[PageEvidenceListItem, str, str, str, str, dict[str, bool]], ...]:
    result = []
    for page in pages:
        if page.parsed_as_html and page.title_presence in {
            MetadataPresence.MISSING,
            MetadataPresence.EMPTY,
        }:
            result.append(
                (
                    page,
                    "metadata_title_missing",
                    "metadata",
                    "high",
                    "The page has no usable title.",
                    {
                        "metadata_impact": True,
                        "sitemap_impact": False,
                        "indexability_impact": False,
                    },
                )
            )
        if page.parsed_as_html and page.description_presence in {
            MetadataPresence.MISSING,
            MetadataPresence.EMPTY,
        }:
            result.append(
                (
                    page,
                    "metadata_description_missing",
                    "metadata",
                    "medium",
                    "The page has no usable meta description.",
                    {
                        "metadata_impact": True,
                        "sitemap_impact": False,
                        "indexability_impact": False,
                    },
                )
            )
        if page.http_status is not None and page.http_status >= _HTTP_ERROR_MINIMUM:
            result.append(
                (
                    page,
                    "status_error",
                    "status_and_redirects",
                    "high",
                    "The URL returned an HTTP error status.",
                    {"metadata_impact": False, "sitemap_impact": True, "indexability_impact": True},
                )
            )
        if page.robots_allowed is False:
            result.append(
                (
                    page,
                    "robots_blocked",
                    "robots_and_indexability",
                    "high",
                    "Robots policy blocks this URL.",
                    {"metadata_impact": False, "sitemap_impact": True, "indexability_impact": True},
                )
            )
        if page.parsed_as_html and page.canonical_presence is MetadataPresence.MISSING:
            result.append(
                (
                    page,
                    "canonical_missing",
                    "canonicals",
                    "medium",
                    "The page has no canonical URL declaration.",
                    {"metadata_impact": True, "sitemap_impact": True, "indexability_impact": False},
                )
            )
    return tuple(result)


def _recommended_action(code: str) -> str:
    return {
        "metadata_title_missing": "Add a unique, descriptive HTML title.",
        "metadata_description_missing": "Add a useful meta description.",
        "status_error": "Repair the URL or its internal references.",
        "robots_blocked": "Confirm robots policy matches the intended indexability.",
        "canonical_missing": "Add a valid canonical declaration where appropriate.",
    }.get(code, "Review the retained evidence and remediate the underlying cause.")


def _paged(
    loader: Callable[[int], tuple[dict[str, Any], ...]],
) -> tuple[dict[str, Any], ...]:
    items: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = tuple(loader(offset))
        items.extend(page)
        if len(page) < _PERSISTENCE_PAGE_SIZE:
            return tuple(items)
        offset += len(page)


def _optional_int(value: object) -> int | None:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _optional_float(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _specialist_stage_state(evidence: SpecialistEvidence) -> StageState:
    if evidence.eligibility_state != "eligible" or evidence.lifecycle_state == "unavailable":
        return StageState.UNAVAILABLE
    if evidence.lifecycle_state == "failed":
        return StageState.FAILED
    if evidence.lifecycle_state in {"cancelled", "partially_completed"} or evidence.partial:
        return StageState.PARTIAL
    if evidence.lifecycle_state in {"completed", "completed_with_warnings"}:
        return (
            StageState.PARTIAL
            if evidence.lifecycle_state == "completed_with_warnings"
            else StageState.COMPLETED
        )
    return StageState.RUNNING
