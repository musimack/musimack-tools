"""Application service for the manually authoritative BS-01 workflow."""

# ruff: noqa: ANN401, PLR2004, TC001 - Bounded request dictionaries are validated at this layer.

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from musimack_tools.blog_strategy.export import build_xlsx, validate_xlsx
from musimack_tools.blog_strategy.repository import BlogStrategyRepository
from musimack_tools.domain.blog_strategy import (
    ClaimRisk,
    ConcernType,
    ContentRole,
    EvidenceCandidate,
    ExportReadiness,
    ImportReport,
    InclusionState,
    MembershipRole,
    PageEvidenceProvider,
    Priority,
    ProjectStatus,
    ReviewState,
    SearchIntent,
    SourceType,
    StrategyAction,
    TopicFamilyStatus,
    normalize_blog_url,
    validate_project_transition,
)


class BlogStrategyService:
    def __init__(
        self, repository: BlogStrategyRepository, provider: PageEvidenceProvider | None = None
    ) -> None:
        self.repository = repository
        self.provider = provider

    def create_project(self, data: dict[str, Any], actor: str | None = None) -> dict[str, Any]:
        website = normalize_blog_url(data["primary_website"])
        parsed = urlsplit(website)
        values = {
            "client_name": _required(data["client_name"], "client_name", 200),
            "primary_website": website,
            "normalized_origin": f"{parsed.scheme}://{parsed.netloc}",
            "primary_market": _required(data["primary_market"], "primary_market", 200),
            "service_area_notes": _text(data.get("service_area_notes"), 5000),
            "core_services_json": json.dumps(_strings(data.get("core_services", []), 100, 300)),
            "important_pages_json": json.dumps(_urls(data.get("important_pages", []))),
            "compliance_notes": _text(data.get("compliance_notes"), 5000),
            "status": ProjectStatus.DRAFT.value,
        }
        return self.repository.create_project(values, actor)

    def update_project(
        self, project_id: str, data: dict[str, Any], revision: int, actor: str | None = None
    ) -> dict[str, Any]:
        current = self.repository.project(project_id)
        values: dict[str, Any] = {}
        if "status" in data:
            target = ProjectStatus(data["status"])
            validate_project_transition(ProjectStatus(current["status"]), target)
            values["status"] = target.value
        mapping = {
            "client_name": 200,
            "primary_market": 200,
            "service_area_notes": 5000,
            "compliance_notes": 5000,
        }
        for key, maximum in mapping.items():
            if key in data:
                values[key] = (
                    _required(data[key], key, maximum)
                    if key in {"client_name", "primary_market"}
                    else _text(data[key], maximum)
                )
        if "core_services" in data:
            values["core_services_json"] = json.dumps(_strings(data["core_services"], 100, 300))
        if "important_pages" in data:
            values["important_pages_json"] = json.dumps(_urls(data["important_pages"]))
        return self.repository.update_project(project_id, values, revision, actor)

    def add_page(
        self, project_id: str, data: dict[str, Any], actor: str | None = None
    ) -> dict[str, Any]:
        original = _required(data["url"], "url", 4096)
        normalized = normalize_blog_url(original)
        return self.repository.add_page(
            project_id,
            {
                "original_url": original,
                "normalized_url": normalized,
                "canonical_url": normalize_blog_url(data["canonical_url"])
                if data.get("canonical_url")
                else None,
                "source_type": SourceType(data.get("source_type", "manual")).value,
                "source_reference": data.get("source_reference"),
                "provenance_json": json.dumps(data.get("provenance", {}), sort_keys=True),
                "inclusion_state": InclusionState(
                    data.get("inclusion_state", "needs_review")
                ).value,
                "title": _optional(data.get("title"), 1000),
                "meta_description": None,
                "h1": None,
                "publication_date": None,
                "modified_date": None,
                "author": None,
                "http_status": data.get("http_status"),
                "indexability": data.get("indexability"),
                "word_count": None,
            },
            actor,
        )

    def preview_import(self, source_reference: str) -> tuple[EvidenceCandidate, ...]:
        if self.provider is None:
            raise ValueError("blog_strategy_evidence_provider_unavailable")
        return self.provider.preview(_required(source_reference, "source_reference", 128))

    def import_pages(
        self,
        project_id: str,
        source_reference: str,
        selected_urls: list[str],
        actor: str | None = None,
    ) -> ImportReport:
        candidates = {
            normalize_blog_url(item.url): item for item in self.preview_import(source_reference)
        }
        existing = {page["normalized_url"] for page in self.repository.pages(project_id)}
        imported: list[str] = []
        skipped = conflicted = 0
        for raw in selected_urls:
            identity = normalize_blog_url(raw)
            candidate = candidates.get(identity)
            if candidate is None:
                conflicted += 1
            elif identity in existing:
                skipped += 1
            else:
                page = self.add_page(
                    project_id,
                    {
                        "url": candidate.url,
                        "canonical_url": candidate.canonical_url,
                        "source_type": "crawl",
                        "source_reference": source_reference,
                        "provenance": {
                            "provider": "page_evidence",
                            "source_reference": source_reference,
                        },
                        "inclusion_state": "needs_review",
                        "title": candidate.title,
                        "http_status": candidate.http_status,
                        "indexability": candidate.indexability,
                    },
                    actor,
                )
                existing.add(identity)
                imported.append(page["page_id"])
        return ImportReport(len(imported), skipped, conflicted, tuple(imported))

    def update_page(
        self,
        project_id: str,
        page_id: str,
        data: dict[str, Any],
        revision: int,
        actor: str | None = None,
    ) -> dict[str, Any]:
        values: dict[str, Any] = {}
        enums = {
            "inclusion_state": InclusionState,
            "search_intent": SearchIntent,
            "content_role": ContentRole,
            "claim_risk": ClaimRisk,
            "membership_role": MembershipRole,
            "action": StrategyAction,
            "priority": Priority,
        }
        for key, enum_type in enums.items():
            if key in data:
                values[key] = enum_type(data[key]).value
        for key in (
            "primary_topic",
            "audience_question",
            "funnel_stage",
            "geographic_intent",
            "supported_page",
            "supported_area",
            "time_sensitivity",
            "rationale",
            "destination_page",
            "notes",
        ):
            if key in data:
                values[key] = _text(data[key], 5000)
        if "secondary_topics" in data:
            values["secondary_topics_json"] = json.dumps(
                _strings(data["secondary_topics"], 50, 300)
            )
        if "family_id" in data:
            if data["family_id"] is not None:
                self.repository.family(project_id, data["family_id"])
            values["family_id"] = data["family_id"]
        if "human_reviewed" in data:
            values["human_reviewed"] = bool(data["human_reviewed"])
        if "approved" in data:
            values["approved"] = bool(data["approved"])
            values["approved_by"] = actor if values["approved"] else None
            values["approved_at"] = datetime.now(UTC) if values["approved"] else None
        return self.repository.update_page(project_id, page_id, values, revision, actor)

    def create_family(
        self, project_id: str, data: dict[str, Any], actor: str | None = None
    ) -> dict[str, Any]:
        primary = data.get("primary_guide_page_id")
        if primary:
            self.repository.page(project_id, primary)
        return self.repository.create_family(
            project_id,
            {
                "name": _required(data["name"], "name", 200),
                "description": _text(data.get("description"), 5000),
                "primary_guide_page_id": primary,
                "supported_page": _text(data.get("supported_page"), 4096),
                "status": TopicFamilyStatus.ACTIVE.value,
                "merged_into_family_id": None,
                "notes": _text(data.get("notes"), 5000),
            },
            actor,
        )

    def update_family(
        self,
        project_id: str,
        family_id: str,
        data: dict[str, Any],
        revision: int,
        actor: str | None = None,
    ) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for key, maximum in {
            "name": 200,
            "description": 5000,
            "supported_page": 4096,
            "notes": 5000,
        }.items():
            if key in data:
                values[key] = (
                    _required(data[key], key, maximum)
                    if key == "name"
                    else _text(data[key], maximum)
                )
        if "status" in data:
            values["status"] = TopicFamilyStatus(data["status"]).value
        if "primary_guide_page_id" in data:
            if data["primary_guide_page_id"]:
                self.repository.page(project_id, data["primary_guide_page_id"])
            values["primary_guide_page_id"] = data["primary_guide_page_id"]
        return self.repository.update_family(project_id, family_id, values, revision, actor)

    def create_overlap(
        self, project_id: str, data: dict[str, Any], actor: str | None = None
    ) -> dict[str, Any]:
        page_ids = tuple(dict.fromkeys(data["page_ids"]))
        if len(page_ids) < 2:
            raise ValueError("blog_strategy_overlap_pages_invalid")
        for page_id in page_ids:
            self.repository.page(project_id, page_id)
        preferred = data.get("preferred_page_id")
        if preferred is not None and preferred not in page_ids:
            raise ValueError("blog_strategy_preferred_page_invalid")
        return self.repository.create_overlap(
            project_id,
            {
                "page_ids_json": json.dumps(page_ids),
                "concern_type": ConcernType(data["concern_type"]).value,
                "severity": _severity(data.get("severity", "medium")),
                "notes": _text(data.get("notes"), 5000),
                "preferred_page_id": preferred,
                "review_state": ReviewState.OPEN.value,
                "resolution_notes": "",
            },
            actor,
        )

    def update_overlap(
        self,
        project_id: str,
        overlap_id: str,
        data: dict[str, Any],
        revision: int,
        actor: str | None = None,
    ) -> dict[str, Any]:
        current = self.repository.overlap(project_id, overlap_id)
        values: dict[str, Any] = {}
        if "review_state" in data:
            values["review_state"] = ReviewState(data["review_state"]).value
        if "preferred_page_id" in data:
            if (
                data["preferred_page_id"] is not None
                and data["preferred_page_id"] not in current["page_ids"]
            ):
                raise ValueError("blog_strategy_preferred_page_invalid")
            values["preferred_page_id"] = data["preferred_page_id"]
        for key in ("notes", "resolution_notes"):
            if key in data:
                values[key] = _text(data[key], 5000)
        return self.repository.update_overlap(project_id, overlap_id, values, revision, actor)

    def readiness(self, project_id: str) -> ExportReadiness:
        pages = [
            page
            for page in self.repository.pages(project_id)
            if page["inclusion_state"] == "included"
        ]
        overlaps = self.repository.overlaps(project_id)
        warnings = []
        if any(not page["human_reviewed"] for page in pages):
            warnings.append("missing_classifications")
        if any(page["family_id"] is None for page in pages):
            warnings.append("unassigned_topic_families")
        if any(item["review_state"] == "open" and item["severity"] == "high" for item in overlaps):
            warnings.append("open_high_severity_overlap")
        if any(page["action"] == "undecided" for page in pages):
            warnings.append("undecided_actions")
        if any(
            page["claim_risk"] in {"high", "requires_professional_review"}
            and page["action"] != "claim_review"
            for page in pages
        ):
            warnings.append("high_risk_without_claim_review")
        if any(not page["approved"] for page in pages):
            warnings.append("missing_approvals")
        return ExportReadiness(not warnings, tuple(warnings))

    def export(
        self, project_id: str, *, acknowledge_warnings: bool = False
    ) -> tuple[str, bytes, dict[str, Any]]:
        project = self.repository.project(project_id)
        readiness = self.readiness(project_id)
        if readiness.warnings and not acknowledge_warnings:
            raise ValueError("blog_strategy_export_not_ready")
        pages = [
            page
            for page in self.repository.pages(project_id)
            if page["inclusion_state"] == "included"
        ]
        families = {item["family_id"]: item for item in self.repository.families(project_id)}
        overlaps = self.repository.overlaps(project_id)
        page_by_id = {page["page_id"]: page for page in pages}
        rows = []
        for page in pages:
            related = [item for item in overlaps if page["page_id"] in item["page_ids"]]
            rows.append(
                [
                    project["client_name"],
                    project["primary_website"],
                    page["original_url"],
                    page["title"] or "",
                    page["canonical_url"] or "",
                    page["inclusion_state"],
                    page["primary_topic"],
                    "; ".join(page["secondary_topics"]),
                    page["search_intent"],
                    page["audience_question"],
                    page["content_role"],
                    families.get(page["family_id"], {}).get("name", ""),
                    page["supported_page"],
                    page["geographic_intent"],
                    page["claim_risk"],
                    "; ".join(item["concern_type"] for item in related),
                    "; ".join(
                        page_by_id[other]["original_url"]
                        for item in related
                        for other in item["page_ids"]
                        if other != page["page_id"] and other in page_by_id
                    ),
                    "; ".join(item["review_state"] for item in related),
                    "; ".join(
                        page_by_id[item["preferred_page_id"]]["original_url"]
                        for item in related
                        if item["preferred_page_id"] in page_by_id
                    ),
                    page["action"],
                    page["priority"],
                    page["destination_page"],
                    page["rationale"],
                    "Yes" if page["approved"] else "No",
                    page["notes"],
                    f"{page['source_type']}:{page['source_reference'] or 'manual'}",
                    page["updated_at"].date().isoformat(),
                ]
            )
        payload = build_xlsx(rows)
        validation = validate_xlsx(payload, len(rows))
        slug = (
            "-".join(
                filter(
                    None,
                    (
                        part.casefold()
                        for part in "".join(
                            character if character.isalnum() else " "
                            for character in project["client_name"]
                        ).split()
                    ),
                )
            )
            or "client"
        )
        return f"{slug}-blog-strategy.xlsx", payload, validation


def _required(value: Any, field: str, maximum: int) -> str:
    text = _text(value, maximum)
    if not text:
        raise ValueError(f"blog_strategy_{field}_required")
    return text


def _text(value: Any, maximum: int) -> str:
    text = "" if value is None else str(value).strip()
    if len(text) > maximum:
        raise ValueError("blog_strategy_value_too_long")
    return text


def _optional(value: Any, maximum: int) -> str | None:
    text = _text(value, maximum)
    return text or None


def _strings(values: Any, maximum_count: int, maximum_length: int) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)) or len(values) > maximum_count:
        raise ValueError("blog_strategy_list_invalid")
    return tuple(_required(value, "list_item", maximum_length) for value in values)


def _urls(values: Any) -> tuple[str, ...]:
    return tuple(normalize_blog_url(value) for value in _strings(values, 100, 4096))


def _severity(value: Any) -> str:
    if value not in {"low", "medium", "high"}:
        raise ValueError("blog_strategy_severity_invalid")
    return str(value)
