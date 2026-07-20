"""Migration and restart-safe repository coverage for CSA-04 orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
from sqlalchemy import inspect

from musimack_tools.domain.persistence import PersistenceConfiguration
from musimack_tools.domain.site_audit_orchestration import (
    OrchestrationState,
    SiteAuditOrchestrationError,
    SiteAuditStage,
    StageState,
)
from musimack_tools.domain.site_audit_persistence import AuditLifecycle
from musimack_tools.persistence.engine import create_persistence_runtime
from musimack_tools.persistence.migrations import PERSISTENCE_HEAD_REVISION, upgrade_to_head
from musimack_tools.persistence.site_audit_orchestration_repository import (
    SQLAlchemySiteAuditOrchestrationRepository,
)
from musimack_tools.persistence.site_audit_repository import SQLAlchemySiteAuditRepository

if TYPE_CHECKING:
    from collections.abc import Iterator

    from musimack_tools.persistence.engine import PersistenceRuntime

BACKEND_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def repositories(
    tmp_path: Path,
) -> Iterator[
    tuple[
        PersistenceRuntime,
        SQLAlchemySiteAuditRepository,
        SQLAlchemySiteAuditOrchestrationRepository,
    ]
]:
    database = tmp_path / "csa04.sqlite3"
    upgrade_to_head(f"sqlite+pysqlite:///{database.as_posix()}", backend_root=BACKEND_ROOT)
    runtime = create_persistence_runtime(
        PersistenceConfiguration(enabled=True, database_path=database)
    )
    try:
        yield (
            runtime,
            SQLAlchemySiteAuditRepository(runtime),
            SQLAlchemySiteAuditOrchestrationRepository(runtime),
        )
    finally:
        runtime.dispose()


def _snapshot(repository: SQLAlchemySiteAuditRepository) -> dict[str, object]:
    audit = repository.create_audit(
        "audit-csa04",
        audit_name="CSA-04 fixture",
        site_label="Example",
        seed_url="https://example.com/",
        normalized_seed_url="https://example.com/",
        draft={"approved_hosts": ["example.com"]},
        created_by="operator-1",
    )
    for lifecycle in (
        AuditLifecycle.VALIDATING,
        AuditLifecycle.VALIDATED,
        AuditLifecycle.PREFLIGHTING,
        AuditLifecycle.READY,
    ):
        audit = repository.transition(
            "audit-csa04", lifecycle, expected_revision=cast("int", audit["revision"])
        )
    return repository.create_snapshot(
        "audit-csa04",
        "snapshot-csa04",
        {
            "approved_hosts": ["example.com"],
            "scope_policy": {"mode": "exact_host"},
            "crawl_limits": {"maximum_urls": 25},
            "enabled_modules": ["images_and_alt_text"],
            "application_version": "test",
        },
        expected_revision=cast("int", audit["revision"]),
    )


def test_0018_schema_has_one_head_and_only_orchestration_state(
    repositories: tuple[
        PersistenceRuntime,
        SQLAlchemySiteAuditRepository,
        SQLAlchemySiteAuditOrchestrationRepository,
    ],
) -> None:
    runtime, _site, _orchestration = repositories
    assert PERSISTENCE_HEAD_REVISION == "0018_combined_site_audit_orchestration"
    tables = set(inspect(runtime.engine).get_table_names())
    assert {
        "site_audit_orchestrations",
        "site_audit_orchestration_stages",
        "site_audit_specialist_associations",
    }.issubset(tables)
    assert "site_audit_crawl_results" not in tables
    assert "site_audit_response_bodies" not in tables
    schema = inspect(runtime.engine)
    assert {item["name"] for item in schema.get_indexes("site_audit_orchestrations")} == {
        "ix_site_audit_orchestration_job",
        "ix_site_audit_orchestration_state",
    }
    assert {
        item["name"] for item in schema.get_unique_constraints("site_audit_orchestration_stages")
    } == {
        "uq_site_audit_orchestration_stage",
        "uq_site_audit_stage_order",
    }
    assert {
        item["options"]["ondelete"] for item in schema.get_foreign_keys("site_audit_orchestrations")
    } == {
        "CASCADE",
        "SET NULL",
    }
    assert {
        item["name"] for item in schema.get_check_constraints("site_audit_orchestration_stages")
    } >= {
        "ck_site_audit_stage_attempts",
        "ck_site_audit_stage_checkpoint",
        "ck_site_audit_stage_counts",
        "ck_site_audit_stage_state",
    }


def test_initialization_is_idempotent_and_dependencies_survive_restart(
    repositories: tuple[
        PersistenceRuntime,
        SQLAlchemySiteAuditRepository,
        SQLAlchemySiteAuditOrchestrationRepository,
    ],
) -> None:
    runtime, site, orchestration = repositories
    snapshot = _snapshot(site)
    first = orchestration.initialize("audit-csa04", snapshot)
    second = orchestration.initialize("audit-csa04", snapshot)
    assert first["audit_id"] == second["audit_id"]
    stages = orchestration.stages("audit-csa04")
    assert stages[0]["stage"] == "crawl_inventory"
    assert next(item for item in stages if item["stage"] == "url_ingestion")["dependencies"] == (
        "crawl_inventory",
    )
    assert any(item["stage"] == "images_and_alt_text" and not item["required"] for item in stages)
    restarted = SQLAlchemySiteAuditOrchestrationRepository(runtime)
    assert restarted.orchestration("audit-csa04") == first


def test_stage_checkpoint_cancellation_retry_and_specialist_provenance_are_durable(
    repositories: tuple[
        PersistenceRuntime,
        SQLAlchemySiteAuditRepository,
        SQLAlchemySiteAuditOrchestrationRepository,
    ],
) -> None:
    _runtime, site, orchestration = repositories
    orchestration.initialize("audit-csa04", _snapshot(site))
    running = orchestration.update_stage(
        "audit-csa04",
        SiteAuditStage.INGEST,
        StageState.RUNNING,
        checkpoint=12,
        source_count=20,
        projected_count=12,
        lease_owner="worker-1",
    )
    assert running["attempt_count"] == 1
    assert running["checkpoint"] == 12
    orchestration.upsert_specialist(
        "audit-csa04",
        {
            "module": "metadata",
            "source_run_id": "run-source",
            "execution_source": "eligible_prior",
            "eligibility_state": "eligible",
            "eligibility_reason": "same_seed_and_evidence",
            "freshness_state": "current",
            "evidence_count": 20,
        },
    )
    assert orchestration.specialists("audit-csa04")[0]["source_run_id"] == "run-source"
    assert orchestration.request_cancellation("audit-csa04")["cancellation_requested"] is True
    orchestration.set_state("audit-csa04", OrchestrationState.RECOVERY_REQUIRED)
    assert orchestration.retry("audit-csa04")["retry_count"] == 1
    with pytest.raises(SiteAuditOrchestrationError) as invalid:
        orchestration.retry("audit-csa04")
    assert invalid.value.code == "site_audit_retry_not_allowed"


def test_expired_lease_is_bounded_recoverable_and_not_recovered_twice(
    repositories: tuple[
        PersistenceRuntime,
        SQLAlchemySiteAuditRepository,
        SQLAlchemySiteAuditOrchestrationRepository,
    ],
) -> None:
    _runtime, site, orchestration = repositories
    orchestration.initialize("audit-csa04", _snapshot(site))
    orchestration.update_stage(
        "audit-csa04",
        SiteAuditStage.INGEST,
        StageState.RUNNING,
        lease_owner="interrupted-worker",
        lease_seconds=-1,
    )
    assert orchestration.recover_expired(limit=1) == ("audit-csa04",)
    parent = orchestration.orchestration("audit-csa04")
    assert parent is not None
    assert parent["state"] == "recovery_required"
    assert parent["recovery_count"] == 1
    stage = next(
        item for item in orchestration.stages("audit-csa04") if item["stage"] == "url_ingestion"
    )
    assert stage["state"] == "pending"
    assert stage["checkpoint"] == 0
    assert stage["failure_code"] == "site_audit_stage_lease_expired"
    assert orchestration.recover_expired(limit=1) == ()
