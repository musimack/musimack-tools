"""Restart-safe repository for bounded Combined Site Audit persistence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from musimack_tools.domain.site_audit_persistence import (
    MAX_SITE_AUDIT_URLS,
    SITE_AUDIT_POPULATION_VERSION,
    SITE_AUDIT_PRIORITY_VERSION,
    SITE_AUDIT_PROJECTION_VERSION,
    AuditLifecycle,
    Population,
    SiteAuditPersistenceError,
    canonical_json,
    normalized_url_identity,
    require_editable,
    snapshot_hash,
    validate_page_size,
    validate_transition,
)
from musimack_tools.persistence.site_audit_models import (
    SiteAuditArtifactAssociationModel,
    SiteAuditDisabledRuleModel,
    SiteAuditDiscoverySourceModel,
    SiteAuditFindingModel,
    SiteAuditIssueGroupModel,
    SiteAuditIssueMembershipModel,
    SiteAuditModel,
    SiteAuditModuleStatusModel,
    SiteAuditPopulationModel,
    SiteAuditRuleMatchModel,
    SiteAuditRuleSnapshotModel,
    SiteAuditSnapshotModel,
    SiteAuditSummaryModel,
    SiteAuditURLModel,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from musimack_tools.persistence.base import Base
    from musimack_tools.persistence.engine import PersistenceRuntime


class SQLAlchemySiteAuditRepository:
    """Owns transaction boundaries and preserves submitted history."""

    def __init__(self, runtime: PersistenceRuntime) -> None:
        self._runtime = runtime

    def create_audit(  # noqa: PLR0913
        self,
        audit_id: str,
        *,
        audit_name: str,
        site_label: str | None,
        seed_url: str,
        normalized_seed_url: str,
        draft: dict[str, Any],
        created_by: str,
        site_profile_id: str | None = None,
        site_profile_version: int | None = None,
        platform_preset_id: str | None = None,
        platform_preset_version: str | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        row = SiteAuditModel(
            audit_id=audit_id,
            audit_name=audit_name,
            site_label=site_label,
            seed_url=seed_url,
            normalized_seed_url=normalized_seed_url,
            lifecycle=AuditLifecycle.DRAFT.value,
            population_completeness="unavailable",
            module_completeness="unavailable",
            partial=False,
            draft_json=canonical_json(draft),
            draft_hash=snapshot_hash(draft),
            created_by=created_by,
            created_at=now,
            updated_at=now,
            projection_version=SITE_AUDIT_PROJECTION_VERSION,
            revision=1,
            site_profile_id=site_profile_id,
            site_profile_version=site_profile_version,
            platform_preset_id=platform_preset_id,
            platform_preset_version=platform_preset_version,
        )
        try:
            with self._runtime.transaction() as session:
                session.add(row)
                session.flush()
                return _audit_record(row)
        except IntegrityError as error:
            raise SiteAuditPersistenceError(
                "site_audit_conflict", "A Site Audit with this identity already exists."
            ) from error

    def audit(self, audit_id: str) -> dict[str, Any] | None:
        with self._runtime.transaction() as session:
            row = session.get(SiteAuditModel, audit_id)
            return _audit_record(row) if row else None

    def audits(
        self,
        *,
        page_size: int = 50,
        offset: int = 0,
        lifecycle: str | None = None,
        search: str | None = None,
    ) -> tuple[tuple[dict[str, Any], ...], int]:
        validate_page_size(page_size)
        if offset < 0:
            raise SiteAuditPersistenceError(
                "site_audit_invalid_pagination", "Pagination offset cannot be negative."
            )
        statement = select(SiteAuditModel)
        count = select(func.count()).select_from(SiteAuditModel)
        if lifecycle:
            statement = statement.where(SiteAuditModel.lifecycle == lifecycle)
            count = count.where(SiteAuditModel.lifecycle == lifecycle)
        if search:
            term = f"%{_safe_search(search)}%"
            condition = (
                SiteAuditModel.normalized_seed_url.ilike(term, escape="\\")
                | SiteAuditModel.audit_name.ilike(term, escape="\\")
                | SiteAuditModel.site_label.ilike(term, escape="\\")
            )
            statement = statement.where(condition)
            count = count.where(condition)
        statement = (
            statement.order_by(SiteAuditModel.created_at.desc(), SiteAuditModel.audit_id.desc())
            .offset(offset)
            .limit(page_size)
        )
        with self._runtime.transaction() as session:
            rows = session.execute(statement).scalars().all()
            return tuple(_audit_record(row) for row in rows), int(
                session.execute(count).scalar_one()
            )

    def update_draft(
        self,
        audit_id: str,
        draft: dict[str, Any],
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            row = self._audit_for_update(session, audit_id)
            self._require_no_snapshot(session, audit_id)
            require_editable(AuditLifecycle(row.lifecycle))
            if row.revision != expected_revision:
                raise SiteAuditPersistenceError(
                    "site_audit_revision_conflict", "The draft changed; reload before saving."
                )
            row.draft_json = canonical_json(draft)
            row.draft_hash = snapshot_hash(draft)
            row.revision += 1
            row.updated_at = datetime.now(UTC)
            if row.lifecycle != AuditLifecycle.DRAFT.value:
                row.lifecycle = AuditLifecycle.DRAFT.value
            session.flush()
            return _audit_record(row)

    def transition(
        self,
        audit_id: str,
        target: AuditLifecycle,
        *,
        expected_revision: int,
        failure_code: str | None = None,
        failure_explanation: str | None = None,
    ) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            row = self._audit_for_update(session, audit_id)
            if row.revision != expected_revision:
                raise SiteAuditPersistenceError(
                    "site_audit_revision_conflict", "The Site Audit changed; reload before saving."
                )
            current = AuditLifecycle(row.lifecycle)
            validate_transition(current, target)
            now = datetime.now(UTC)
            row.lifecycle = target.value
            row.failure_code = failure_code
            row.failure_explanation = failure_explanation
            row.updated_at = now
            row.revision += 1
            if target is AuditLifecycle.RUNNING:
                row.started_at = now
            if target in {
                AuditLifecycle.CANCELLED,
                AuditLifecycle.COMPLETED,
                AuditLifecycle.COMPLETED_WITH_WARNINGS,
                AuditLifecycle.PARTIALLY_COMPLETED,
                AuditLifecycle.FAILED,
            }:
                row.completed_at = now
            if target is AuditLifecycle.ARCHIVED:
                row.archived_at = now
            session.flush()
            return _audit_record(row)

    def create_snapshot(  # noqa: PLR0913
        self,
        audit_id: str,
        snapshot_id: str,
        configuration: dict[str, Any],
        *,
        expected_revision: int,
        rules: tuple[dict[str, Any], ...] = (),
        disabled_rules: tuple[dict[str, Any], ...] = (),
    ) -> dict[str, Any]:
        encoded = canonical_json(configuration)
        now = datetime.now(UTC)
        try:
            with self._runtime.transaction() as session:
                audit = self._audit_for_update(session, audit_id)
                self._require_no_snapshot(session, audit_id)
                if audit.revision != expected_revision:
                    raise SiteAuditPersistenceError(
                        "site_audit_revision_conflict",
                        "The draft changed; reload before submitting.",
                    )
                if AuditLifecycle(audit.lifecycle) is not AuditLifecycle.READY:
                    raise SiteAuditPersistenceError(
                        "site_audit_not_ready", "Only a ready Site Audit may be snapshotted."
                    )
                row = SiteAuditSnapshotModel(
                    snapshot_id=snapshot_id,
                    audit_id=audit_id,
                    source_revision=audit.revision,
                    canonical_json=encoded,
                    sha256=snapshot_hash(configuration),
                    approved_hosts_json=canonical_json(configuration.get("approved_hosts", [])),
                    scope_policy_json=canonical_json(configuration.get("scope_policy", {})),
                    crawl_limits_json=canonical_json(configuration.get("crawl_limits", {})),
                    thresholds_json=canonical_json(configuration.get("thresholds", {})),
                    enabled_modules_json=canonical_json(configuration.get("enabled_modules", [])),
                    tracking_parameters_json=canonical_json(
                        configuration.get("tracking_parameters", {})
                    ),
                    population_definition_version=str(
                        configuration.get(
                            "population_definition_version", SITE_AUDIT_POPULATION_VERSION
                        )
                    ),
                    priority_model_version=str(
                        configuration.get("priority_model_version", SITE_AUDIT_PRIORITY_VERSION)
                    ),
                    artifact_schema_versions_json=canonical_json(
                        configuration.get("artifact_schema_versions", {})
                    ),
                    application_version=str(configuration.get("application_version", "unknown")),
                    projection_version=str(
                        configuration.get("projection_version", SITE_AUDIT_PROJECTION_VERSION)
                    ),
                    site_profile_id=audit.site_profile_id,
                    site_profile_version=audit.site_profile_version,
                    platform_preset_id=audit.platform_preset_id,
                    platform_preset_version=audit.platform_preset_version,
                    created_at=now,
                )
                session.add(row)
                # SQLAlchemy has no ORM relationships here by design; materialize the immutable
                # parent before inserting its normalized child rows.
                session.flush()
                for order, rule in enumerate(rules):
                    session.add(_rule_snapshot(row, audit_id, rule, order))
                for disabled in disabled_rules:
                    session.add(
                        SiteAuditDisabledRuleModel(
                            snapshot_id=snapshot_id,
                            audit_id=audit_id,
                            stable_rule_id=str(disabled["stable_rule_id"]),
                            rule_source=str(disabled["rule_source"]),
                            source_version=str(disabled["source_version"]),
                            reason_code=str(disabled.get("reason_code", "disabled_by_override")),
                        )
                    )
                audit.submitted_at = now
                audit.updated_at = now
                audit.revision += 1
                session.flush()
                return _snapshot_record(row)
        except IntegrityError as error:
            raise SiteAuditPersistenceError(
                "site_audit_snapshot_conflict", "The immutable snapshot could not be created."
            ) from error

    def snapshot(self, audit_id: str) -> dict[str, Any] | None:
        with self._runtime.transaction() as session:
            row = session.execute(
                select(SiteAuditSnapshotModel).where(SiteAuditSnapshotModel.audit_id == audit_id)
            ).scalar_one_or_none()
            if row is None:
                return None
            rules = session.execute(
                select(SiteAuditRuleSnapshotModel)
                .where(SiteAuditRuleSnapshotModel.snapshot_id == row.snapshot_id)
                .order_by(SiteAuditRuleSnapshotModel.stable_order)
            ).scalars()
            disabled = session.execute(
                select(SiteAuditDisabledRuleModel)
                .where(SiteAuditDisabledRuleModel.snapshot_id == row.snapshot_id)
                .order_by(SiteAuditDisabledRuleModel.stable_rule_id)
            ).scalars()
            result = _snapshot_record(row)
            result["rules"] = tuple(_model_dict(item) for item in rules)
            result["disabled_inherited_rules"] = tuple(_model_dict(item) for item in disabled)
            return result

    def add_url(  # noqa: PLR0913
        self,
        audit_id: str,
        url_id: str,
        *,
        sequence: int,
        original_url: str,
        requested_url: str,
        normalized_url: str,
        values: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        values = values or {}
        parsed = urlsplit(normalized_url)
        now = datetime.now(UTC)
        try:
            with self._runtime.transaction() as session:
                self._audit_for_update(session, audit_id)
                total = session.execute(
                    select(func.count())
                    .select_from(SiteAuditURLModel)
                    .where(SiteAuditURLModel.audit_id == audit_id)
                ).scalar_one()
                if int(total) >= MAX_SITE_AUDIT_URLS:
                    raise SiteAuditPersistenceError(
                        "site_audit_url_limit_reached", "The retained URL limit has been reached."
                    )
                row = SiteAuditURLModel(
                    url_id=url_id,
                    audit_id=audit_id,
                    sequence=sequence,
                    original_url=original_url,
                    requested_url=requested_url,
                    normalized_url=normalized_url,
                    normalized_url_identity=normalized_url_identity(normalized_url),
                    final_url=values.get("final_url"),
                    host=parsed.hostname or "",
                    path=parsed.path or "/",
                    query=parsed.query,
                    discovery_state=str(values.get("discovery_state", "discovered")),
                    enqueued_state=str(values.get("enqueued_state", "not_enqueued")),
                    fetch_state=str(values.get("fetch_state", "not_fetched")),
                    parse_state=str(values.get("parse_state", "not_parsed")),
                    http_status=values.get("http_status"),
                    content_type=values.get("content_type"),
                    fetch_outcome=values.get("fetch_outcome"),
                    redirect_state=str(values.get("redirect_state", "not_observed")),
                    robots_state=str(values.get("robots_state", "unavailable")),
                    indexability_state=str(values.get("indexability_state", "indeterminate")),
                    canonical_state=str(values.get("canonical_state", "indeterminate")),
                    existing_sitemap_state=str(
                        values.get("existing_sitemap_state", "indeterminate")
                    ),
                    recommended_sitemap_state=str(
                        values.get("recommended_sitemap_state", "indeterminate")
                    ),
                    discovery_decision=str(values.get("discovery_decision", "enqueue")),
                    metadata_scoring_decision=str(
                        values.get("metadata_scoring_decision", "indeterminate")
                    ),
                    sitemap_policy_decision=str(
                        values.get("sitemap_policy_decision", "indeterminate")
                    ),
                    highest_severity=values.get("highest_severity"),
                    issue_count=int(values.get("issue_count", 0)),
                    crawl_depth=values.get("crawl_depth"),
                    inbound_link_count=int(values.get("inbound_link_count", 0)),
                    outbound_link_count=int(values.get("outbound_link_count", 0)),
                    partial=bool(values.get("partial", False)),
                    failure_code=values.get("failure_code"),
                    business_importance=str(values.get("business_importance", "not_assigned")),
                    evidence_id=values.get("evidence_id"),
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
                session.flush()
                return _model_dict(row)
        except IntegrityError as error:
            raise SiteAuditPersistenceError(
                "site_audit_duplicate_normalized_url",
                "This normalized URL already exists in the Site Audit.",
            ) from error

    def urls(  # noqa: PLR0913
        self,
        audit_id: str,
        *,
        page_size: int = 50,
        offset: int = 0,
        url_text: str | None = None,
        http_status: int | None = None,
        sitemap_state: str | None = None,
        only_partial: bool | None = None,
    ) -> tuple[tuple[dict[str, Any], ...], int]:
        validate_page_size(page_size)
        if offset < 0:
            raise SiteAuditPersistenceError("site_audit_invalid_pagination", "Invalid offset.")
        statement = select(SiteAuditURLModel).where(SiteAuditURLModel.audit_id == audit_id)
        count = (
            select(func.count())
            .select_from(SiteAuditURLModel)
            .where(SiteAuditURLModel.audit_id == audit_id)
        )
        if url_text:
            url_condition = SiteAuditURLModel.normalized_url.ilike(
                f"%{_safe_search(url_text)}%", escape="\\"
            )
            statement = statement.where(url_condition)
            count = count.where(url_condition)
        if http_status is not None:
            status_condition = SiteAuditURLModel.http_status == http_status
            statement = statement.where(status_condition)
            count = count.where(status_condition)
        if sitemap_state:
            sitemap_condition = SiteAuditURLModel.recommended_sitemap_state == sitemap_state
            statement = statement.where(sitemap_condition)
            count = count.where(sitemap_condition)
        if only_partial is not None:
            partial_condition = SiteAuditURLModel.partial == only_partial
            statement = statement.where(partial_condition)
            count = count.where(partial_condition)
        statement = statement.order_by(SiteAuditURLModel.sequence, SiteAuditURLModel.url_id)
        with self._runtime.transaction() as session:
            self._audit_for_update(session, audit_id)
            rows = session.execute(statement.offset(offset).limit(page_size)).scalars()
            return tuple(_model_dict(row) for row in rows), int(session.execute(count).scalar_one())

    def add_discovery(self, audit_id: str, url_id: str, record: dict[str, Any]) -> dict[str, Any]:
        try:
            with self._runtime.transaction() as session:
                self._require_url(session, audit_id, url_id)
                row = SiteAuditDiscoverySourceModel(
                    discovery_id=str(record["discovery_id"]),
                    audit_id=audit_id,
                    url_id=url_id,
                    sequence=int(record["sequence"]),
                    source_type=str(record["source_type"]),
                    source_url=record.get("source_url"),
                    source_artifact_id=record.get("source_artifact_id"),
                    source_evidence_id=record.get("source_evidence_id"),
                    discovered_at=record.get("discovered_at", datetime.now(UTC)),
                    original_observed_url=str(record["original_observed_url"]),
                    relationship_json=canonical_json(record.get("relationship", {})),
                    evidence_key=snapshot_hash(
                        {
                            "source_type": record["source_type"],
                            "source_url": record.get("source_url"),
                            "source_artifact_id": record.get("source_artifact_id"),
                            "source_evidence_id": record.get("source_evidence_id"),
                            "original_observed_url": record["original_observed_url"],
                        }
                    ),
                )
                session.add(row)
                session.flush()
                return _model_dict(row)
        except IntegrityError as error:
            raise SiteAuditPersistenceError(
                "site_audit_discovery_conflict", "This discovery evidence is already retained."
            ) from error

    def set_populations(
        self, audit_id: str, url_id: str, populations: tuple[Population, ...]
    ) -> tuple[str, ...]:
        with self._runtime.transaction() as session:
            self._require_url(session, audit_id, url_id)
            existing = {
                row.population
                for row in session.execute(
                    select(SiteAuditPopulationModel).where(
                        SiteAuditPopulationModel.url_id == url_id
                    )
                ).scalars()
            }
            now = datetime.now(UTC)
            for population in populations:
                if population.value not in existing:
                    session.add(
                        SiteAuditPopulationModel(
                            audit_id=audit_id,
                            url_id=url_id,
                            population=population.value,
                            decision_state="member",
                            definition_version=SITE_AUDIT_POPULATION_VERSION,
                            created_at=now,
                        )
                    )
            session.flush()
            return tuple(sorted(existing | {item.value for item in populations}))

    def add_rule_match(self, audit_id: str, url_id: str, record: dict[str, Any]) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            self._require_url(session, audit_id, url_id)
            rule = session.get(SiteAuditRuleSnapshotModel, str(record["snapshot_rule_id"]))
            if rule is None or rule.audit_id != audit_id:
                raise SiteAuditPersistenceError(
                    "site_audit_rule_snapshot_not_found", "The snapshotted rule was not found."
                )
            row = SiteAuditRuleMatchModel(
                match_id=str(record["match_id"]),
                audit_id=audit_id,
                url_id=url_id,
                snapshot_rule_id=rule.snapshot_rule_id,
                decision_layer=str(record.get("decision_layer", rule.decision_layer)),
                primary_rule=bool(record.get("primary_rule", False)),
                contributed=bool(record.get("contributed", True)),
                disabled=bool(record.get("disabled", False)),
                overridden=bool(record.get("overridden", False)),
                specificity=int(record.get("specificity", rule.specificity)),
                priority=int(record.get("priority", rule.priority)),
                precedence_key=str(record.get("precedence_key", rule.stable_rule_id)),
                conflict_code=record.get("conflict_code"),
                reason=str(record.get("reason", rule.explanation)),
                matched_original_url=str(record["matched_original_url"]),
                matched_normalized_url=str(record["matched_normalized_url"]),
                matched_at=record.get("matched_at", datetime.now(UTC)),
            )
            session.add(row)
            try:
                session.flush()
            except IntegrityError as error:
                raise SiteAuditPersistenceError(
                    "site_audit_rule_match_conflict_invalid",
                    "This rule match is already retained or conflicts with its snapshot.",
                ) from error
            return _model_dict(row)

    def rule_matches(
        self, audit_id: str, *, page_size: int = 50, offset: int = 0
    ) -> tuple[dict[str, Any], ...]:
        validate_page_size(page_size)
        with self._runtime.transaction() as session:
            rows = session.execute(
                select(SiteAuditRuleMatchModel)
                .join(SiteAuditURLModel, SiteAuditURLModel.url_id == SiteAuditRuleMatchModel.url_id)
                .where(SiteAuditRuleMatchModel.audit_id == audit_id)
                .order_by(
                    SiteAuditURLModel.sequence,
                    SiteAuditRuleMatchModel.decision_layer,
                    SiteAuditRuleMatchModel.precedence_key,
                    SiteAuditRuleMatchModel.match_id,
                )
                .offset(offset)
                .limit(page_size)
            ).scalars()
            return tuple(_model_dict(row) for row in rows)

    def add_finding(self, audit_id: str, record: dict[str, Any]) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            self._audit_for_update(session, audit_id)
            row = SiteAuditFindingModel(
                finding_id=str(record["finding_id"]),
                audit_id=audit_id,
                url_id=record.get("url_id"),
                module=str(record["module"]),
                category=str(record["category"]),
                code=str(record["code"]),
                severity=str(record["severity"]),
                determinacy=str(record.get("determinacy", "determinate")),
                confidence=str(record.get("confidence", "high")),
                explanation=str(record["explanation"]),
                evidence_reference=record.get("evidence_reference"),
                sitemap_impact=bool(record.get("sitemap_impact", False)),
                metadata_impact=bool(record.get("metadata_impact", False)),
                indexability_impact=bool(record.get("indexability_impact", False)),
                created_at=record.get("created_at", datetime.now(UTC)),
                projection_version=str(
                    record.get("projection_version", SITE_AUDIT_PROJECTION_VERSION)
                ),
            )
            session.add(row)
            session.flush()
            return _model_dict(row)

    def upsert_issue_group(self, audit_id: str, record: dict[str, Any]) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            self._audit_for_update(session, audit_id)
            group_id = str(record["group_id"])
            row = session.get(SiteAuditIssueGroupModel, group_id)
            now = datetime.now(UTC)
            values = _issue_group_values(audit_id, record, now)
            if row is None:
                row = SiteAuditIssueGroupModel(group_id=group_id, **values)
                session.add(row)
            else:
                if row.audit_id != audit_id:
                    raise SiteAuditPersistenceError(
                        "site_audit_issue_group_not_found", "The issue group was not found."
                    )
                for key, value in values.items():
                    if key != "created_at":
                        setattr(row, key, value)
            session.flush()
            return _model_dict(row)

    def add_issue_membership(
        self, audit_id: str, group_id: str, finding_id: str, *, sequence: int, reason: str
    ) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            group = session.get(SiteAuditIssueGroupModel, group_id)
            finding = session.get(SiteAuditFindingModel, finding_id)
            if (
                group is None
                or group.audit_id != audit_id
                or finding is None
                or finding.audit_id != audit_id
            ):
                raise SiteAuditPersistenceError(
                    "site_audit_issue_group_not_found", "The issue group or finding was not found."
                )
            row = SiteAuditIssueMembershipModel(
                group_id=group_id,
                finding_id=finding_id,
                url_id=finding.url_id,
                sequence=sequence,
                membership_reason=reason,
                created_at=datetime.now(UTC),
            )
            session.add(row)
            try:
                session.flush()
            except IntegrityError as error:
                raise SiteAuditPersistenceError(
                    "site_audit_issue_membership_conflict",
                    "The finding is already a member of this issue group.",
                ) from error
            return _model_dict(row)

    def issue_groups(
        self, audit_id: str, *, page_size: int = 50, offset: int = 0
    ) -> tuple[dict[str, Any], ...]:
        validate_page_size(page_size)
        with self._runtime.transaction() as session:
            rows = session.execute(
                select(SiteAuditIssueGroupModel)
                .where(SiteAuditIssueGroupModel.audit_id == audit_id)
                .order_by(SiteAuditIssueGroupModel.priority_key, SiteAuditIssueGroupModel.group_id)
                .offset(offset)
                .limit(page_size)
            ).scalars()
            return tuple(_model_dict(row) for row in rows)

    def upsert_module_status(self, audit_id: str, record: dict[str, Any]) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            self._audit_for_update(session, audit_id)
            row = session.execute(
                select(SiteAuditModuleStatusModel).where(
                    SiteAuditModuleStatusModel.audit_id == audit_id,
                    SiteAuditModuleStatusModel.module == str(record["module"]),
                )
            ).scalar_one_or_none()
            values = {
                "execution_source": str(record.get("execution_source", "retained_evidence")),
                "specialist_audit_id": record.get("specialist_audit_id"),
                "lifecycle": str(record.get("lifecycle", "not_started")),
                "completeness": str(record.get("completeness", "unavailable")),
                "partial": bool(record.get("partial", False)),
                "started_at": record.get("started_at"),
                "completed_at": record.get("completed_at"),
                "failure_code": record.get("failure_code"),
                "failure_explanation": record.get("failure_explanation"),
                "result_count": int(record.get("result_count", 0)),
                "artifact_count": int(record.get("artifact_count", 0)),
                "projection_version": str(
                    record.get("projection_version", SITE_AUDIT_PROJECTION_VERSION)
                ),
                "updated_at": datetime.now(UTC),
            }
            if row is None:
                row = SiteAuditModuleStatusModel(
                    audit_id=audit_id, module=str(record["module"]), **values
                )
                session.add(row)
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            session.flush()
            return _model_dict(row)

    def module_statuses(self, audit_id: str) -> tuple[dict[str, Any], ...]:
        with self._runtime.transaction() as session:
            rows = session.execute(
                select(SiteAuditModuleStatusModel)
                .where(SiteAuditModuleStatusModel.audit_id == audit_id)
                .order_by(SiteAuditModuleStatusModel.module)
            ).scalars()
            return tuple(_model_dict(row) for row in rows)

    def rebuild_summary(
        self, audit_id: str, *, expected_revision: int | None = None
    ) -> dict[str, Any]:
        """Rebuild normalized counts atomically; repeated rebuilds produce equal counts."""
        with self._runtime.transaction() as session:
            self._audit_for_update(session, audit_id)
            current = session.get(SiteAuditSummaryModel, audit_id)
            if expected_revision is not None:
                actual = current.revision if current else 0
                if actual != expected_revision:
                    raise SiteAuditPersistenceError(
                        "site_audit_projection_version_conflict",
                        "The summary projection changed; reload before rebuilding.",
                    )
            population_counts: dict[str, int] = {
                key: int(value)
                for key, value in session.execute(
                    select(SiteAuditPopulationModel.population, func.count())
                    .where(SiteAuditPopulationModel.audit_id == audit_id)
                    .group_by(SiteAuditPopulationModel.population)
                ).tuples()
            }
            severity_counts: dict[str, int] = {
                key: int(value)
                for key, value in session.execute(
                    select(SiteAuditIssueGroupModel.severity, func.count())
                    .where(SiteAuditIssueGroupModel.audit_id == audit_id)
                    .group_by(SiteAuditIssueGroupModel.severity)
                ).tuples()
            }
            recommendation_counts: dict[str, int] = {
                key: int(value)
                for key, value in session.execute(
                    select(SiteAuditURLModel.recommended_sitemap_state, func.count())
                    .where(SiteAuditURLModel.audit_id == audit_id)
                    .group_by(SiteAuditURLModel.recommended_sitemap_state)
                ).tuples()
            }
            module_counts: dict[str, int] = {
                key: int(value)
                for key, value in session.execute(
                    select(SiteAuditModuleStatusModel.completeness, func.count())
                    .where(SiteAuditModuleStatusModel.audit_id == audit_id)
                    .group_by(SiteAuditModuleStatusModel.completeness)
                ).tuples()
            }
            group_membership_counts = {
                group_id: int(value)
                for group_id, value in session.execute(
                    select(
                        SiteAuditIssueGroupModel.group_id,
                        func.count(func.distinct(SiteAuditIssueMembershipModel.url_id)),
                    )
                    .outerjoin(
                        SiteAuditIssueMembershipModel,
                        SiteAuditIssueMembershipModel.group_id == SiteAuditIssueGroupModel.group_id,
                    )
                    .where(SiteAuditIssueGroupModel.audit_id == audit_id)
                    .group_by(SiteAuditIssueGroupModel.group_id)
                ).tuples()
            }
            for group in session.execute(
                select(SiteAuditIssueGroupModel).where(
                    SiteAuditIssueGroupModel.audit_id == audit_id
                )
            ).scalars():
                group.affected_url_count = group_membership_counts.get(group.group_id, 0)
            values = _summary_values(
                population_counts, severity_counts, recommendation_counts, module_counts
            )
            now = datetime.now(UTC)
            if current is None:
                current = SiteAuditSummaryModel(
                    audit_id=audit_id,
                    **values,
                    image_summary_json="{}",
                    structured_data_summary_json="{}",
                    module_counts_json=canonical_json(module_counts),
                    projection_version=SITE_AUDIT_PROJECTION_VERSION,
                    revision=1,
                    updated_at=now,
                )
                session.add(current)
            else:
                for key, value in values.items():
                    setattr(current, key, value)
                current.module_counts_json = canonical_json(module_counts)
                current.revision += 1
                current.updated_at = now
            session.flush()
            return _model_dict(current)

    def summary(self, audit_id: str) -> dict[str, Any] | None:
        with self._runtime.transaction() as session:
            row = session.get(SiteAuditSummaryModel, audit_id)
            return _model_dict(row) if row else None

    def associate_artifact(  # noqa: PLR0913
        self,
        audit_id: str,
        artifact_id: str,
        *,
        purpose: str,
        schema_version: str,
        completeness: str,
        row_count: int | None = None,
        truncated: bool = False,
    ) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            self._audit_for_update(session, audit_id)
            row = SiteAuditArtifactAssociationModel(
                audit_id=audit_id,
                artifact_id=artifact_id,
                purpose=purpose,
                schema_version=schema_version,
                completeness=completeness,
                row_count=row_count,
                truncated=truncated,
                created_at=datetime.now(UTC),
            )
            session.add(row)
            try:
                session.flush()
            except IntegrityError as error:
                raise SiteAuditPersistenceError(
                    "site_audit_artifact_association_invalid",
                    "The artifact association is invalid or already retained.",
                ) from error
            return _model_dict(row)

    @staticmethod
    def _audit_for_update(session: Session, audit_id: str) -> SiteAuditModel:
        row = session.get(SiteAuditModel, audit_id)
        if row is None:
            raise SiteAuditPersistenceError("site_audit_not_found", "The Site Audit was not found.")
        return row

    @staticmethod
    def _require_no_snapshot(session: Session, audit_id: str) -> None:
        present = session.execute(
            select(SiteAuditSnapshotModel.snapshot_id).where(
                SiteAuditSnapshotModel.audit_id == audit_id
            )
        ).scalar_one_or_none()
        if present is not None:
            raise SiteAuditPersistenceError(
                "site_audit_snapshot_immutable", "Submitted Site Audit snapshots are immutable."
            )

    @staticmethod
    def _require_url(session: Session, audit_id: str, url_id: str) -> SiteAuditURLModel:
        row = session.get(SiteAuditURLModel, url_id)
        if row is None or row.audit_id != audit_id:
            raise SiteAuditPersistenceError(
                "site_audit_url_not_found", "The Site Audit URL was not found."
            )
        return row


def _rule_snapshot(
    snapshot: SiteAuditSnapshotModel, audit_id: str, rule: dict[str, Any], order: int
) -> SiteAuditRuleSnapshotModel:
    stable_rule_id = str(rule["stable_rule_id"])
    return SiteAuditRuleSnapshotModel(
        snapshot_rule_id=snapshot_hash(
            {"snapshot_id": snapshot.snapshot_id, "stable_rule_id": stable_rule_id}
        ),
        snapshot_id=snapshot.snapshot_id,
        audit_id=audit_id,
        stable_rule_id=stable_rule_id,
        rule_source=str(rule["rule_source"]),
        source_id=rule.get("source_id"),
        source_version=str(rule["source_version"]),
        decision_layer=str(rule["decision_layer"]),
        match_type=str(rule["match_type"]),
        match_value=str(rule["match_value"]),
        action=str(rule["action"]),
        enabled=bool(rule.get("enabled", True)),
        priority=int(rule.get("priority", 0)),
        specificity=int(rule.get("specificity", 0)),
        reason_code=str(rule["reason_code"]),
        explanation=str(rule["explanation"]),
        overrides_rule_ids_json=canonical_json(rule.get("overrides_rule_ids", [])),
        stable_order=order,
    )


def _issue_group_values(audit_id: str, record: dict[str, Any], now: datetime) -> dict[str, Any]:
    return {
        "audit_id": audit_id,
        "category": str(record["category"]),
        "code": str(record["code"]),
        "remediation_key": str(record["remediation_key"]),
        "applicable_population": str(record["applicable_population"]),
        "title": str(record["title"]),
        "explanation": str(record["explanation"]),
        "severity": str(record["severity"]),
        "affected_url_count": int(record.get("affected_url_count", 0)),
        "highest_business_importance": str(
            record.get("highest_business_importance", "not_assigned")
        ),
        "pattern_state": str(record.get("pattern_state", "none")),
        "sitemap_impact": bool(record.get("sitemap_impact", False)),
        "metadata_impact": bool(record.get("metadata_impact", False)),
        "indexability_impact": bool(record.get("indexability_impact", False)),
        "internal_link_impact": bool(record.get("internal_link_impact", False)),
        "confidence": str(record.get("confidence", "high")),
        "determinacy": str(record.get("determinacy", "determinate")),
        "priority_band": str(record.get("priority_band", record["severity"])),
        "priority_key": str(record["priority_key"]),
        "priority_explanation": str(record["priority_explanation"]),
        "recommended_action": str(record["recommended_action"]),
        "sample_urls_json": canonical_json(record.get("sample_urls", [])),
        "created_at": record.get("created_at", now),
        "updated_at": now,
        "projection_version": str(record.get("projection_version", SITE_AUDIT_PROJECTION_VERSION)),
    }


def _summary_values(
    population: dict[str, int],
    severity: dict[str, int],
    recommendations: dict[str, int],
    _modules: dict[str, int],
) -> dict[str, int]:
    return {
        "urls_discovered": population.get(Population.DISCOVERED.value, 0),
        "urls_enqueued": population.get(Population.ENQUEUED.value, 0),
        "urls_fetched": population.get(Population.FETCHED.value, 0),
        "html_urls": population.get(Population.PARSED_HTML.value, 0),
        "indexable_urls": population.get(Population.INDEXABLE.value, 0),
        "canonical_urls": population.get(Population.CANONICAL.value, 0),
        "metadata_scoring_eligible_urls": population.get(
            Population.METADATA_SCORING_ELIGIBLE.value, 0
        ),
        "sitemap_eligible_urls": population.get(Population.SITEMAP_ELIGIBLE.value, 0),
        "urls_excluded": population.get(Population.EXCLUDED.value, 0),
        "partial_urls": population.get(Population.PARTIAL.value, 0),
        "failed_urls": population.get(Population.FAILED.value, 0),
        "indeterminate_urls": population.get(Population.INDETERMINATE.value, 0),
        "critical_issue_groups": severity.get("critical", 0),
        "high_issue_groups": severity.get("high", 0),
        "medium_issue_groups": severity.get("medium", 0),
        "low_issue_groups": severity.get("low", 0),
        "unassigned_issue_groups": severity.get("informational", 0) + severity.get("unassigned", 0),
        "recommendation_include": recommendations.get("include", 0),
        "recommendation_exclude": recommendations.get("exclude", 0),
        "recommendation_review": recommendations.get("review", 0),
        "recommendation_indeterminate": recommendations.get("indeterminate", 0),
    }


def _audit_record(row: SiteAuditModel) -> dict[str, Any]:
    result = _model_dict(row)
    result["draft"] = json.loads(row.draft_json)
    result.pop("draft_json")
    return result


def _snapshot_record(row: SiteAuditSnapshotModel) -> dict[str, Any]:
    result = _model_dict(row)
    result["configuration"] = json.loads(row.canonical_json)
    return result


def _model_dict(row: Base) -> dict[str, Any]:
    return {
        column.name: (
            value.isoformat() if isinstance(value := getattr(row, column.name), datetime) else value
        )
        for column in row.__table__.columns
    }


def _safe_search(value: str) -> str:
    return value[:256].replace("%", "\\%").replace("_", "\\_")
