"""Bounded specialist-audit selection without transferring evidence ownership."""

from __future__ import annotations

import inspect
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from musimack_tools.domain.site_audit_orchestration import SiteAuditStage  # noqa: TC001

_PAGE_SIZE = 500
_UNSUPPORTED_RECORD = "Specialist authority returned an unsupported record."


@dataclass(frozen=True, slots=True)
class SpecialistEvidence:
    module: SiteAuditStage
    specialist_audit_id: str | None
    execution_source: str
    eligibility_state: str
    eligibility_reason: str
    freshness_state: str
    lifecycle_state: str
    partial: bool
    evidence_count: int
    artifact_count: int = 0
    documents: tuple[dict[str, Any], ...] = ()
    entries: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class SpecialistRequest:
    module: SiteAuditStage
    run_id: str
    seed_url: str
    approved_hosts: tuple[str, ...]
    associated: dict[str, Any] | None
    configured_audit_id: str | None
    allow_launch: bool


class SiteAuditSpecialistGateway(Protocol):
    async def resolve(self, request: SpecialistRequest) -> SpecialistEvidence: ...


class SpecialistAuthority:
    """Normalize one existing specialist repository/service behind a safe contract."""

    def __init__(  # noqa: PLR0913 - repository capabilities are explicit and bounded.
        self,
        repository: object,
        *,
        list_method: str = "list_audits",
        document_method: str | None = None,
        entry_method: str | None = None,
        launch: object | None = None,
        paginated_list: bool = True,
    ) -> None:
        self.repository = repository
        self.list_method = list_method
        self.document_method = document_method
        self.entry_method = entry_method
        self.launch = launch
        self.paginated_list = paginated_list

    def get(self, audit_id: str) -> dict[str, Any] | None:
        value = getattr(self.repository, "get")(audit_id)  # noqa: B009
        return None if value is None else _mapping(value)

    def list(self) -> tuple[dict[str, Any], ...]:
        method = getattr(self.repository, self.list_method)
        values = method(0, 100) if self.paginated_list else method()
        return tuple(_mapping(value) for value in values)

    def documents(self, audit_id: str) -> tuple[dict[str, Any], ...]:
        return self._paged(self.document_method, audit_id)

    def entries(self, audit_id: str) -> tuple[dict[str, Any], ...]:
        return self._paged(self.entry_method, audit_id)

    async def launch_for_run(self, run_id: str) -> dict[str, Any] | None:
        if self.launch is None:
            return None
        value = self.launch(run_id)  # type: ignore[operator]
        if inspect.isawaitable(value):
            value = await value
        return None if value is None else _mapping(value)

    @property
    def launch_available(self) -> bool:
        return self.launch is not None

    def _paged(self, method_name: str | None, audit_id: str) -> tuple[dict[str, Any], ...]:
        if method_name is None:
            return ()
        method = getattr(self.repository, method_name)
        result: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = tuple(method(audit_id, offset, _PAGE_SIZE))
            result.extend(_mapping(value) for value in page)
            if len(page) < _PAGE_SIZE:
                return tuple(result)
            offset += len(page)


class SQLAlchemySiteAuditSpecialistGateway:
    """Choose linked, prior, or newly launched specialist evidence deterministically."""

    def __init__(
        self,
        authorities: dict[SiteAuditStage, SpecialistAuthority],
        *,
        maximum_age_days: int = 30,
    ) -> None:
        self._authorities = authorities
        self._maximum_age = timedelta(days=maximum_age_days)

    async def resolve(self, request: SpecialistRequest) -> SpecialistEvidence:
        module = request.module
        run_id = request.run_id
        seed_url = request.seed_url
        _ = request.approved_hosts  # Exact run identity is stricter than host compatibility.
        authority = self._authorities.get(module)
        if authority is None:
            return _unavailable(module, "specialist_authority_unavailable")
        candidate_id = (
            str(request.associated["specialist_audit_id"])
            if request.associated and request.associated.get("specialist_audit_id")
            else request.configured_audit_id
        )
        source = (
            str(request.associated.get("execution_source", "linked_child"))
            if request.associated
            else "linked_child"
        )
        candidate = authority.get(candidate_id) if candidate_id else None
        if candidate_id and candidate is None:
            return _unavailable(module, "linked_specialist_missing", audit_id=candidate_id)
        if candidate is None:
            eligible = [
                item
                for item in authority.list()
                if str(item.get("run_id")) == run_id and _seed_matches(item, seed_url)
            ]
            eligible.sort(
                key=lambda item: (
                    str(item.get("completed_at") or item.get("created_at") or ""),
                    str(item.get("audit_id")),
                ),
                reverse=True,
            )
            candidate = eligible[0] if eligible else None
            source = "eligible_prior"
        if candidate is None and request.allow_launch:
            if not authority.launch_available:
                return SpecialistEvidence(
                    module=module,
                    specialist_audit_id=None,
                    execution_source="linked_child",
                    eligibility_state="eligible",
                    eligibility_reason="specialist_launch_pending_worker",
                    freshness_state="current",
                    lifecycle_state="accepted",
                    partial=False,
                    evidence_count=0,
                )
            candidate = await authority.launch_for_run(run_id)
            source = "linked_child"
        if candidate is None:
            return _unavailable(module, "no_compatible_specialist_audit")
        return self._projection(module, authority, candidate, source, run_id, seed_url)

    def _projection(  # noqa: PLR0913 - normalized projection inputs are explicit.
        self,
        module: SiteAuditStage,
        authority: SpecialistAuthority,
        candidate: dict[str, Any],
        source: str,
        run_id: str,
        seed_url: str,
    ) -> SpecialistEvidence:
        audit_id = str(candidate.get("audit_id"))
        if str(candidate.get("run_id")) != run_id or not _seed_matches(candidate, seed_url):
            return _unavailable(module, "specialist_identity_incompatible", audit_id=audit_id)
        freshness = _freshness(candidate, self._maximum_age)
        if freshness == "stale":
            return SpecialistEvidence(
                module=module,
                specialist_audit_id=audit_id,
                execution_source=source,
                eligibility_state="ineligible",
                eligibility_reason="specialist_evidence_stale",
                freshness_state=freshness,
                lifecycle_state=str(candidate.get("state", "unknown")),
                partial=bool(candidate.get("partial", False)),
                evidence_count=0,
            )
        lifecycle = str(candidate.get("state", "unknown"))
        documents = authority.documents(audit_id)
        entries = authority.entries(audit_id)
        count = int(
            candidate.get("unique_url_count")
            or candidate.get("page_count")
            or candidate.get("target_count")
            or candidate.get("resource_count")
            or candidate.get("entity_count")
            or len(entries)
        )
        partial = bool(candidate.get("partial", False)) or lifecycle == "partially_completed"
        reason = "same_crawl_run" if source == "eligible_prior" else "linked_specialist_audit"
        return SpecialistEvidence(
            module,
            audit_id,
            source,
            "eligible",
            reason,
            freshness,
            lifecycle,
            partial,
            count,
            documents=documents,
            entries=entries,
        )


def _mapping(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    raise TypeError(_UNSUPPORTED_RECORD)


def _seed_matches(candidate: dict[str, Any], seed_url: str) -> bool:
    value = candidate.get("seed_url")
    return value is None or str(value) == seed_url


def _freshness(candidate: dict[str, Any], maximum_age: timedelta) -> str:
    value = candidate.get("completed_at") or candidate.get("created_at")
    if not isinstance(value, str):
        if isinstance(value, datetime):
            completed = value
        else:
            return "unknown"
    else:
        try:
            completed = datetime.fromisoformat(value)
        except ValueError:
            return "unknown"
    if completed.tzinfo is None:
        completed = completed.replace(tzinfo=UTC)
    return "stale" if datetime.now(UTC) - completed > maximum_age else "current"


def _unavailable(
    module: SiteAuditStage, reason: str, *, audit_id: str | None = None
) -> SpecialistEvidence:
    return SpecialistEvidence(
        module=module,
        specialist_audit_id=audit_id,
        execution_source="unavailable",
        eligibility_state="unavailable",
        eligibility_reason=reason,
        freshness_state="unknown",
        lifecycle_state="unavailable",
        partial=False,
        evidence_count=0,
    )
