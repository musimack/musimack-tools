"""Focused BS-01 workflow, persistence, fixture, and export coverage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from musimack_tools.blog_strategy.export import EXPORT_COLUMNS, safe_spreadsheet_text
from musimack_tools.blog_strategy.repository import BlogStrategyRepository
from musimack_tools.blog_strategy.service import BlogStrategyService
from musimack_tools.domain.blog_strategy import (
    EvidenceCandidate,
    PageEvidenceProvider,
    normalize_blog_url,
)
from musimack_tools.domain.persistence import PersistenceConfiguration
from musimack_tools.persistence.engine import create_persistence_runtime
from musimack_tools.persistence.migrations import upgrade_to_head

if TYPE_CHECKING:
    from collections.abc import Iterator

BACKEND = Path(__file__).parents[2]
FIXTURE = BACKEND / "tests" / "fixtures" / "bewell_blog_strategy_bs01.json"


class FixtureEvidenceProvider(PageEvidenceProvider):
    def preview(self, source_reference: str) -> tuple[EvidenceCandidate, ...]:
        assert source_reference == "run_fixture"
        return (
            EvidenceCandidate(
                "run_fixture",
                "https://crokinchiro.com/articles/imported",
                "Imported page",
                http_status=200,
                indexability="indexable",
            ),
        )


@pytest.fixture
def service(tmp_path: Path) -> Iterator[BlogStrategyService]:
    database = tmp_path / "blog.db"
    upgrade_to_head(f"sqlite+pysqlite:///{database.as_posix()}", backend_root=BACKEND)
    runtime = create_persistence_runtime(
        PersistenceConfiguration(enabled=True, database_path=database)
    )
    yield BlogStrategyService(BlogStrategyRepository(runtime), FixtureEvidenceProvider())
    runtime.dispose()


def test_url_normalization_and_invalid_scheme() -> None:
    assert (
        normalize_blog_url("HTTPS://Example.COM:443/blog//post/#part")
        == "https://example.com/blog/post"
    )
    with pytest.raises(ValueError, match="blog_strategy_url_invalid"):
        normalize_blog_url("file:///private")


def test_bs01_bewell_workflow_and_one_sheet_export(  # noqa: PLR0915
    service: BlogStrategyService,
) -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    project = service.create_project(
        {
            "client_name": fixture["client"],
            "primary_website": fixture["website"],
            "primary_market": fixture["primary_market"],
            "core_services": ["Chiropractic care"],
            "important_pages": ["https://crokinchiro.com/services/chiropractic"],
            "compliance_notes": "Professional review is required for health claims.",
        },
        "reviewer",
    )
    assert project["status"] == "draft"
    progressed = service.update_project(
        project["project_id"], {"status": "inventory_in_progress"}, project["revision"], "reviewer"
    )
    with pytest.raises(ValueError, match="invalid_status_transition"):
        service.update_project(
            project["project_id"], {"status": "completed"}, progressed["revision"], "reviewer"
        )

    families = {
        name: service.create_family(project["project_id"], {"name": name}, "reviewer")
        for name in ("Back Pain", "Neck Pain", "Temporary")
    }
    pages = {}
    for item in fixture["pages"]:
        page = service.add_page(
            project["project_id"],
            {
                "url": f"https://crokinchiro.com/blog/{item['slug']}",
                "title": item["title"],
                "inclusion_state": "excluded" if item.get("excluded") else "included",
            },
            "reviewer",
        )
        data = {
            "primary_topic": item["topic"],
            "search_intent": "learn_condition",
            "content_role": item["role"],
            "claim_risk": item.get("claim_risk", "low"),
            "action": item["action"],
            "priority": "priority_2",
            "human_reviewed": True,
            "approved": True,
            "notes": "'=fixture safety check" if item["slug"] == "back-pain-guide" else "",
        }
        if item.get("family"):
            data.update(
                {
                    "family_id": families[item["family"]]["family_id"],
                    "membership_role": "primary"
                    if item["role"] == "primary_guide"
                    else "supporting",
                }
            )
        pages[item["slug"]] = service.update_page(
            project["project_id"], page["page_id"], data, page["revision"], "reviewer"
        )

    duplicate = pages["back-pain-guide"]
    with pytest.raises(ValueError, match="duplicate_url"):
        service.add_page(project["project_id"], {"url": duplicate["original_url"] + "/"})
    with pytest.raises(ValueError, match="revision_conflict"):
        service.update_page(project["project_id"], duplicate["page_id"], {"notes": "stale"}, 1)

    preview = service.preview_import("run_fixture")
    assert preview[0].http_status == 200
    first = service.import_pages(project["project_id"], "run_fixture", [preview[0].url], "reviewer")
    second = service.import_pages(
        project["project_id"], "run_fixture", [preview[0].url], "reviewer"
    )
    assert (first.imported, second.skipped) == (1, 1)
    imported = service.repository.page(project["project_id"], first.page_ids[0])
    assert imported["provenance"]["provider"] == "page_evidence"

    for item in fixture["overlaps"]:
        concern = service.create_overlap(
            project["project_id"],
            {
                "page_ids": [pages[slug]["page_id"] for slug in item["pages"]],
                "concern_type": item["type"],
                "severity": "high" if item["state"] == "open" else "medium",
                "preferred_page_id": pages[item["preferred"]]["page_id"]
                if item.get("preferred")
                else None,
                "notes": item.get("notes", "Human-entered evidence."),
            },
            "reviewer",
        )
        if item["state"] != "open":
            concern = service.update_overlap(
                project["project_id"],
                concern["overlap_id"],
                {
                    "review_state": item["state"],
                    "resolution_notes": "Reviewed by a human.",
                },
                concern["revision"],
                "reviewer",
            )
        assert concern["review_state"] == item["state"]

    temporary = families["Temporary"]
    merged = service.repository.merge_family(
        project["project_id"],
        temporary["family_id"],
        families["Back Pain"]["family_id"],
        temporary["revision"],
        "reviewer",
    )
    assert merged["status"] == "merged"
    archived = service.update_family(
        project["project_id"],
        families["Neck Pain"]["family_id"],
        {"status": "archived"},
        families["Neck Pain"]["revision"],
        "reviewer",
    )
    assert archived["status"] == "archived"

    readiness = service.readiness(project["project_id"])
    assert "open_high_severity_overlap" in readiness.warnings
    with pytest.raises(ValueError, match="export_not_ready"):
        service.export(project["project_id"])
    filename, workbook, validation = service.export(
        project["project_id"], acknowledge_warnings=True
    )
    assert filename == "bewell-chiropractic-blog-strategy.xlsx"
    assert workbook.startswith(b"PK")
    assert validation["worksheet_count"] == 1
    assert validation["worksheet_name"] == "Blog Strategy"
    assert validation["row_count"] == 9
    assert validation["frozen_header"] and validation["filters_enabled"]
    assert not validation["hidden_sheets"] and validation["formula_count"] == 0
    assert validation["has_styles"] and validation["safe_hyperlinks"]
    assert validation["hyperlink_count"] >= 18
    assert len(EXPORT_COLUMNS) == 27
    assert safe_spreadsheet_text("=2+2") == "'=2+2"
    events = service.repository.events(project["project_id"])
    assert {event["event_type"] for event in events} >= {
        "project_created",
        "page_added",
        "overlap_updated",
        "topic_family_merged",
    }
