"""CSA-03 normalized repository, restart, projection, and migration coverage."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
from alembic import command
from sqlalchemy import inspect

from musimack_tools.domain.persistence import PersistenceConfiguration
from musimack_tools.domain.site_audit_persistence import (
    AuditLifecycle,
    Population,
    SiteAuditPersistenceError,
)
from musimack_tools.operations.backup import create_backup, restore_backup
from musimack_tools.persistence.engine import create_persistence_runtime
from musimack_tools.persistence.migrations import (
    PERSISTENCE_HEAD_PARENT_REVISION,
    PERSISTENCE_HEAD_REVISION,
    alembic_configuration,
    current_revision,
    upgrade_to_head,
)
from musimack_tools.persistence.models import (
    ArtifactRecordModel,
    ArtifactStorageRootModel,
    ConfigurationSnapshotModel,
    JobModel,
    RunModel,
)
from musimack_tools.persistence.site_audit_orchestration_repository import (
    SQLAlchemySiteAuditOrchestrationRepository,
)
from musimack_tools.persistence.site_audit_repository import SQLAlchemySiteAuditRepository

if TYPE_CHECKING:
    from musimack_tools.persistence.engine import PersistenceRuntime

BACKEND_ROOT = Path(__file__).resolve().parents[2]


CSA_TABLES = {
    "site_audits",
    "site_audit_snapshots",
    "site_audit_rule_snapshots",
    "site_audit_disabled_inherited_rules",
    "site_audit_urls",
    "site_audit_url_discovery_sources",
    "site_audit_url_populations",
    "site_audit_rule_matches",
    "site_audit_findings",
    "site_audit_issue_groups",
    "site_audit_issue_group_memberships",
    "site_audit_module_statuses",
    "site_audit_summary_projections",
    "site_audit_artifact_associations",
}

CSA_ORCHESTRATION_TABLES = {
    "site_audit_orchestrations",
    "site_audit_orchestration_stages",
    "site_audit_specialist_associations",
}


@pytest.fixture
def repository(tmp_path: Path) -> tuple[PersistenceRuntime, SQLAlchemySiteAuditRepository]:
    database = tmp_path / "csa03.sqlite3"
    upgrade_to_head(f"sqlite+pysqlite:///{database.as_posix()}", backend_root=BACKEND_ROOT)
    runtime = create_persistence_runtime(
        PersistenceConfiguration(enabled=True, database_path=database)
    )
    return runtime, SQLAlchemySiteAuditRepository(runtime)


def _create(repo: SQLAlchemySiteAuditRepository, audit_id: str = "audit-1") -> dict[str, object]:
    return repo.create_audit(
        audit_id,
        audit_name="Example audit",
        site_label="Example",
        seed_url="https://example.com/",
        normalized_seed_url="https://example.com/",
        draft={"approved_hosts": ["example.com"], "enabled_modules": ["metadata"]},
        created_by="user-1",
    )


def _ready(repo: SQLAlchemySiteAuditRepository, audit_id: str = "audit-1") -> dict[str, object]:
    record = _create(repo, audit_id)
    for state in (
        AuditLifecycle.VALIDATING,
        AuditLifecycle.VALIDATED,
        AuditLifecycle.PREFLIGHTING,
        AuditLifecycle.READY,
    ):
        record = repo.transition(audit_id, state, expected_revision=cast("int", record["revision"]))
    return record


def _snapshot(repo: SQLAlchemySiteAuditRepository) -> dict[str, object]:
    ready = _ready(repo)
    return repo.create_snapshot(
        "audit-1",
        "snapshot-1",
        {
            "approved_hosts": ["example.com"],
            "scope_policy": {"mode": "exact_host"},
            "crawl_limits": {"maximum_urls": 100},
            "thresholds": {"title_minimum": 25},
            "enabled_modules": ["metadata"],
            "tracking_parameters": {"strip": ["utm_source"]},
            "application_version": "test",
        },
        expected_revision=cast("int", ready["revision"]),
        rules=(
            {
                "stable_rule_id": "rule-1",
                "rule_source": "per_audit",
                "source_version": "1",
                "decision_layer": "discovery",
                "match_type": "exact_path",
                "match_value": "/private",
                "action": "exclude_from_discovery",
                "reason_code": "private_path",
                "explanation": "Exclude the governed private path.",
                "priority": 10,
                "specificity": 6,
            },
        ),
        disabled_rules=(
            {
                "stable_rule_id": "preset-rule-1",
                "rule_source": "preset",
                "source_version": "wordpress-1",
            },
        ),
    )


def _url(repo: SQLAlchemySiteAuditRepository, sequence: int = 1) -> dict[str, object]:
    return repo.add_url(
        "audit-1",
        f"url-{sequence}",
        sequence=sequence,
        original_url=f"https://example.com/page-{sequence}?utm_source=test",
        requested_url=f"https://example.com/page-{sequence}",
        normalized_url=f"https://example.com/page-{sequence}",
        values={
            "fetch_state": "fetched",
            "parse_state": "parsed_html",
            "http_status": 200,
            "content_type": "text/html",
            "indexability_state": "indexable",
            "canonical_state": "canonical",
            "recommended_sitemap_state": "include",
            "metadata_scoring_decision": "include_in_metadata_scoring",
        },
    )


def _existing_artifact(runtime: PersistenceRuntime) -> None:
    now = datetime.now(UTC)
    with runtime.transaction() as session:
        session.add(
            ConfigurationSnapshotModel(
                snapshot_id="crawl-snapshot",
                snapshot_type="crawl",
                schema_version="test",
                canonical_json="{}",
                sha256="a" * 64,
            )
        )
        session.flush()
        session.add(
            RunModel(
                run_id="run-1",
                orchestration_version="test",
                normalized_seed_url="https://example.com/",
                lifecycle="completed",
                requested_stages_json="[]",
                stage_states_json="[]",
                crawl_count=0,
                recommendation_count=0,
                xml_count=0,
                publication_count=0,
                warning_count=0,
                failure_count=0,
                final_result_available=True,
                summary_available=True,
                configuration_snapshot_id="crawl-snapshot",
            )
        )
        session.flush()
        session.add(
            JobModel(
                job_id="job-1",
                run_id="run-1",
                attempt_number=1,
                state="completed",
                terminal=True,
                result_available=True,
                payload_retention_policy="metadata_only",
                registry_version="test",
                application_service_version="test",
                created_sequence=1,
                configuration_snapshot_id="crawl-snapshot",
                warning_count=0,
                failure_count=0,
            )
        )
        session.add(
            ArtifactStorageRootModel(
                root_id="root-1",
                enabled=True,
                readiness_state="ready",
                readable=True,
                writable=True,
                last_checked_at=now,
                storage_version="test",
            )
        )
        session.flush()
        session.add(
            ArtifactRecordModel(
                artifact_id="artifact-1",
                job_id="job-1",
                run_id="run-1",
                artifact_type="csv_export",
                root_id="root-1",
                relative_path="exports/pages.csv",
                safe_filename="pages.csv",
                content_type="text/csv",
                lifecycle_state="available",
                integrity_state="verified",
                expected_byte_count=0,
                observed_byte_count=0,
                expected_sha256="b" * 64,
                observed_sha256="b" * 64,
                created_at=now,
                available_at=now,
                retention_state="normal",
                storage_version="test",
                retrieval_version="test",
                reconciliation_version="test",
            )
        )


def test_create_update_list_archive_and_concurrency(
    repository: tuple[PersistenceRuntime, SQLAlchemySiteAuditRepository],
) -> None:
    _runtime, repo = repository
    _create(repo)
    updated = repo.update_draft("audit-1", {"changed": True}, expected_revision=1)
    assert updated["revision"] == 2
    assert updated["draft"] == {"changed": True}
    with pytest.raises(SiteAuditPersistenceError) as captured:
        repo.update_draft("audit-1", {}, expected_revision=1)
    assert captured.value.code == "site_audit_revision_conflict"
    items, total = repo.audits(search="example", page_size=50)
    assert total == 1
    assert items[0]["audit_id"] == "audit-1"
    archived = repo.transition("audit-1", AuditLifecycle.ARCHIVED, expected_revision=2)
    assert archived["archived_at"] is not None


def test_snapshot_is_exact_and_immutable(
    repository: tuple[PersistenceRuntime, SQLAlchemySiteAuditRepository],
) -> None:
    _runtime, repo = repository
    created = _snapshot(repo)
    reopened = repo.snapshot("audit-1")
    assert reopened is not None
    assert reopened["sha256"] == created["sha256"]
    assert len(reopened["rules"]) == 1
    assert len(reopened["disabled_inherited_rules"]) == 1
    with pytest.raises(SiteAuditPersistenceError) as captured:
        repo.update_draft("audit-1", {}, expected_revision=6)
    assert captured.value.code == "site_audit_snapshot_immutable"
    with pytest.raises(SiteAuditPersistenceError) as captured:
        repo.create_snapshot("audit-1", "snapshot-2", {}, expected_revision=6)
    assert captured.value.code == "site_audit_snapshot_immutable"


def test_url_identity_discoveries_populations_matches_and_filters(
    repository: tuple[PersistenceRuntime, SQLAlchemySiteAuditRepository],
) -> None:
    _runtime, repo = repository
    _snapshot(repo)
    _url(repo)
    repo.add_discovery(
        "audit-1",
        "url-1",
        {
            "discovery_id": "discovery-1",
            "sequence": 1,
            "source_type": "html_link",
            "source_url": "https://example.com/",
            "source_evidence_id": "evidence-1",
            "original_observed_url": "https://example.com/page-1?utm_source=test",
        },
    )
    assert repo.set_populations(
        "audit-1",
        "url-1",
        (
            Population.DISCOVERED,
            Population.ENQUEUED,
            Population.FETCHED,
            Population.PARSED_HTML,
            Population.INDEXABLE,
            Population.CANONICAL,
            Population.METADATA_SCORING_ELIGIBLE,
            Population.SITEMAP_ELIGIBLE,
        ),
    ) == tuple(
        sorted(
            item.value
            for item in (
                Population.DISCOVERED,
                Population.ENQUEUED,
                Population.FETCHED,
                Population.PARSED_HTML,
                Population.INDEXABLE,
                Population.CANONICAL,
                Population.METADATA_SCORING_ELIGIBLE,
                Population.SITEMAP_ELIGIBLE,
            )
        )
    )
    retained_snapshot = repo.snapshot("audit-1")
    assert retained_snapshot is not None
    snapshot_rule_id = retained_snapshot["rules"][0]["snapshot_rule_id"]
    match = repo.add_rule_match(
        "audit-1",
        "url-1",
        {
            "match_id": "match-1",
            "snapshot_rule_id": snapshot_rule_id,
            "matched_original_url": "https://example.com/page-1?utm_source=test",
            "matched_normalized_url": "https://example.com/page-1",
            "primary_rule": True,
        },
    )
    assert match["primary_rule"] is True
    rows, total = repo.urls(
        "audit-1", page_size=50, url_text="page-1", http_status=200, sitemap_state="include"
    )
    assert total == 1
    assert rows[0]["url_id"] == "url-1"
    assert repo.rule_matches("audit-1")[0]["match_id"] == "match-1"
    with pytest.raises(SiteAuditPersistenceError) as captured:
        repo.add_url(
            "audit-1",
            "url-duplicate",
            sequence=2,
            original_url="https://example.com/page-1",
            requested_url="https://example.com/page-1",
            normalized_url="https://example.com/page-1",
        )
    assert captured.value.code == "site_audit_duplicate_normalized_url"


def test_findings_groups_membership_modules_and_restart_safe_rebuild(
    repository: tuple[PersistenceRuntime, SQLAlchemySiteAuditRepository],
) -> None:
    runtime, repo = repository
    _snapshot(repo)
    _url(repo)
    repo.set_populations(
        "audit-1",
        "url-1",
        (Population.DISCOVERED, Population.PARSED_HTML, Population.INDEXABLE),
    )
    repo.add_finding(
        "audit-1",
        {
            "finding_id": "finding-1",
            "url_id": "url-1",
            "module": "metadata",
            "category": "title",
            "code": "title_missing",
            "severity": "high",
            "explanation": "The title is missing.",
            "metadata_impact": True,
        },
    )
    repo.upsert_issue_group(
        "audit-1",
        {
            "group_id": "group-1",
            "category": "title",
            "code": "title_missing",
            "remediation_key": "add-title",
            "applicable_population": "parsed_html",
            "title": "Missing titles",
            "explanation": "Pages have no title.",
            "severity": "high",
            "affected_url_count": 1,
            "priority_key": "1|high|not_assigned|000001|title_missing|group-1",
            "priority_explanation": "High severity, one affected URL.",
            "recommended_action": "Add a descriptive title.",
            "sample_urls": ["https://example.com/page-1"],
        },
    )
    repo.add_issue_membership(
        "audit-1", "group-1", "finding-1", sequence=1, reason="same remediation"
    )
    repo.upsert_module_status(
        "audit-1",
        {
            "module": "metadata",
            "lifecycle": "completed",
            "completeness": "complete",
            "result_count": 1,
        },
    )
    first = repo.rebuild_summary("audit-1", expected_revision=0)
    second = repo.rebuild_summary("audit-1", expected_revision=1)
    assert first["urls_discovered"] == second["urls_discovered"] == 1
    assert first["high_issue_groups"] == second["high_issue_groups"] == 1
    assert second["recommendation_include"] == 1
    database = runtime.configuration.database_path
    assert database is not None
    runtime.dispose()
    reopened_runtime = create_persistence_runtime(
        PersistenceConfiguration(enabled=True, database_path=database)
    )
    reopened = SQLAlchemySiteAuditRepository(reopened_runtime)
    summary = reopened.summary("audit-1")
    assert summary is not None
    assert summary["revision"] == 2
    restored_group = reopened.issue_groups("audit-1")[0]
    assert restored_group["group_id"] == "group-1"
    assert restored_group["affected_url_count"] == 1
    assert reopened.module_statuses("audit-1")[0]["module"] == "metadata"
    reopened_runtime.dispose()


def test_migration_head_schema_downgrade_and_reupgrade(tmp_path: Path) -> None:
    database = tmp_path / "migration.sqlite3"
    url = f"sqlite+pysqlite:///{database.as_posix()}"
    configuration = alembic_configuration(url, backend_root=BACKEND_ROOT)
    command.upgrade(configuration, "head")
    runtime = create_persistence_runtime(
        PersistenceConfiguration(enabled=True, database_path=database)
    )
    assert current_revision(runtime.engine) == PERSISTENCE_HEAD_REVISION
    schema = inspect(runtime.engine)
    assert set(schema.get_table_names()) >= CSA_TABLES
    assert {item["name"] for item in schema.get_unique_constraints("site_audit_urls")} >= {
        "uq_site_audit_url_sequence",
        "uq_site_audit_url_identity",
    }
    assert {item["name"] for item in schema.get_indexes("site_audit_urls")} >= {
        "ix_site_audit_urls_order",
        "ix_site_audit_urls_status",
        "ix_site_audit_urls_sitemap",
        "ix_site_audit_urls_severity",
    }
    snapshot_foreign_keys = schema.get_foreign_keys("site_audit_snapshots")
    assert snapshot_foreign_keys[0]["options"]["ondelete"] == "CASCADE"
    artifact_foreign_keys = schema.get_foreign_keys("site_audit_artifact_associations")
    assert {item["options"]["ondelete"] for item in artifact_foreign_keys} == {
        "CASCADE",
        "RESTRICT",
    }
    assert {item["name"] for item in schema.get_check_constraints("site_audits")} >= {
        "ck_site_audit_lifecycle",
        "ck_site_audit_revision_positive",
    }
    runtime.dispose()
    command.downgrade(configuration, PERSISTENCE_HEAD_PARENT_REVISION)
    downgraded = create_persistence_runtime(
        PersistenceConfiguration(enabled=True, database_path=database)
    )
    assert current_revision(downgraded.engine) == PERSISTENCE_HEAD_PARENT_REVISION
    downgraded_tables = set(inspect(downgraded.engine).get_table_names())
    assert downgraded_tables >= CSA_TABLES
    assert not (CSA_ORCHESTRATION_TABLES & downgraded_tables)
    downgraded.dispose()
    command.upgrade(configuration, "head")
    reupgraded = create_persistence_runtime(
        PersistenceConfiguration(enabled=True, database_path=database)
    )
    assert current_revision(reupgraded.engine) == PERSISTENCE_HEAD_REVISION
    reupgraded.dispose()


def test_populated_csa_database_backup_and_restore(
    repository: tuple[PersistenceRuntime, SQLAlchemySiteAuditRepository], tmp_path: Path
) -> None:
    runtime, repo = repository
    snapshot = _snapshot(repo)
    SQLAlchemySiteAuditOrchestrationRepository(runtime).initialize("audit-1", snapshot)
    _url(repo)
    repo.set_populations("audit-1", "url-1", (Population.DISCOVERED, Population.FETCHED))
    repo.rebuild_summary("audit-1", expected_revision=0)
    _existing_artifact(runtime)
    association = repo.associate_artifact(
        "audit-1",
        "artifact-1",
        purpose="page_inventory_csv",
        schema_version="site-audit-pages-v1",
        completeness="complete",
        row_count=1,
    )
    assert association["artifact_id"] == "artifact-1"
    database = runtime.configuration.database_path
    assert database is not None
    runtime.dispose()
    backup = tmp_path / "backup"
    restored = tmp_path / "restored"
    create_backup(
        database,
        (),
        backup,
        repository_root=Path.cwd(),
        services_stopped=True,
        application_revision="test",
    )
    result = restore_backup(backup, restored, repository_root=Path.cwd())
    with (
        closing(sqlite3.connect(database)) as source,
        closing(sqlite3.connect(result.database_path)) as target,
    ):
        for table in CSA_TABLES | CSA_ORCHESTRATION_TABLES:
            source_count = source.execute(
                f'SELECT count(*) FROM "{table}"'  # noqa: S608 - closed constant inventory.
            ).fetchone()
            target_count = target.execute(
                f'SELECT count(*) FROM "{table}"'  # noqa: S608 - closed constant inventory.
            ).fetchone()
            assert source_count == target_count
