"""CSA-04 orchestration over accepted crawl, evidence, and artifact authorities."""

from __future__ import annotations

import ipaddress
import json
import uuid
from dataclasses import asdict
from typing import TYPE_CHECKING, Any, Protocol, cast
from urllib.parse import urlsplit

from musimack_tools.application.profiles import profile_for
from musimack_tools.domain.application import (
    ApplicationOutcomeCode,
    CrawlLimitOverrides,
    CrawlProfileName,
    RawApplicationCrawlRequest,
    ScopeProfile,
)
from musimack_tools.domain.crawl import CrawlExclusionRule, ExclusionRuleType
from musimack_tools.domain.fetching import (
    CRAWLER_USER_AGENT,
    OUTBOUND_DESTINATION_POLICY_VERSION,
)
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
    snapshot_hash,
)
from musimack_tools.domain.site_audit_settings import (
    RuleAction,
    RuleMatchType,
    RuleScope,
    RuleSource,
    SiteAuditSettingsError,
    UrlGovernanceRule,
    normalize_governed_url,
    rule_matches,
)
from musimack_tools.site_audit.artifacts import generate_site_audit_artifacts
from musimack_tools.site_audit.specialists import (
    SiteAuditSpecialistGateway,
    SpecialistEvidence,
    SpecialistRequest,
    SpecialistSafetyEnvelope,
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


def _sitemap_comparison_state(item: dict[str, Any]) -> str:  # noqa: C901, PLR0911
    if item.get("partial"):
        return "indeterminate"
    status = item.get("http_status")
    if item.get("fetch_state") == "failed" or (
        isinstance(status, int) and status >= _HTTP_ERROR_MINIMUM
    ):
        return "broken"
    if item.get("content_type") and "html" not in str(item["content_type"]).lower():
        return "non_html"
    if item.get("redirect_state") not in {None, "none", "not_redirected"}:
        return "redirect_source"
    if item.get("canonical_state") not in {"self", "self_canonical", "canonical", "unknown"}:
        return "canonicalized_elsewhere"
    recommended = item.get("recommended_sitemap_state")
    existing = item.get("existing_sitemap_state")
    if recommended == "include" and existing in {"present", "included"}:
        return "valid_unchanged"
    if recommended == "include":
        return "add"
    if recommended == "exclude" and existing in {"present", "included"}:
        return "remove"
    if recommended == "review":
        return "review"
    if item.get("sitemap_policy_decision") not in {"include", "evidence_derived"}:
        return "excluded_by_rule"
    if item.get("robots_state") in {"blocked", "disallowed"}:
        return "not_crawlable"
    return "indeterminate"


if TYPE_CHECKING:
    from collections.abc import Callable

    from musimack_tools.api.dependencies import InternalApiApplication
    from musimack_tools.artifacts.service import ArtifactService
    from musimack_tools.domain.application import (
        ApplicationCancellationResult,
        ApplicationJobStatus,
        ApplicationPreflightResult,
        ApplicationRecommendationPage,
        ApplicationResultProjection,
        ApplicationSubmissionResult,
        ApplicationValidationReport,
    )
    from musimack_tools.persistence.page_evidence_repository import (
        SQLAlchemyPageEvidenceRepository,
    )
    from musimack_tools.persistence.site_audit_orchestration_repository import (
        SQLAlchemySiteAuditOrchestrationRepository,
    )
    from musimack_tools.persistence.site_audit_repository import SQLAlchemySiteAuditRepository
    from musimack_tools.site_audit_settings.service import SiteAuditSettingsService


class SiteAuditCrawlGateway(Protocol):
    def validate(self, request: RawApplicationCrawlRequest) -> ApplicationValidationReport: ...

    async def preflight(
        self, request: RawApplicationCrawlRequest
    ) -> ApplicationPreflightResult: ...

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

    def validate(self, request: RawApplicationCrawlRequest) -> ApplicationValidationReport:
        return self._application.validate_request(request)

    async def preflight(self, request: RawApplicationCrawlRequest) -> ApplicationPreflightResult:
        return await self._application.preflight(request)

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
        settings: SiteAuditSettingsService | None = None,
    ) -> None:
        self._repository = repository
        self._orchestration = orchestration
        self._page_evidence = page_evidence
        self._crawl = crawl
        self._artifacts = artifacts
        self._specialists = specialists
        self._settings = settings

    def create_draft(
        self,
        draft: dict[str, Any],
        *,
        actor: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Create a durable UI draft without creating a crawl or snapshot."""

        normalized = _normalized_draft(draft)
        audit_id = (
            stable_identifier("audit", actor, idempotency_key)
            if idempotency_key
            else f"audit-{uuid.uuid4().hex[:24]}"
        )
        existing = self._repository.audit(audit_id)
        if existing is not None and "global_settings_version" not in normalized:
            normalized["global_settings_version"] = existing["draft"].get(
                "global_settings_version", 0
            )
        else:
            normalized.setdefault(
                "global_settings_version", self._current_global_settings_version()
            )
        if existing is not None:
            if existing["draft_hash"] == _draft_hash(normalized):
                return existing
            raise SiteAuditOrchestrationError(
                "site_audit_submission_conflict",
                "The idempotency key was already used for a different Site Audit draft.",
            )
        return self._repository.create_audit(
            audit_id,
            audit_name=str(normalized["audit_name"]),
            site_label=_string_or_none(normalized.get("site_label")),
            seed_url=str(normalized["seed_url"]),
            normalized_seed_url=str(normalized["normalized_seed_url"]),
            draft=normalized,
            created_by=actor,
            site_profile_id=_string_or_none(normalized.get("site_profile_id")),
            site_profile_version=_int_or_none(normalized.get("site_profile_version")),
            platform_preset_id=_string_or_none(normalized.get("platform_preset_id")),
            platform_preset_version=_string_or_none(normalized.get("platform_preset_version")),
        )

    def update_draft(
        self, audit_id: str, patch: dict[str, Any], *, expected_revision: int
    ) -> dict[str, Any]:
        audit = self._required_audit(audit_id)
        current = dict(audit["draft"])
        current.update(patch)
        normalized = _normalized_draft(current)
        normalized.setdefault("global_settings_version", self._current_global_settings_version())
        return self._repository.update_draft(
            audit_id, normalized, expected_revision=expected_revision
        )

    def history(
        self,
        *,
        offset: int = 0,
        page_size: int = 50,
        lifecycle: str | None = None,
        search: str | None = None,
    ) -> dict[str, Any]:
        items, total = self._repository.audits(
            offset=offset,
            page_size=page_size,
            lifecycle=lifecycle,
            search=search,
        )
        return {
            "items": items,
            "offset": offset,
            "page_size": page_size,
            "total": total,
            "ordering": "created_at_desc,audit_id_desc",
        }

    def audit_detail(self, audit_id: str) -> dict[str, Any]:
        audit = self._required_audit(audit_id)
        snapshot = self._repository.snapshot(audit_id)
        if snapshot is not None:
            effective_settings = snapshot["configuration"].get("resolution")
        else:
            try:
                effective_settings = self._resolve_configuration(audit)["resolution"]
            except SiteAuditOrchestrationError as error:
                effective_settings = {
                    "effective_rules": [],
                    "disabled_inherited_rules": [],
                    "warnings": [],
                    "resolution_error": {"code": error.code, "explanation": str(error)},
                }
        return {
            "audit": audit,
            "snapshot": snapshot,
            "orchestration": self._orchestration.orchestration(audit_id),
            "effective_settings": effective_settings,
        }

    def validate_draft(self, audit_id: str, *, expected_revision: int) -> dict[str, Any]:
        audit = self._required_audit(audit_id)
        if int(audit["revision"]) != expected_revision:
            raise SiteAuditPersistenceError(
                "site_audit_revision_conflict", "The draft changed; reload before validating."
            )
        configuration = self._resolve_configuration(audit)
        validating = self._repository.transition(
            audit_id, AuditLifecycle.VALIDATING, expected_revision=expected_revision
        )
        report = self._crawl.validate(_draft_crawl_request(validating, configuration))
        target = AuditLifecycle.VALIDATED if report.valid else AuditLifecycle.VALIDATION_FAILED
        updated = self._repository.transition(
            audit_id,
            target,
            expected_revision=int(validating["revision"]),
            failure_code=None if report.valid else "site_audit_validation_failed",
            failure_explanation=None if report.valid else "The draft has validation errors.",
        )
        return {
            "audit": updated,
            "validation": asdict(report),
            "effective_settings": configuration["resolution"],
        }

    async def preflight_draft(self, audit_id: str, *, expected_revision: int) -> dict[str, Any]:
        audit = self._required_audit(audit_id)
        if int(audit["revision"]) != expected_revision:
            raise SiteAuditPersistenceError(
                "site_audit_revision_conflict", "The draft changed; reload before preflight."
            )
        configuration = self._resolve_configuration(audit)
        preflighting = self._repository.transition(
            audit_id, AuditLifecycle.PREFLIGHTING, expected_revision=expected_revision
        )
        report = await self._crawl.preflight(_draft_crawl_request(preflighting, configuration))
        ready = report.state.value != "blocked" and report.validation.valid
        updated = self._repository.transition(
            audit_id,
            AuditLifecycle.READY if ready else AuditLifecycle.PREFLIGHT_FAILED,
            expected_revision=int(preflighting["revision"]),
            failure_code=None if ready else "site_audit_preflight_failed",
            failure_explanation=None if ready else "The bounded preflight did not pass.",
        )
        return {
            "audit": updated,
            "preflight": asdict(report),
            "effective_settings": configuration["resolution"],
        }

    async def submit(self, audit_id: str, *, actor: str) -> dict[str, Any]:
        audit = self._required_audit(audit_id)
        snapshot = self._repository.snapshot(audit_id)
        if snapshot is None:
            if audit["lifecycle"] != AuditLifecycle.READY.value:
                raise SiteAuditOrchestrationError(
                    "site_audit_not_ready", "Only a ready Site Audit may be submitted."
                )
            configuration = self._resolve_configuration(audit)
            if configuration["operation_mode"] == "real_site":
                authorization = self._current_real_site_authorization()
                if not authorization["enabled"]:
                    raise SiteAuditOrchestrationError(
                        "site_audit_real_site_operations_suspended",
                        "Real-site operations are globally suspended.",
                    )
                configuration["real_site_authorization"] = authorization
            configuration["submitted_by"] = actor
            configuration.setdefault("application_version", SITE_AUDIT_ORCHESTRATION_VERSION)
            validate_snapshot_integrity(
                {"configuration": configuration, "sha256": snapshot_hash(configuration)}
            )
            snapshot = self._repository.create_snapshot(
                audit_id,
                stable_identifier("snapshot", audit_id, str(audit["draft_hash"])),
                configuration,
                expected_revision=int(audit["revision"]),
                rules=_snapshot_rules(configuration),
                disabled_rules=_disabled_rules(configuration),
            )
            # The insert result intentionally contains only the parent row. Reload the complete
            # immutable aggregate so crawl preparation receives its normalized child rules.
            snapshot = self._required_snapshot(audit_id)
            audit = self._required_audit(audit_id)
        validate_snapshot_integrity(snapshot)
        snapshot_configuration = cast("dict[str, Any]", snapshot["configuration"])
        if snapshot_configuration.get("operation_mode") == "real_site" and not (
            self._current_real_site_authorization().get("enabled", False)
        ):
            raise SiteAuditOrchestrationError(
                "site_audit_real_site_operations_suspended",
                "Real-site operations are globally suspended.",
            )
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

    def _current_global_settings_version(self) -> int:
        if self._settings is None:
            return 0
        return self._settings.current_global_version()

    def _current_real_site_authorization(self) -> dict[str, Any]:
        if self._settings is None:
            return {"enabled": False, "status": "suspended"}
        return self._settings.current_real_site_authorization()

    def _resolve_configuration(self, audit: dict[str, Any]) -> dict[str, Any]:
        if self._settings is None:
            raise SiteAuditOrchestrationError(
                "site_audit_settings_unavailable",
                "Effective Site Audit settings cannot be resolved.",
            )
        draft = dict(audit["draft"])
        disabled = draft.get("disabled_inherited_rules", ())
        disabled_ids = (
            [
                str(item.get("stable_rule_id") or item.get("rule_id"))
                if isinstance(item, dict)
                else str(item)
                for item in disabled
            ]
            if isinstance(disabled, (list, tuple))
            else []
        )
        payload = {
            "global_settings_version": draft.get("global_settings_version"),
            "profile_id": draft.get("site_profile_id"),
            "profile_version": draft.get("site_profile_version"),
            "preset_id": draft.get("platform_preset_id"),
            "preset_version": draft.get("platform_preset_version"),
            "preset_accepted": draft.get("preset_accepted", False),
            "preset_rule_states": draft.get("preset_rule_states", {}),
            "tracking_parameters": draft.get("tracking_parameters", ()),
            "tracking_parameters_accepted": draft.get("tracking_parameters_accepted", False),
            "tracking_parameter_exceptions": draft.get("tracking_parameter_exceptions", ()),
            "overrides": {
                "crawl_profile": draft.get("crawl_profile", "standard_crawl"),
                "crawl_limit_overrides": draft.get("crawl_limits", {}),
                "metadata_thresholds": draft.get("thresholds", {}),
                "rules": draft.get("rules", ()),
                "disabled_rule_ids": disabled_ids,
            },
        }
        try:
            effective = self._settings.effective_settings(
                payload,
                actor=str(audit["created_by"]),
                resolved_at=str(audit["created_at"]),
            )
        except SiteAuditSettingsError as error:
            raise SiteAuditOrchestrationError(error.code, str(error)) from None
        crawl_profile = str(effective["crawl_profile"])
        selected_profile = profile_for(crawl_profile)
        if selected_profile is None:
            raise SiteAuditOrchestrationError(
                "site_audit_crawl_profile_invalid", "Crawl profile is invalid."
            )
        crawl_limits = asdict(selected_profile.limits)
        operation_mode = _operation_mode(str(draft.get("seed_url", "")))
        real_site_authorization = cast("dict[str, Any]", effective.get("real_site_operations", {}))
        if operation_mode == "real_site":
            if not real_site_authorization.get("enabled", False):
                raise SiteAuditOrchestrationError(
                    "site_audit_real_site_operations_suspended",
                    "Real-site operations are globally suspended.",
                )
            crawl_limits = _conservative_real_site_limits(
                crawl_limits,
                cast("dict[str, Any]", real_site_authorization.get("default_limits", {})),
            )
        crawl_limits.update(cast("dict[str, Any]", effective["crawl_limit_overrides"]))
        effective = dict(effective)
        effective.update(
            {
                "approved_hosts": draft.get("approved_hosts", []),
                "scope_policy": draft.get("scope_policy", {"mode": "exact_host"}),
                "crawl_limits": crawl_limits,
                "enabled_modules": draft.get("enabled_modules", []),
                "operation_mode": operation_mode,
                "outbound_policy_version": OUTBOUND_DESTINATION_POLICY_VERSION,
                "crawler_user_agent": CRAWLER_USER_AGENT,
                "real_site_authorization": real_site_authorization,
                "normalized_seed_url": audit["normalized_seed_url"],
                "submitted_by": audit["created_by"],
                "dns_timeout_seconds": 5.0,
                "publication_enabled": False,
                "external_ai_enabled": False,
                "summary_writing_enabled": False,
            }
        )
        configuration = dict(draft)
        configuration.update(
            {
                "global_settings_version": effective["global_settings_version"],
                "global_settings_hash": effective["global_settings_hash"],
                "crawl_profile": crawl_profile,
                "crawl_limits": crawl_limits,
                "thresholds": effective["metadata_thresholds"],
                "rules": effective["effective_rules"],
                "disabled_inherited_rules": effective["disabled_inherited_rules"],
                "tracking_parameters": effective["tracking_parameters"],
                "tracking_parameters_accepted": effective["tracking_parameters_accepted"],
                "tracking_parameter_exceptions": effective["tracking_parameter_exceptions"],
                "resolution": effective,
                "operation_mode": operation_mode,
                "outbound_policy_version": OUTBOUND_DESTINATION_POLICY_VERSION,
                "crawler_user_agent": CRAWLER_USER_AGENT,
                "real_site_authorization": real_site_authorization,
                "normalized_seed_url": audit["normalized_seed_url"],
                "submitted_by": audit["created_by"],
                "dns_timeout_seconds": 5.0,
                "publication_enabled": False,
                "external_ai_enabled": False,
                "summary_writing_enabled": False,
            }
        )
        return configuration

    async def reconcile(self, audit_id: str) -> dict[str, Any]:  # noqa: C901, PLR0911
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
        expected_run_id = str(parent["crawl_run_id"])
        if crawl_status.job_id != job_id or crawl_status.run_id != expected_run_id:
            self._fail_execution_integrity(
                audit_id,
                code="site_audit_execution_owner_mismatch",
                explanation="The crawl status owner does not match this Site Audit execution.",
            )
            return self.status(audit_id)
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
        if crawl_status.state == "failed":
            self._fail_execution_integrity(
                audit_id,
                code="site_audit_terminal_persistence_failed",
                explanation=(
                    "The crawl execution failed before its terminal evidence could be retained."
                ),
            )
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
        if result.job_id != job_id or result.run_id != expected_run_id:
            self._fail_execution_integrity(
                audit_id,
                code="site_audit_execution_owner_mismatch",
                explanation="The retained crawl result belongs to another execution.",
            )
            return self.status(audit_id)
        self._start_parent_and_crawl(audit_id)
        crawl_counts = dict(result.crawl_counts)
        self._orchestration.update_stage(
            audit_id,
            SiteAuditStage.CRAWL,
            StageState.PARTIAL
            if result.run_lifecycle in {"partially_completed", "completed_with_warnings"}
            else StageState.COMPLETED,
            source_count=crawl_counts.get(
                "urls_discovered", crawl_counts.get("unique_urls_discovered", 0)
            ),
            projected_count=crawl_counts.get("urls_fetched", 0),
        )
        await self._project(
            audit_id,
            expected_run_id,
            job_id,
            result,
        )
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
        module_counts = _decoded_json(value.get("module_counts_json"))
        if isinstance(module_counts, dict):
            value["operational_accounting"] = module_counts.get("operational_accounting")
        return value

    def pages(  # noqa: PLR0913
        self,
        audit_id: str,
        *,
        offset: int = 0,
        page_size: int = 50,
        filters: dict[str, Any] | None = None,
        sort: str = "sequence",
        direction: str = "asc",
    ) -> dict[str, Any]:
        values = filters or {}
        items, total = self._repository.urls(
            audit_id,
            offset=offset,
            page_size=page_size,
            url_text=cast("str | None", values.get("url")),
            http_status=cast("int | None", values.get("http_status")),
            sitemap_state=cast("str | None", values.get("recommended_sitemap")),
            only_partial=cast("bool | None", values.get("partial")),
            filters=values,
            sort=sort,
            direction=direction,
        )
        return {
            "items": tuple(self._enrich_url(item) for item in items),
            "offset": offset,
            "page_size": page_size,
            "total": total,
            "ordering": f"{sort}:{direction},sequence,url_id",
        }

    def page_detail(self, audit_id: str, sequence: int) -> dict[str, Any]:
        value = self._repository.url_detail(audit_id, sequence)
        if value is None:
            raise SiteAuditOrchestrationError(
                "site_audit_evidence_unavailable", "The requested URL evidence is unavailable."
            )
        return self._enrich_url(value)

    def issues(
        self,
        audit_id: str,
        *,
        offset: int = 0,
        page_size: int = 50,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        items = self._repository.issue_groups(
            audit_id, offset=offset, page_size=page_size, filters=filters
        )
        return {
            "items": items,
            "offset": offset,
            "page_size": page_size,
            "total": self._repository.issue_group_count(audit_id, filters=filters),
            "ordering": "priority_key,group_id",
        }

    def issue_detail(
        self,
        audit_id: str,
        group_id: str,
        *,
        offset: int = 0,
        page_size: int = 50,
    ) -> dict[str, Any]:
        value = self._repository.issue_group_detail(
            audit_id, group_id, offset=offset, page_size=page_size
        )
        if value is None:
            raise SiteAuditOrchestrationError(
                "site_audit_projection_unavailable", "The issue group is unavailable."
            )
        return value

    def rules(self, audit_id: str, *, offset: int = 0, page_size: int = 50) -> dict[str, Any]:
        return {
            "items": self._repository.rule_matches(audit_id, offset=offset, page_size=page_size),
            "offset": offset,
            "page_size": page_size,
        }

    def artifact_associations(self, audit_id: str) -> tuple[dict[str, Any], ...]:
        items: list[dict[str, Any]] = []
        for association in self._repository.artifact_associations(audit_id):
            item = dict(association)
            try:
                artifact = self._artifacts.get(str(item["artifact_id"]))
            except Exception:  # noqa: BLE001 - unavailable artifacts remain explicit and safe.
                item["artifact"] = None
            else:
                item["artifact"] = {
                    "artifact_id": artifact.artifact_id,
                    "artifact_type": artifact.artifact_type.value,
                    "filename": artifact.filename,
                    "content_type": artifact.content_type,
                    "byte_count": artifact.expected_byte_count,
                    "sha256": artifact.expected_sha256,
                    "lifecycle_state": artifact.lifecycle_state.value,
                    "integrity_state": artifact.integrity_state.value,
                    "created_at": artifact.created_at.isoformat(),
                    "expires_at": artifact.expires_at.isoformat() if artifact.expires_at else None,
                    "download_available": artifact.lifecycle_state.value
                    in {"available", "retained"}
                    and artifact.integrity_state.value == "verified",
                }
            items.append(item)
        return tuple(items)

    def sitemap_comparison(
        self,
        audit_id: str,
        *,
        offset: int = 0,
        page_size: int = 50,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        values = filters or {}
        items, total = self._repository.urls(
            audit_id,
            offset=offset,
            page_size=page_size,
            url_text=cast("str | None", values.get("url")),
            sitemap_state=cast("str | None", values.get("state")),
            only_partial=cast("bool | None", values.get("partial")),
        )
        selected = tuple(
            {
                "sequence": item["sequence"],
                "url_id": item["url_id"],
                "url": item["normalized_url"],
                "existing_sitemap_state": item["existing_sitemap_state"],
                "recommended_sitemap_state": item["recommended_sitemap_state"],
                "sitemap_policy_decision": item["sitemap_policy_decision"],
                "comparison_state": _sitemap_comparison_state(item),
                "primary_reason": item.get("failure_code") or item["sitemap_policy_decision"],
                "http_status": item["http_status"],
                "robots_state": item["robots_state"],
                "indexability_state": item["indexability_state"],
                "canonical_state": item["canonical_state"],
                "partial": item["partial"],
            }
            for item in items
        )
        modules = self._repository.module_statuses(audit_id)
        existing = next((item for item in modules if item["module"] == "existing_sitemap"), None)
        documents, document_total = self._repository.sitemap_documents(
            audit_id, offset=0, page_size=500
        )
        summary = self._repository.summary(audit_id) or {}
        sitemap_only = sum(
            item.get("existing_sitemap_state") == "present" and item.get("fetch_state") != "fetched"
            for item in self._all_urls(audit_id)
        )
        return {
            "items": selected,
            "offset": offset,
            "page_size": page_size,
            "total": total,
            "existing_sitemap_module": existing,
            "document_count": document_total,
            "document_preview": documents,
            "sitemap_totals": {
                "index_count": sum(item.get("root_type") == "sitemap_index" for item in documents),
                "document_count": document_total,
                "entry_count": sum(int(item.get("entry_count", 0)) for item in documents),
                "sitemap_only_count": sitemap_only,
                "fetch_failure_count": sum(
                    item.get("fetch_state") == "failed" for item in documents
                ),
                "definition": "Present in an existing sitemap and not fetched by the parent crawl.",
            },
            "comparison_totals": {
                "include": summary.get("recommendation_include", 0),
                "exclude": summary.get("recommendation_exclude", 0),
                "review": summary.get("recommendation_review", 0),
                "indeterminate": summary.get("recommendation_indeterminate", 0),
            },
            "ordering": "sequence,url_id",
        }

    def exclusions(
        self,
        audit_id: str,
        *,
        offset: int = 0,
        page_size: int = 50,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        governed, total = self._repository.excluded_urls(
            audit_id, offset=offset, page_size=page_size, filters=filters
        )
        return {
            "items": governed,
            "offset": offset,
            "page_size": page_size,
            "total": total,
            "ordering": "sequence,url_id",
        }

    def sitemap_documents(
        self,
        audit_id: str,
        *,
        offset: int = 0,
        page_size: int = 50,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        items, total = self._repository.sitemap_documents(
            audit_id, offset=offset, page_size=page_size, filters=filters
        )
        return {
            "items": items,
            "offset": offset,
            "page_size": page_size,
            "total": total,
            "ordering": "discovery_sequence,document_id",
        }

    def evidence(self, audit_id: str) -> dict[str, Any]:
        status = self.status(audit_id)
        findings = self._repository.findings(audit_id, offset=0, page_size=500)
        snapshot = self._repository.snapshot(audit_id)
        summary = self.summary(audit_id)
        return {
            "audit": status["audit"],
            "orchestration": status["orchestration"],
            "stages": status["stages"],
            "modules": status["modules"],
            "specialists": status["specialists"],
            "findings": findings,
            "finding_count": len(findings),
            "snapshot": snapshot,
            "operational_accounting": summary.get("operational_accounting"),
            "projection_version": SITE_AUDIT_ORCHESTRATION_VERSION,
            "body_content_retained": False,
        }

    def settings_snapshot(self, audit_id: str) -> dict[str, Any]:
        snapshot = self._repository.snapshot(audit_id)
        if snapshot is None:
            raise SiteAuditOrchestrationError(
                "site_audit_projection_unavailable",
                "The immutable settings snapshot is unavailable for this draft.",
            )
        return snapshot

    def archive(self, audit_id: str) -> dict[str, Any]:
        audit = self._required_audit(audit_id)
        return self._repository.transition(
            audit_id, AuditLifecycle.ARCHIVED, expected_revision=int(audit["revision"])
        )

    def rebuild_summary(self, audit_id: str) -> dict[str, Any]:
        return self._repository.rebuild_summary(audit_id)

    async def _project(  # noqa: PLR0911 - each integrity gate fails closed immediately.
        self,
        audit_id: str,
        run_id: str,
        job_id: str,
        result: ApplicationResultProjection,
    ) -> None:
        evidence_summary = self._page_evidence.get_summary(run_id)
        if evidence_summary is None:
            self._fail_execution_integrity(
                audit_id,
                code="site_audit_evidence_unavailable",
                explanation="Durable crawl page evidence is unavailable for this execution.",
                stage=SiteAuditStage.INGEST,
            )
            return
        if evidence_summary.run_id != run_id or evidence_summary.job_id != job_id:
            self._fail_execution_integrity(
                audit_id,
                code="site_audit_evidence_owner_mismatch",
                explanation="Durable page evidence belongs to another crawl execution.",
                stage=SiteAuditStage.INGEST,
            )
            return
        pages = self._all_page_evidence(run_id)
        if not pages:
            self._fail_execution_integrity(
                audit_id,
                code="site_audit_evidence_unavailable",
                explanation="Durable crawl page evidence is unavailable for this execution.",
                stage=SiteAuditStage.INGEST,
            )
            return
        if any(page.run_id != run_id or page.job_id != job_id for page in pages):
            self._fail_execution_integrity(
                audit_id,
                code="site_audit_evidence_owner_mismatch",
                explanation="One or more page records belong to another crawl execution.",
                stage=SiteAuditStage.INGEST,
            )
            return
        if evidence_summary.total_records != len(pages):
            self._fail_execution_integrity(
                audit_id,
                code="site_audit_evidence_count_mismatch",
                explanation="The retained page-evidence summary does not match its records.",
                stage=SiteAuditStage.INGEST,
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
        if not self._validate_population_integrity(audit_id, result, summary):
            return
        if not self._validate_artifact_inputs(audit_id, pages, job_id, run_id):
            return
        accounting = _aggregate_operational_accounting(
            result,
            specialist_evidence,
            scope_denials=sum(
                item.get("failure_code") == "scope_denied" for item in self._all_urls(audit_id)
            ),
        )
        self._orchestration.update_stage(
            audit_id, SiteAuditStage.SUMMARY, StageState.COMPLETED, projected_count=1
        )
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
        # Final exports are deliberately gated on the retained terminal lifecycle. A crash
        # during storage is repaired idempotently by the existing purpose association keys.
        self._finish(audit_id, final)
        summary = self._repository.rebuild_summary(audit_id)
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
        summary = self._repository.set_operational_accounting(audit_id, accounting)
        self._generate_artifacts(audit_id, pages, summary, job_id, run_id)

    def _validate_population_integrity(
        self,
        audit_id: str,
        result: ApplicationResultProjection,
        summary: dict[str, Any],
    ) -> bool:
        crawl = dict(result.crawl_counts)
        admitted = int(crawl.get("urls_admitted", crawl.get("urls_queued", 0)))
        fetched = int(crawl.get("urls_fetched", 0))
        parsed = int(crawl.get("urls_parsed", summary.get("html_urls", 0)))
        metadata = int(summary.get("metadata_scoring_eligible_urls", 0))
        canonical = int(summary.get("canonical_urls", 0))
        indexable = int(summary.get("indexable_urls", 0))
        if fetched > admitted or parsed > fetched or metadata > parsed:
            self._fail_execution_integrity(
                audit_id,
                code="site_audit_population_integrity_failed",
                explanation="Retained crawl populations violate required subset relationships.",
                stage=SiteAuditStage.SUMMARY,
            )
            return False
        if metadata > canonical or metadata > indexable:
            self._fail_execution_integrity(
                audit_id,
                code="site_audit_population_integrity_failed",
                explanation="Metadata eligibility exceeds its canonical or indexable population.",
                stage=SiteAuditStage.SUMMARY,
            )
            return False
        return True

    def _validate_artifact_inputs(
        self,
        audit_id: str,
        pages: tuple[PageEvidenceListItem, ...],
        job_id: str,
        run_id: str,
    ) -> bool:
        page_ids = {page.evidence_id for page in pages}
        if any(
            item.get("evidence_id") is not None and item.get("evidence_id") not in page_ids
            for item in self._all_findings(audit_id)
        ):
            self._fail_execution_integrity(
                audit_id,
                code="site_audit_finding_owner_mismatch",
                explanation="A retained finding references evidence from another execution.",
                stage=SiteAuditStage.ARTIFACTS,
            )
            return False
        for association in self._repository.artifact_associations(audit_id):
            record = self._artifacts.get(str(association["artifact_id"]))
            if record.job_id != job_id or record.run_id != run_id:
                self._fail_execution_integrity(
                    audit_id,
                    code="site_audit_artifact_owner_mismatch",
                    explanation="A retained artifact belongs to another execution.",
                    stage=SiteAuditStage.ARTIFACTS,
                )
                return False
        return True

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
            observed = _observed_rule_urls(
                url,
                self._repository.discovery_sources(audit_id, str(url["url_id"])),
            )
            matched = [
                (rule, record, original)
                for rule, record in zip(rules, stored, strict=True)
                if rule.enabled
                and (
                    original := next(
                        (candidate for candidate in observed if rule_matches(rule, candidate)),
                        None,
                    )
                )
                is not None
            ]
            overridden_ids = {
                target for rule, _record, _original in matched for target in rule.overrides_rule_ids
            }
            active_matches = [
                (rule, record)
                for rule, record, _original in matched
                if rule.rule_id not in overridden_ids
            ]
            decisions = _governance_decisions(active_matches)
            if url.get("failure_code") == "scope_denied":
                decisions["discovery_decision"] = "scope_denied"
            elif (
                decisions["discovery_decision"] == "exclude_from_discovery"
                and url.get("fetch_state") == "not_fetched"
            ):
                decisions["enqueued_state"] = "not_enqueued"
            self._orchestration.update_url(audit_id, str(url["url_id"]), decisions)
            by_layer: dict[str, list[tuple[UrlGovernanceRule, dict[str, Any], str]]] = {}
            for rule, record, original in matched:
                by_layer.setdefault(str(record["decision_layer"]), []).append(
                    (rule, record, original)
                )
            for layer, matches in by_layer.items():
                ordered = sorted(
                    matches,
                    key=lambda item: (
                        int(item[1]["stable_order"]),
                        str(item[1]["stable_rule_id"]),
                    ),
                )
                active_ordered = [item for item in ordered if item[0].rule_id not in overridden_ids]
                conflict = len({item[0].action.value for item in active_ordered}) > 1
                primary_rule_id = active_ordered[0][0].rule_id if active_ordered else None
                for position, (rule, record, original) in enumerate(ordered):
                    overridden = rule.rule_id in overridden_ids
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
                                "primary_rule": rule.rule_id == primary_rule_id,
                                "contributed": not overridden,
                                "overridden": overridden,
                                "specificity": record["specificity"],
                                "priority": record["priority"],
                                "precedence_key": f"{position:04d}:{record['stable_rule_id']}",
                                "conflict_code": ("site_audit_rule_conflict" if conflict else None),
                                "reason": rule.reason,
                                "matched_original_url": original,
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
        limits = cast("dict[str, Any]", configuration.get("crawl_limits", {}))
        authorization = cast("dict[str, Any]", configuration.get("real_site_authorization", {}))
        envelope = SpecialistSafetyEnvelope(
            authorization_enabled=bool(authorization.get("enabled", False)),
            authorization_version=_optional_int(
                authorization.get("global_settings_version", authorization.get("version"))
            ),
            destination_policy_version=str(
                configuration.get("outbound_policy_version", OUTBOUND_DESTINATION_POLICY_VERSION)
            ),
            user_agent=str(configuration.get("crawler_user_agent", CRAWLER_USER_AGENT)),
            maximum_urls=int(limits.get("maximum_urls", 100)),
            maximum_depth=int(limits.get("maximum_depth", 3)),
            maximum_duration_seconds=float(limits.get("maximum_duration_seconds", 300)),
            maximum_accepted_bytes=int(limits.get("maximum_accepted_bytes", 50_000_000)),
            maximum_concurrency=int(limits.get("maximum_concurrency", 1)),
            maximum_queue_size=int(limits.get("maximum_queue_size", 500)),
            minimum_request_delay_seconds=float(limits.get("minimum_request_delay_seconds", 1)),
            maximum_redirect_hops=int(limits.get("maximum_redirect_hops", 5)),
            maximum_response_bytes=int(limits.get("maximum_response_bytes", 3_000_000)),
            dns_timeout_seconds=float(configuration.get("dns_timeout_seconds", 5.0)),
            retry_policy="none",
            recovery_policy="reuse_immutable_configuration",
        )
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
                    safety_envelope=envelope,
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

    def _aggregate_issues(  # noqa: C901 - ordered deterministic aggregation is explicit.
        self, audit_id: str, pages: tuple[PageEvidenceListItem, ...]
    ) -> None:
        self._orchestration.update_stage(
            audit_id,
            SiteAuditStage.ISSUE_AGGREGATION,
            StageState.RUNNING,
            lease_owner="reconciler",
        )
        snapshot = self._required_snapshot(audit_id)
        thresholds = snapshot["configuration"].get("thresholds", {})
        title_maximum = int(thresholds.get("title_maximum", 60))
        definitions = _finding_definitions(pages, title_maximum=title_maximum)
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
        url_findings: dict[str, list[str]] = {}
        for page, _code, _category, severity, _explanation, _impacts in definitions:
            url = urls_by_evidence.get(page.evidence_id)
            if url is not None:
                url_findings.setdefault(str(url["url_id"]), []).append(severity)
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "information": 4}
        for url_id, severities in url_findings.items():
            self._orchestration.update_url(
                audit_id,
                url_id,
                {
                    "issue_count": len(severities),
                    "highest_severity": min(severities, key=lambda item: severity_order[item]),
                },
            )
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
        urls = tuple(self._enrich_url(item) for item in self._all_urls(audit_id))
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

    def _enrich_url(self, item: dict[str, Any]) -> dict[str, Any]:
        """Join the retained safe page projection without creating a second authority."""

        result = dict(item)
        evidence_id = result.get("evidence_id")
        if not isinstance(evidence_id, str):
            return result
        evidence = self._page_evidence.get_safe_page_evidence(evidence_id)
        if evidence is None:
            return result
        result.update(
            {
                "title": evidence.get("title_value"),
                "title_length": evidence.get("title_length"),
                "description": evidence.get("description_value"),
                "description_length": evidence.get("description_length"),
                "canonical": evidence.get("canonical_url"),
                "meta_robots": _decoded_json(evidence.get("meta_robots_json")),
                "x_robots_tag": _decoded_json(evidence.get("x_robots_json")),
                "metadata_warning_count": evidence.get("parse_warning_count"),
                "metadata_evidence_state": evidence.get("evidence_state"),
            }
        )
        page_summary = self._page_evidence.safe_page_summary(evidence_id)
        result["link_summary"] = {"occurrences": page_summary["links"]}
        result["image_summary"] = {"occurrences": page_summary["images"]}
        result["structured_data_summary"] = {"blocks": page_summary["structured_data"]}
        return result

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
            AuditLifecycle.QUEUED.value,
            AuditLifecycle.RUNNING.value,
            AuditLifecycle.CANCEL_REQUESTED.value,
            AuditLifecycle.RECOVERY_REQUIRED.value,
        }:
            self._repository.transition(
                audit_id,
                lifecycle,
                expected_revision=int(audit["revision"]),
                failure_code=failure_code,
                failure_explanation=explanation,
            )

    def _fail_execution_integrity(
        self,
        audit_id: str,
        *,
        code: str,
        explanation: str,
        stage: SiteAuditStage = SiteAuditStage.CRAWL,
    ) -> None:
        """Fail closed without projecting or exporting evidence from another execution."""
        self._orchestration.update_stage(
            audit_id,
            stage,
            StageState.FAILED,
            failure_code=code,
            failure_explanation=explanation,
        )
        self._finish(
            audit_id,
            OrchestrationState.FAILED,
            failure_code=code,
            explanation=explanation,
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


def _operation_mode(seed_url: str) -> str:
    """Classify deterministic local fixtures separately from outbound real-site work."""

    hostname = (urlsplit(seed_url).hostname or "").rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        return "fixture"
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return "real_site"
    return "fixture" if not address.is_global else "real_site"


def _conservative_real_site_limits(
    profile_limits: dict[str, Any], configured_defaults: dict[str, Any]
) -> dict[str, Any]:
    """Apply real-site defaults without silently raising a selected profile limit."""

    result = dict(profile_limits)
    for key, value in configured_defaults.items():
        current = result.get(key)
        if current is None:
            result[key] = value
        elif key == "minimum_request_delay_seconds":
            result[key] = max(current, value)
        else:
            result[key] = min(current, value)
    return result


def _crawl_request(audit: dict[str, Any], snapshot: dict[str, Any]) -> RawApplicationCrawlRequest:
    configuration = snapshot["configuration"]
    limits = configuration.get("crawl_limits", {})
    if not isinstance(limits, dict):
        limits = {}
    scope = configuration.get("scope_policy", {})
    scope_name = scope.get("mode", "exact_host") if isinstance(scope, dict) else str(scope)
    approved = configuration.get("approved_hosts", [])
    request_approved_hosts = approved if scope_name == ScopeProfile.APPROVED_HOSTS.value else []
    return RawApplicationCrawlRequest(
        seed_url=str(audit["normalized_seed_url"]),
        scope_profile=ScopeProfile(scope_name),
        approved_hosts=tuple(str(item) for item in request_approved_hosts),
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
        execution_identity=f"site-audit:{audit['audit_id']}",
        exclusion_rules=_discovery_exclusion_rules(snapshot),
        strip_query_parameters=_tracking_parameters(snapshot),
    )


def _draft_crawl_request(
    audit: dict[str, Any], configuration: dict[str, Any]
) -> RawApplicationCrawlRequest:
    if not isinstance(audit.get("draft"), dict):
        raise SiteAuditOrchestrationError(
            "site_audit_evidence_unavailable", "The Site Audit draft is unavailable."
        )
    return _crawl_request(
        audit,
        {"configuration": configuration, "rules": _snapshot_rules(configuration)},
    )


def _normalized_draft(value: dict[str, Any]) -> dict[str, Any]:
    seed = str(value.get("seed_url", "")).strip()
    if not seed:
        raise SiteAuditOrchestrationError(
            "site_audit_not_ready", "A seed URL is required to create a Site Audit."
        )
    normalized = str(normalize_governed_url(seed, strip_parameters=set())["normalized_url"])
    result = dict(value)
    result["seed_url"] = seed
    result["normalized_seed_url"] = normalized
    result["audit_name"] = str(value.get("audit_name") or f"Site Audit: {normalized}")[:200]
    result["site_label"] = _string_or_none(value.get("site_label"))
    result.setdefault("scope_policy", {"mode": "exact_host"})
    scope = result["scope_policy"]
    scope_mode = scope.get("mode") if isinstance(scope, dict) else str(scope)
    if scope_mode == "exact_host":
        seed_host = urlsplit(normalized).hostname
        result["approved_hosts"] = [seed_host] if seed_host else []
    else:
        result.setdefault("approved_hosts", [])
    result.setdefault("crawl_profile", CrawlProfileName.STANDARD_CRAWL.value)
    result.setdefault("crawl_limits", {})
    result.setdefault("rules", [])
    result.setdefault("disabled_inherited_rules", [])
    result.setdefault("tracking_parameters", [])
    result.setdefault("tracking_parameters_accepted", False)
    result.setdefault("tracking_parameter_exceptions", [])
    result.setdefault("enabled_modules", [])
    result.setdefault("thresholds", {})
    result.setdefault("business_importance", [])
    result.setdefault("publication_requested", False)
    return result


def _snapshot_rules(configuration: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    actions = {
        RuleAction.EXCLUDE_FROM_DISCOVERY.value: "discovery",
        RuleAction.EXCLUDE_FROM_METADATA.value: "metadata_scoring",
        RuleAction.EXCLUDE_FROM_SITEMAP.value: "sitemap",
        RuleAction.MARK_FOR_REVIEW.value: "discovery",
        RuleAction.STRIP_QUERY_PARAMETER.value: "normalization",
    }
    specificity = {
        RuleMatchType.EXACT_URL.value: 7,
        RuleMatchType.EXACT_PATH.value: 6,
        RuleMatchType.QUERY_PARAMETER_EQUALS.value: 5,
        RuleMatchType.QUERY_PARAMETER_EXISTS.value: 4,
        RuleMatchType.PATH_STARTS_WITH.value: 3,
        RuleMatchType.PATH_ENDS_WITH.value: 3,
        RuleMatchType.PATH_CONTAINS.value: 2,
    }
    result: list[dict[str, Any]] = []
    raw = configuration.get("rules", ())
    if not isinstance(raw, (list, tuple)):
        return ()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        action = str(item.get("action", ""))
        match_type = str(item.get("match_type", ""))
        source = str(item.get("source") or "per_audit")
        source_id = (
            configuration.get("platform_preset_id")
            if source == RuleSource.PRESET.value
            else configuration.get("site_profile_id")
            if source == RuleSource.SITE_PROFILE.value
            else "global-settings"
            if source == RuleSource.GLOBAL.value
            else "audit-draft"
        )
        source_version = (
            configuration.get("platform_preset_version")
            if source == RuleSource.PRESET.value
            else configuration.get("site_profile_version")
            if source == RuleSource.SITE_PROFILE.value
            else configuration.get("global_settings_version")
            if source == RuleSource.GLOBAL.value
            else item.get("version", 1)
        )
        result.append(
            {
                "stable_rule_id": str(
                    item.get("rule_id") or stable_identifier("rule", index, item)
                ),
                "rule_source": source,
                "source_id": str(source_id) if source_id is not None else None,
                "source_version": str(source_version),
                "decision_layer": str(item.get("scope") or actions.get(action, "discovery")),
                "match_type": match_type,
                "match_value": str(item.get("match_value", "")),
                "action": action,
                "enabled": bool(item.get("enabled", True)),
                "priority": int(item.get("priority", 0)),
                "specificity": specificity.get(match_type, 0),
                "reason_code": str(item.get("reason_code") or "per_audit_rule"),
                "explanation": str(
                    item.get("reason") or item.get("description") or "Rule applied."
                ),
                "overrides_rule_ids": tuple(
                    str(value) for value in item.get("overrides_rule_ids", ())
                ),
            }
        )
    return tuple(result)


def _disabled_rules(configuration: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    raw = configuration.get("disabled_inherited_rules", ())
    if not isinstance(raw, (list, tuple)):
        return ()
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict) or not (item.get("stable_rule_id") or item.get("rule_id")):
            continue
        source = str(item.get("rule_source") or item.get("source") or "preset")
        source_version = (
            configuration.get("platform_preset_version")
            if source == RuleSource.PRESET.value
            else configuration.get("site_profile_version")
            if source == RuleSource.SITE_PROFILE.value
            else configuration.get("global_settings_version")
            if source == RuleSource.GLOBAL.value
            else item.get("version", 1)
        )
        result.append(
            {
                "stable_rule_id": str(item.get("stable_rule_id") or item.get("rule_id")),
                "rule_source": source,
                "source_version": str(source_version),
                "reason_code": str(item.get("reason_code") or "disabled_by_override"),
            }
        )
    return tuple(result)


def _draft_hash(value: dict[str, Any]) -> str:
    return snapshot_hash(value)


def _string_or_none(value: object) -> str | None:
    return str(value) if value not in {None, ""} else None


def _int_or_none(value: object) -> int | None:
    return int(str(value)) if value not in {None, ""} else None


def _aggregate_operational_accounting(
    parent: ApplicationResultProjection,
    specialists: dict[SiteAuditStage, SpecialistEvidence],
    *,
    scope_denials: int,
) -> dict[str, Any]:
    """Combine each durable execution authority exactly once by module identity."""

    specialist_records = {
        stage.value: evidence.operational_accounting
        for stage, evidence in specialists.items()
        if isinstance(evidence.operational_accounting, dict)
    }

    def specialist_total(name: str) -> int:
        return sum(int(record.get(name, 0)) for record in specialist_records.values())

    specialist_fingerprints = {
        str(value)
        for record in specialist_records.values()
        for value in record.get("resolved_address_fingerprints", ())
        if isinstance(value, str)
    }
    fingerprints = tuple(
        sorted({*parent.resolved_address_fingerprints, *specialist_fingerprints})[:256]
    )
    robots_outcomes: dict[str, int] = dict(parent.robots_outcome_counts)
    sitemap_outcomes: dict[str, int] = {}
    for record in specialist_records.values():
        raw_robots = record.get("robots_outcomes", {})
        if isinstance(raw_robots, dict):
            for key, value in raw_robots.items():
                robots_outcomes[str(key)] = robots_outcomes.get(str(key), 0) + int(value)
        raw_sitemap = record.get("sitemap_outcomes", {})
        if isinstance(raw_sitemap, dict):
            for key, value in raw_sitemap.items():
                sitemap_outcomes[str(key)] = sitemap_outcomes.get(str(key), 0) + int(value)

    envelopes = {
        stage.value: evidence.safety_envelope
        for stage, evidence in specialists.items()
        if isinstance(evidence.safety_envelope, dict)
    }
    parent_scope_denials = max(parent.scope_denial_count, scope_denials)
    crawl_counts = dict(parent.crawl_counts)
    return {
        "definition": (
            "Parent crawl and each specialist execution are counted once from their final "
            "durable projections; reconciliation and artifact retries do not add observations."
        ),
        "crawl_elapsed_seconds": parent.crawl_elapsed_seconds,
        "dns_operation_count": parent.dns_resolution_count
        + specialist_total("dns_operation_count"),
        "request_count": parent.outbound_request_count + specialist_total("request_count"),
        "accepted_byte_count": parent.accepted_byte_count + specialist_total("accepted_byte_count"),
        "redirect_count": parent.outbound_redirect_count + specialist_total("redirect_count"),
        "rejected_destination_count": parent.rejected_destination_count
        + specialist_total("rejected_destination_count"),
        "scope_denial_count": parent_scope_denials + specialist_total("scope_denial_count"),
        "robots_request_count": parent.robots_request_count
        + specialist_total("robots_request_count"),
        "page_request_count": parent.page_request_count,
        "sitemap_request_count": specialist_total("sitemap_request_count"),
        "retry_count": parent.retry_count + specialist_total("retry_count"),
        "timeout_count": parent.timeout_count + specialist_total("timeout_count"),
        "response_size_rejection_count": parent.response_size_rejection_count
        + specialist_total("response_size_rejection_count"),
        "resolved_address_fingerprints": fingerprints,
        "robots_outcomes": dict(sorted(robots_outcomes.items())),
        "sitemap_outcomes": dict(sorted(sitemap_outcomes.items())),
        "source_attribution": {
            "parent_crawl": {
                "request_count": parent.outbound_request_count,
                "dns_operation_count": parent.dns_resolution_count,
                "accepted_byte_count": parent.accepted_byte_count,
                "redirect_count": parent.outbound_redirect_count,
                "scope_denial_count": parent_scope_denials,
                "robots_request_count": parent.robots_request_count,
                "page_request_count": parent.page_request_count,
            },
            "specialists": specialist_records,
        },
        "specialist_safety_envelopes": envelopes,
        "url_admission": {
            "admitted": crawl_counts.get("urls_admitted", 0),
            "fetched": crawl_counts.get("urls_fetched", 0),
            "over_limit": crawl_counts.get("urls_over_limit", 0),
            "definition": (
                "Over-limit discoveries are retained as rejected admission evidence; "
                "already-queued URLs continue processing."
            ),
        },
    }


def _inventory_url(snapshot: dict[str, Any], url: str) -> str:
    return str(
        normalize_governed_url(url, strip_parameters=set(_tracking_parameters(snapshot)))[
            "normalized_url"
        ]
    )


def _observed_rule_urls(
    url: dict[str, Any], discoveries: tuple[dict[str, Any], ...]
) -> tuple[str, ...]:
    values: list[str] = [
        str(url[key]) for key in ("original_url", "requested_url", "normalized_url") if url.get(key)
    ]
    for discovery in discoveries:
        relationship = discovery.get("relationship_json")
        if isinstance(relationship, str):
            try:
                relationship = json.loads(relationship)
            except json.JSONDecodeError:
                relationship = {}
        if isinstance(relationship, dict) and relationship.get("resolved_url"):
            values.append(str(relationship["resolved_url"]))
    return tuple(dict.fromkeys(values))


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
        "fetch_state": (
            "fetched" if page.fetch_outcome in {"success", "failure"} else "not_fetched"
        ),
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


def _governance_decisions(
    matched: list[tuple[UrlGovernanceRule, dict[str, Any]]],
) -> dict[str, Any]:
    by_layer: dict[str, list[tuple[RuleAction, int, str]]] = {}
    for rule, record in matched:
        by_layer.setdefault(str(record["decision_layer"]), []).append(
            (
                rule.action,
                int(record["stable_order"]),
                str(record["stable_rule_id"]),
            )
        )
    discovery = "enqueue"
    metadata = "include_in_metadata_scoring"
    sitemap = "evidence_derived"
    for layer, records in by_layer.items():
        action = min(records, key=lambda item: (item[1], item[2]))[0]
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
    if url["failure_code"] and url["failure_code"] not in {
        "scope_denied",
        "redirect_scope_denied",
        "unsafe_destination",
    }:
        values.add(Population.FAILED)
    if url["indexability_state"] == "indeterminate" or url["canonical_state"] == "indeterminate":
        values.add(Population.INDETERMINATE)
    return tuple(sorted(values, key=lambda item: item.value))


def _finding_definitions(
    pages: tuple[PageEvidenceListItem, ...],
    *,
    title_maximum: int = 60,
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
        if (
            page.parsed_as_html
            and page.title_value is not None
            and len(page.title_value) > title_maximum
        ):
            result.append(
                (
                    page,
                    "long_title",
                    "metadata",
                    "medium",
                    f"The page title exceeds the accepted {title_maximum}-character maximum.",
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
        "long_title": "Shorten the title while preserving a unique, descriptive label.",
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


def _decoded_json(value: object) -> object:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


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
