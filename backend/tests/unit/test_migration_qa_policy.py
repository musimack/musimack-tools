"""Direct Phase 26 policy, ingestion, pagination, and authorization tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

import pytest

from musimack_tools.api.dependencies import permission_for_request
from musimack_tools.domain.authentication import Permission
from musimack_tools.domain.migration_qa import (
    FINDING_CODES,
    FINDING_CODES_BY_CATEGORY,
    MAPPING_CARDINALITIES,
    MAPPING_METHODS,
    RECOMMENDATION_ACTIONS,
    MigrationQaConfiguration,
    classify_migration_finding,
    decode_cursor,
    encode_cursor,
)
from musimack_tools.migration_qa.service import MigrationQaService
from musimack_tools.persistence.migration_qa_repository import is_expired_evidence_timestamp

if TYPE_CHECKING:
    from musimack_tools.persistence.migration_qa_repository import SQLAlchemyMigrationQaRepository


class PolicyRepository:
    def __init__(self) -> None:
        self.inputs: dict[str, list[dict[str, Any]]] = {"sources": [], "redirect-map": []}
        self.project = {
            "project_id": "project",
            "source_origin": "https://old.example",
            "destination_origin": "https://www.example",
            "destination_run_id": "destination-run",
            "source_run_id": None,
            "state": "draft",
        }

    def get(self, project_id: str) -> dict[str, Any] | None:
        return self.project if project_id == "project" else None

    def replace_input(self, _project_id: str, name: str, rows: list[dict[str, Any]]) -> None:
        self.inputs[name] = rows

    def list_resource(self, _project_id: str, name: str) -> tuple[dict[str, Any], ...]:
        return tuple(self.inputs.get(name, []))


@pytest.mark.parametrize("code", sorted(FINDING_CODES))
def test_every_finding_code_is_behaviorally_reachable(code: str) -> None:
    finding = classify_migration_finding(code, {"retained": True})
    assert finding["code"] == code
    assert finding["confidence"] in {"high", "indeterminate"}
    assert finding["evidence"] == {"retained": True}


def test_taxonomies_cover_all_required_categories_and_actions() -> None:
    assert set(FINDING_CODES_BY_CATEGORY) == {
        "redirect",
        "destination",
        "metadata",
        "content",
        "canonical",
        "indexability",
        "internal_links",
        "sitemap",
        "images",
        "structured_data",
        "sitewide",
        "inventory",
        "mapping",
        "readiness",
    }
    assert len(RECOMMENDATION_ACTIONS) == 35
    assert len(MAPPING_METHODS) == 10
    assert {
        "one_to_one",
        "many_to_one",
        "one_to_many",
        "unmapped",
        "ambiguous",
    } == MAPPING_CARDINALITIES


def test_cursor_is_filter_bound_and_tamper_evident() -> None:
    cursor = encode_cursor("findings", "filter-a", 25)
    assert decode_cursor(cursor, "findings", "filter-a") == 25
    with pytest.raises(ValueError, match="migration_qa_cursor_mismatch"):
        decode_cursor(cursor, "findings", "filter-b")


def test_configuration_is_disabled_by_default_and_bounded() -> None:
    configuration = MigrationQaConfiguration()
    assert not configuration.enabled
    assert configuration.maximum_input_bytes == 10_000_000
    with pytest.raises(ValueError, match="migration_qa_invalid_page_size"):
        MigrationQaConfiguration(default_page_size=201, maximum_page_size=200)


def test_sqlite_naive_evidence_expiry_is_compared_as_utc() -> None:
    now = datetime(2026, 1, 2, tzinfo=UTC)
    assert is_expired_evidence_timestamp(datetime(2026, 1, 1, tzinfo=UTC).replace(tzinfo=None), now)
    assert not is_expired_evidence_timestamp(
        datetime(2026, 1, 3, tzinfo=UTC).replace(tzinfo=None), now
    )


def test_ingestion_preserves_raw_normalized_comparison_and_diagnostics() -> None:
    repository = PolicyRepository()
    service = MigrationQaService(
        MigrationQaConfiguration(enabled=True),
        cast("SQLAlchemyMigrationQaRepository", repository),
    )
    result = service.ingest_source_inventory(
        "project",
        "source_url,destination_url\n"
        "https://OLD.example/a,https://www.example/a\n"
        "https://OLD.example/a,https://www.example/other\n"
        "http://,\n",
    )
    assert result == {"accepted_rows": 3, "invalid_rows": 1}
    assert repository.inputs["sources"][0]["raw_url"] == "https://OLD.example/a"
    assert repository.inputs["sources"][0]["normalized_url"] == "https://old.example/a"
    assert repository.inputs["sources"][0]["comparison_url"] == "https://old.example/a"
    assert repository.inputs["sources"][1]["state"] == "conflict"
    assert repository.inputs["sources"][2]["state"] == "invalid"


def test_redirect_map_keeps_planned_rows_separate_and_flags_conflicts() -> None:
    repository = PolicyRepository()
    service = MigrationQaService(
        MigrationQaConfiguration(enabled=True),
        cast("SQLAlchemyMigrationQaRepository", repository),
    )
    result = service.ingest_redirect_map(
        "project",
        "source_url,destination_url,status\n"
        "https://old.example/a,https://www.example/a,301\n"
        "https://old.example/a,https://www.example/b,302\n",
    )
    assert result == {"accepted_rows": 2, "invalid_rows": 0}
    assert repository.inputs["redirect-map"][0]["expected_status"] == 301
    assert repository.inputs["redirect-map"][1]["state"] == "conflict"


def test_migration_routes_have_explicit_role_permission_mapping() -> None:
    assert permission_for_request("GET", "/api/internal/v1/migrations/qa") is Permission.RUNS_VIEW
    assert (
        permission_for_request("POST", "/api/internal/v1/migrations/qa") is Permission.JOBS_SUBMIT
    )
    assert (
        permission_for_request("POST", "/api/internal/v1/migrations/qa/id/exports")
        is Permission.JOBS_SUBMIT
    )


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("/one\n/two?x=1#part\n", ("https://old.example/one", "https://old.example/two?x=1")),
        ("source_url\tdestination_url\n/one\t/new\n", ("https://old.example/one",)),
        (
            'source_url,destination_url\n"/quoted,comma","/new,comma"\n',
            ("https://old.example/quoted,comma",),
        ),
        ('source_url,destination_url\n"/quoted\nnewline",/new\n', (None,)),
        ("source_url\nhttps://münich.example/straße\n", ("https://xn--mnich-kva.example/straße",)),
        ("source_url\nhttps://old.example/%7euser\n", ("https://old.example/%7Euser",)),
    ],
)
def test_inventory_parses_supported_bounded_input_forms(
    content: str, expected: tuple[str | None, ...]
) -> None:
    repository = PolicyRepository()
    service = MigrationQaService(
        MigrationQaConfiguration(enabled=True),
        cast("SQLAlchemyMigrationQaRepository", repository),
    )
    service.ingest_source_inventory("project", content)
    assert tuple(row["normalized_url"] for row in repository.inputs["sources"]) == expected


def test_inventory_preserves_out_of_scope_state_and_detects_conflicting_destinations() -> None:
    repository = PolicyRepository()
    service = MigrationQaService(
        MigrationQaConfiguration(enabled=True),
        cast("SQLAlchemyMigrationQaRepository", repository),
    )
    service.ingest_source_inventory(
        "project",
        "source_url,destination_url\n"
        "https://outside.example/a,/a\n"
        "https://outside.example/a,/other\n",
    )
    first, second = repository.inputs["sources"]
    assert first["state"] == "out_of_scope"
    assert second["state"] == "out_of_scope"
    assert "inventory_out_of_scope" in first["diagnostics_json"]
    assert "inventory_duplicate_source" in second["diagnostics_json"]
    assert "inventory_conflicting_destination" in second["diagnostics_json"]


def test_inventory_rejects_unsupported_scheme_overlong_and_oversized_input() -> None:
    repository = PolicyRepository()
    service = MigrationQaService(
        MigrationQaConfiguration(enabled=True, maximum_field_characters=10),
        cast("SQLAlchemyMigrationQaRepository", repository),
    )
    result = service.ingest_source_inventory(
        "project", "source_url\nftp://old.example/a\n=FORMULA-LIKE\n"
    )
    assert result["invalid_rows"] == 2
    assert "inventory_unsupported_scheme" in repository.inputs["sources"][0]["diagnostics_json"]
    assert "inventory_field_too_long" in repository.inputs["sources"][1]["diagnostics_json"]
    valid_bounds = MigrationQaService(
        MigrationQaConfiguration(enabled=True),
        cast("SQLAlchemyMigrationQaRepository", repository),
    )
    valid_bounds.ingest_source_inventory("project", "source_url\nhttp://\n")
    assert "inventory_invalid_url" in repository.inputs["sources"][0]["diagnostics_json"]
    limited = MigrationQaService(
        MigrationQaConfiguration(enabled=True, maximum_input_bytes=5),
        cast("SQLAlchemyMigrationQaRepository", repository),
    )
    with pytest.raises(ValueError, match="migration_qa_input_too_large"):
        limited.ingest_source_inventory("project", "source_url\nhttps://old.example/a")


@pytest.mark.parametrize(
    ("status", "state"),
    [
        ("301", "valid"),
        ("302", "valid"),
        ("307", "valid"),
        ("308", "valid"),
        ("", "valid"),
        ("200", "invalid"),
    ],
)
def test_redirect_map_supported_status_policy(status: str, state: str) -> None:
    repository = PolicyRepository()
    service = MigrationQaService(
        MigrationQaConfiguration(enabled=True),
        cast("SQLAlchemyMigrationQaRepository", repository),
    )
    service.ingest_redirect_map("project", f"source_url,destination_url,status\n/a,/b,{status}\n")
    assert repository.inputs["redirect-map"][0]["state"] == state


def test_redirect_map_detects_duplicates_collisions_chain_loop_query_and_fragment_inputs() -> None:
    repository = PolicyRepository()
    service = MigrationQaService(
        MigrationQaConfiguration(enabled=True),
        cast("SQLAlchemyMigrationQaRepository", repository),
    )
    service.ingest_redirect_map(
        "project",
        "source_url,destination_url,status\n"
        "https://old.example/a#old,https://old.example/b#new,301\n"
        "https://old.example/b,https://old.example/c,302\n"
        "https://old.example/c,https://old.example/a,308\n"
        "https://old.example/a,https://old.example/other,301\n"
        "https://old.example/different,https://old.example/c,301\n"
        "https://old.example/a,https://old.example/b,301\n",
    )
    rows = repository.inputs["redirect-map"]
    assert "redirect_map_loop" in rows[0]["diagnostics_json"]
    assert "redirect_map_duplicate_source" in rows[5]["diagnostics_json"]
    assert "redirect_map_conflicting_destination" in rows[3]["diagnostics_json"]
    assert rows[3]["state"] == "conflict"
    assert "redirect_destination_collision" in rows[4]["diagnostics_json"]
    assert rows[0]["raw_source_url"].endswith("#old")
    service.ingest_redirect_map(
        "project",
        "source_url,destination_url,status\n"
        "https://old.example/x,https://old.example/y,301\n"
        "https://old.example/y,https://old.example/z,301\n",
    )
    assert "redirect_map_chain" in repository.inputs["redirect-map"][0]["diagnostics_json"]


def test_inventory_and_redirect_row_caps_reject_without_truncation() -> None:
    repository = PolicyRepository()
    service = MigrationQaService(
        MigrationQaConfiguration(enabled=True, maximum_inventory_rows=1, maximum_redirect_rows=1),
        cast("SQLAlchemyMigrationQaRepository", repository),
    )
    with pytest.raises(ValueError, match="migration_qa_inventory_too_large"):
        service.ingest_source_inventory("project", "source_url\n/a\n/b\n")
    with pytest.raises(ValueError, match="migration_qa_redirect_map_too_large"):
        service.ingest_redirect_map("project", "source_url,destination_url\n/a,/b\n/b,/c\n")
