"""Focused CSA-04 specialist selection and provenance tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from musimack_tools.domain.site_audit_orchestration import SiteAuditStage
from musimack_tools.site_audit.specialists import (
    SpecialistAuthority,
    SpecialistRequest,
    SQLAlchemySiteAuditSpecialistGateway,
)


class _Repository:
    def __init__(self, audits: tuple[dict[str, Any], ...]) -> None:
        self.audits = audits

    def get(self, audit_id: str) -> dict[str, Any] | None:
        return next((item for item in self.audits if item["audit_id"] == audit_id), None)

    def list_audits(self, offset: int, limit: int) -> tuple[dict[str, Any], ...]:
        return self.audits[offset : offset + limit]

    def list_documents(self, audit_id: str, offset: int, limit: int) -> tuple[dict[str, Any], ...]:
        del audit_id
        return ({"document_id": "root", "parse_state": "valid", "depth": 0},)[
            offset : offset + limit
        ]

    def list_entries(self, audit_id: str, offset: int, limit: int) -> tuple[dict[str, Any], ...]:
        del audit_id
        return (
            {
                "entry_id": "entry-1",
                "document_id": "root",
                "normalized_identity": "https://example.com/sitemap-only",
                "entry_sequence": 0,
                "in_scope": True,
                "validation_state": "valid",
                "duplicate": False,
                "is_child_reference": False,
            },
        )[offset : offset + limit]


def _audit(
    audit_id: str,
    *,
    run_id: str = "run-1",
    state: str = "completed",
    age_days: int = 0,
    partial: bool = False,
) -> dict[str, Any]:
    return {
        "audit_id": audit_id,
        "run_id": run_id,
        "seed_url": "https://example.com/",
        "state": state,
        "partial": partial,
        "unique_url_count": 1,
        "completed_at": (datetime.now(UTC) - timedelta(days=age_days)).isoformat(),
    }


def _request(
    module: SiteAuditStage,
    *,
    associated: dict[str, Any] | None = None,
    configured: str | None = None,
    launch: bool = False,
) -> SpecialistRequest:
    return SpecialistRequest(
        module,
        "run-1",
        "https://example.com/",
        ("example.com",),
        associated,
        configured,
        launch,
    )


def test_linked_child_and_authoritative_sitemap_evidence_are_retained() -> None:
    repository = _Repository((_audit("child"),))
    gateway = SQLAlchemySiteAuditSpecialistGateway(
        {
            SiteAuditStage.EXISTING_SITEMAP: SpecialistAuthority(
                repository,
                document_method="list_documents",
                entry_method="list_entries",
            )
        }
    )
    result = asyncio.run(
        gateway.resolve(
            _request(
                SiteAuditStage.EXISTING_SITEMAP,
                associated={
                    "specialist_audit_id": "child",
                    "execution_source": "linked_child",
                },
            )
        )
    )

    assert result.specialist_audit_id == "child"
    assert result.execution_source == "linked_child"
    assert result.documents[0]["document_id"] == "root"
    assert result.entries[0]["normalized_identity"].endswith("sitemap-only")


def test_latest_eligible_prior_is_selected_and_incompatible_run_is_ignored() -> None:
    repository = _Repository((_audit("wrong", run_id="run-other"), _audit("eligible")))
    gateway = SQLAlchemySiteAuditSpecialistGateway(
        {SiteAuditStage.METADATA: SpecialistAuthority(repository)}
    )
    result = asyncio.run(gateway.resolve(_request(SiteAuditStage.METADATA)))

    assert result.specialist_audit_id == "eligible"
    assert result.execution_source == "eligible_prior"
    assert result.eligibility_reason == "same_crawl_run"


def test_stale_partial_and_failed_lifecycle_states_remain_truthful() -> None:
    for audit, expected in (
        (_audit("stale", age_days=31), ("ineligible", "specialist_evidence_stale")),
        (
            _audit("partial", state="partially_completed", partial=True),
            ("eligible", "same_crawl_run"),
        ),
        (_audit("failed", state="failed"), ("eligible", "same_crawl_run")),
    ):
        gateway = SQLAlchemySiteAuditSpecialistGateway(
            {SiteAuditStage.IMAGES: SpecialistAuthority(_Repository((audit,)))}
        )
        result = asyncio.run(gateway.resolve(_request(SiteAuditStage.IMAGES)))
        assert (result.eligibility_state, result.eligibility_reason) == expected
        assert result.lifecycle_state == audit["state"]


def test_launch_occurs_once_only_when_no_persisted_association_or_prior_exists() -> None:
    launches: list[str] = []

    def launch(run_id: str) -> dict[str, Any]:
        launches.append(run_id)
        return _audit("launched")

    repository = _Repository((_audit("retained"),))
    gateway = SQLAlchemySiteAuditSpecialistGateway(
        {SiteAuditStage.STRUCTURED_DATA: SpecialistAuthority(repository, launch=launch)}
    )
    retained = asyncio.run(gateway.resolve(_request(SiteAuditStage.STRUCTURED_DATA, launch=True)))
    assert retained.specialist_audit_id == "retained"
    assert launches == []

    empty_gateway = SQLAlchemySiteAuditSpecialistGateway(
        {SiteAuditStage.STRUCTURED_DATA: SpecialistAuthority(_Repository(()), launch=launch)}
    )
    launched = asyncio.run(
        empty_gateway.resolve(_request(SiteAuditStage.STRUCTURED_DATA, launch=True))
    )
    assert launched.specialist_audit_id == "launched"
    assert launches == ["run-1"]
