"""Evidence-backed, bounded image and alt-text analysis."""

# ruff: noqa: ANN401, ARG002, C901, E501, FBT001, PLR0911, PLR0913, PLR2004

from __future__ import annotations

import asyncio
import csv
import io
import json
from collections import defaultdict
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import urlsplit

from sqlalchemy import or_

from musimack_tools.domain.artifacts import ArtifactType
from musimack_tools.domain.image_audit import (
    AUDIT_ORDERING,
    GROUP_ORDERING,
    IMAGE_EVIDENCE_VERSION,
    OCCURRENCE_ORDERING,
    PAGE_ORDERING,
    RECOMMENDATION_ORDERING,
    RESOURCE_ORDERING,
    AltTextState,
    Confidence,
    DimensionState,
    ImageAction,
    ImageAuditConfiguration,
    ImageAuditLifecycle,
    ImageExportFormat,
    ImageResourceState,
    LoadingState,
    Severity,
    audit_identity,
    classify_alt,
    classify_dimensions,
    classify_loading,
    decode_cursor,
    encode_cursor,
    filter_fingerprint,
    stable_identity,
    stable_json,
)
from musimack_tools.persistence.image_audit_models import (
    ImageAuditResourceModel,
    ImageDuplicateGroupModel,
    ImageFindingModel,
    ImageOccurrenceAnalysisModel,
    ImagePageSummaryModel,
    ImageRecommendationModel,
)

if TYPE_CHECKING:
    from musimack_tools.artifacts.service import ArtifactService
    from musimack_tools.persistence.image_audit_repository import SQLAlchemyImageAuditRepository


class ImageResourceVerifier(Protocol):
    """Narrow adapter implemented only through the accepted safe-fetch boundary."""

    async def verify(self, url: str, *, maximum_bytes: int) -> dict[str, Any]: ...


class ImageAuditService:
    def __init__(
        self,
        configuration: ImageAuditConfiguration,
        repository: SQLAlchemyImageAuditRepository,
        artifacts: ArtifactService | None = None,
        verifier: ImageResourceVerifier | None = None,
    ) -> None:
        self.configuration = configuration
        self._repository = repository
        self._artifacts = artifacts
        self._verifier = verifier
        self._repository.reconcile_interrupted()

    def evidence_status(self, run_id: str) -> dict[str, Any]:
        context = self._repository.run_context(run_id)
        scope = self._repository.run_scope_snapshot(run_id)
        if context is None:
            raise ValueError("image_audit_run_not_found")
        versions = self._repository.image_evidence_versions(run_id)
        version_compatible = not versions or versions == (IMAGE_EVIDENCE_VERSION,)
        return {
            "run_id": run_id,
            "terminal": context[2],
            "page_evidence_count": context[3],
            "image_evidence_count": context[4],
            "scope_available": scope is not None,
            "evidence_versions": versions,
            "compatible": (
                context[2]
                and context[3] > 0
                and context[4] > 0
                and scope is not None
                and version_compatible
            ),
        }

    def create_audit(self, run_id: str) -> dict[str, Any]:
        if not self.configuration.enabled:
            raise ValueError("image_audit_disabled")
        context = self._context(run_id)
        if self._repository.image_evidence_versions(run_id) != (IMAGE_EVIDENCE_VERSION,):
            raise ValueError("image_audit_evidence_version_unsupported")
        scope = self._repository.run_scope_snapshot(run_id)
        if scope is None:
            raise ValueError("image_audit_scope_unavailable")
        identifier = audit_identity(run_id, self.configuration)
        return self._repository.create(
            identifier,
            context[0],
            run_id,
            {"mode": scope[0].value, "approved_hosts": scope[1]},
            self.configuration,
        )

    async def execute_audit(self, audit_id: str) -> dict[str, Any]:
        audit = self.get(audit_id)
        if audit["state"] in {"completed", "completed_with_warnings", "failed", "cancelled"}:
            raise ValueError("image_audit_already_terminal")
        if not self._repository.claim_execution(audit_id):
            raise ValueError("image_audit_already_executing")
        try:
            return await self._execute_claimed(audit_id, audit)
        except asyncio.CancelledError:
            self._repository.transition(
                audit_id, ImageAuditLifecycle.CANCELLED, "image_audit_cancelled"
            )
            raise
        except Exception:
            self._repository.fail_if_running(audit_id, "image_audit_execution_failed")
            raise

    async def _execute_claimed(self, audit_id: str, audit: dict[str, Any]) -> dict[str, Any]:
        run_id = str(audit["run_id"])
        images = self._repository.images(run_id)
        pages = self._repository.pages(run_id)
        if not pages:
            raise ValueError("image_audit_page_evidence_unavailable")
        if not images:
            raise ValueError("image_audit_image_evidence_unavailable")
        self._repository.transition(audit_id, ImageAuditLifecycle.BUILDING_INVENTORY)
        grouped = self._group_images(images)
        page_by_identity: dict[str, dict[str, Any]] = {}
        for page in pages:
            requested_identity = page.get("requested_url_identity")
            final_identity = page.get("final_url_identity")
            if requested_identity:
                page_by_identity[str(requested_identity)] = page
            if final_identity:
                page_by_identity.setdefault(str(final_identity), page)
        self._repository.transition(audit_id, ImageAuditLifecycle.RESOLVING_RESOURCES)
        resources: dict[str, dict[str, Any]] = {}
        warnings = 0
        verified = 0
        for sequence, (identity, occurrences) in enumerate(grouped.items()):
            resolution, consumed = await self._resolve_resource(
                identity, occurrences, page_by_identity, verified
            )
            verified += consumed
            warnings += resolution["resource_state"] == ImageResourceState.UNVERIFIED.value
            values = {
                **resolution,
                **self._reuse_metrics(occurrences, len(pages), str(resolution["resource_state"])),
                "resource_id": stable_identity(audit_id, "resource", identity),
                "image_identity": identity,
                "resource_sequence": sequence,
            }
            resources[identity] = self._repository.persist_resource(audit_id, values)
        self._repository.transition(audit_id, ImageAuditLifecycle.CLASSIFYING_ALT_TEXT)
        analyses = self._analyze_occurrences(audit_id, images, resources)
        for analysis in analyses:
            self._repository.persist_occurrence(audit_id, analysis)
        self._repository.transition(audit_id, ImageAuditLifecycle.ANALYZING_REUSE)
        groups = self._duplicate_groups(audit_id, images)
        for group in groups:
            self._repository.persist_group(audit_id, group)
        summaries = self._page_summaries(audit_id, images, analyses, resources)
        for summary in summaries:
            self._repository.persist_page(audit_id, summary)
        self._persist_findings(audit_id, analyses, resources, groups)
        self._repository.transition(audit_id, ImageAuditLifecycle.BUILDING_RECOMMENDATIONS)
        self._persist_recommendations(audit_id, analyses, resources, groups)
        return self._repository.finalize(audit_id, warnings)

    @staticmethod
    def _group_images(images: tuple[dict[str, Any], ...]) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for image in images:
            identity = str(
                image.get("image_identity") or stable_identity("unresolved", image["image_id"])
            )
            grouped[identity].append(image)
        return dict(
            sorted(
                grouped.items(),
                key=lambda item: (min(int(row["occurrence_sequence"]) for row in item[1]), item[0]),
            )
        )

    async def _resolve_resource(
        self,
        identity: str,
        occurrences: list[dict[str, Any]],
        page_by_identity: dict[str, dict[str, Any]],
        verified: int,
    ) -> tuple[dict[str, Any], int]:
        first = occurrences[0]
        url = first.get("resolved_src") or first.get("primary_candidate")
        scheme = str(first.get("source_scheme") or "").casefold()
        base = {
            "representative_url": url,
            "http_status": None,
            "status_class": None,
            "content_type": None,
            "final_image_url": None,
            "response_byte_count": None,
            "redirect_state": "none",
        }
        if first.get("data_fingerprint"):
            return (
                {
                    **base,
                    "scope_state": "inline",
                    "fetch_state": "not_fetched",
                    "resource_state": ImageResourceState.DATA.value,
                    "severity": Severity.INFO.value,
                },
                0,
            )
        if isinstance(url, str) and _is_placeholder_url(url):
            return (
                {
                    **base,
                    "scope_state": "in_scope",
                    "fetch_state": "not_required",
                    "resource_state": ImageResourceState.PLACEHOLDER.value,
                    "severity": Severity.MEDIUM.value,
                },
                0,
            )
        if first.get("unsupported_scheme") or scheme not in {"http", "https"}:
            return (
                {
                    **base,
                    "scope_state": "unsupported",
                    "fetch_state": "not_fetched",
                    "resource_state": ImageResourceState.UNSUPPORTED.value,
                    "severity": Severity.LOW.value,
                },
                0,
            )
        source_host = urlsplit(
            str(first.get("source_final_url") or first["source_requested_url"])
        ).hostname
        target_host = urlsplit(str(url or "")).hostname
        cross_host = bool(
            source_host and target_host and source_host.casefold() != target_host.casefold()
        )
        if first.get("in_scope") is False or (first.get("in_scope") is None and cross_host):
            state = ImageResourceState.EXTERNAL if cross_host else ImageResourceState.OUT_OF_SCOPE
            return (
                {
                    **base,
                    "scope_state": "external"
                    if state is ImageResourceState.EXTERNAL
                    else "out_of_scope",
                    "fetch_state": "not_fetched",
                    "resource_state": state.value,
                    "severity": Severity.INFO.value,
                },
                0,
            )
        page = page_by_identity.get(identity)
        if page is not None:
            status = page.get("http_status")
            content = str(page.get("content_type") or "") or None
            state = _resource_state(
                status,
                content,
                int(page.get("redirect_count") or 0),
                str(page.get("final_url") or url or ""),
            )
            return (
                {
                    **base,
                    "scope_state": "in_scope",
                    "fetch_state": "existing_evidence",
                    "http_status": status,
                    "status_class": int(status) // 100 if status else None,
                    "content_type": content,
                    "final_image_url": page.get("final_url"),
                    "redirect_state": "redirected" if page.get("redirect_count") else "none",
                    "resource_state": state.value,
                    "severity": _resource_severity(state, occurrences).value,
                },
                0,
            )
        verifier = self._verifier
        should_verify = (
            self.configuration.verify_internal_images
            and verifier is not None
            and verified < self.configuration.maximum_unique_image_fetches
            and isinstance(url, str)
        )
        if should_verify and verifier is not None and isinstance(url, str):
            result = await verifier.verify(
                url, maximum_bytes=self.configuration.maximum_image_response_bytes
            )
            status = result.get("http_status")
            content = result.get("content_type")
            state = _resource_state(
                status,
                content,
                int(result.get("redirect_count") or 0),
                str(result.get("final_url") or url),
            )
            return (
                {
                    **base,
                    "scope_state": "in_scope",
                    "fetch_state": str(result.get("fetch_state") or "verified"),
                    "http_status": status,
                    "status_class": int(status) // 100 if status else None,
                    "content_type": content,
                    "final_image_url": result.get("final_url"),
                    "response_byte_count": result.get("response_byte_count"),
                    "redirect_state": "redirected" if result.get("redirect_count") else "none",
                    "resource_state": state.value,
                    "severity": _resource_severity(state, occurrences).value,
                },
                1,
            )
        return (
            {
                **base,
                "scope_state": "in_scope",
                "fetch_state": "evidence_unavailable",
                "resource_state": ImageResourceState.UNVERIFIED.value,
                "severity": Severity.LOW.value,
            },
            0,
        )

    def _reuse_metrics(
        self,
        occurrences: list[dict[str, Any]],
        parsed_pages: int,
        resource_state: str,
    ) -> dict[str, Any]:
        pages = {str(item["source_evidence_id"]) for item in occurrences}
        page_count = len(pages)
        sitewide = (
            parsed_pages >= self.configuration.minimum_sitewide_pages
            and page_count >= self.configuration.minimum_sitewide_pages
            and page_count / parsed_pages >= self.configuration.sitewide_source_ratio
        )
        return {
            "unique_source_page_count": page_count,
            "total_occurrence_count": len(occurrences),
            "unique_alt_count": len(
                {
                    str(item.get("alt_normalized") or "").casefold()
                    for item in occurrences
                    if item.get("alt_normalized")
                }
            ),
            "missing_alt_count": sum(not item["alt_present"] for item in occurrences),
            "empty_alt_count": sum(
                item["alt_present"] and not str(item.get("alt_normalized") or "")
                for item in occurrences
            ),
            "linked_occurrence_count": sum(bool(item["linked"]) for item in occurrences),
            "broken_occurrence_count": (
                len(occurrences) if resource_state == ImageResourceState.BROKEN.value else 0
            ),
            "redirecting_occurrence_count": (
                len(occurrences) if resource_state == ImageResourceState.REDIRECTING.value else 0
            ),
            "width_consistent": len({item.get("width_value") for item in occurrences}) <= 1,
            "height_consistent": len({item.get("height_value") for item in occurrences}) <= 1,
            "loading_distribution_json": stable_json(
                {
                    str(value or "missing"): sum(
                        item.get("loading_value") == value for item in occurrences
                    )
                    for value in sorted(
                        {item.get("loading_value") for item in occurrences},
                        key=lambda item: str(item or ""),
                    )
                }
            ),
            "earliest_discovery_sequence": min(
                int(item["source_discovery_sequence"]) for item in occurrences
            ),
            "minimum_source_depth": min(int(item["source_crawl_depth"]) for item in occurrences),
            "maximum_source_depth": max(int(item["source_crawl_depth"]) for item in occurrences),
            "sitewide_state": "sitewide_candidate" if sitewide else "not_sitewide",
        }

    def _analyze_occurrences(
        self,
        audit_id: str,
        images: tuple[dict[str, Any], ...],
        resources: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for sequence, image in enumerate(images):
            identity = str(
                image.get("image_identity") or stable_identity("unresolved", image["image_id"])
            )
            resource = resources[identity]
            alt = classify_alt(
                present=bool(image["alt_present"]),
                raw_value=image.get("alt_raw"),
                linked=bool(image["linked"]),
                decorative=bool(image["decorative_explicit"]),
                maximum_length=self.configuration.maximum_alt_length,
            )
            dimension = classify_dimensions(image.get("width_value"), image.get("height_value"))
            loading = classify_loading(
                image.get("loading_value"), image.get("decoding_value"), image.get("fetch_priority")
            )
            severity, reason = _occurrence_severity(
                alt,
                dimension,
                loading,
                str(resource["resource_state"]),
                bool(image["linked"]),
                int(resource["unique_source_page_count"]),
            )
            result.append(
                {
                    "analysis_id": stable_identity(audit_id, "occurrence", image["image_id"]),
                    "image_evidence_id": image["image_id"],
                    "source_evidence_id": image["source_evidence_id"],
                    "resource_id": resource["resource_id"],
                    "source_page_url": image.get("source_final_url")
                    or image["source_requested_url"],
                    "image_url": image.get("resolved_src") or image.get("primary_candidate"),
                    "raw_src": image.get("raw_src"),
                    "primary_candidate": image.get("primary_candidate"),
                    "element_type": image["element_type"],
                    "alt_raw": image.get("alt_raw"),
                    "alt_normalized": image.get("alt_normalized"),
                    "width_value": image.get("width_value"),
                    "height_value": image.get("height_value"),
                    "loading_value": image.get("loading_value"),
                    "decoding_value": image.get("decoding_value"),
                    "fetch_priority": image.get("fetch_priority"),
                    "alt_state": alt.value,
                    "dimension_state": dimension.value,
                    "loading_state": loading.value,
                    "linked_image": bool(image["linked"]),
                    "decorative": bool(image["decorative_explicit"]),
                    "severity": severity.value,
                    "primary_reason": reason,
                    "occurrence_sequence": sequence,
                }
            )
        return result

    def _duplicate_groups(
        self, audit_id: str, images: tuple[dict[str, Any], ...]
    ) -> list[dict[str, Any]]:
        by_alt: dict[str, list[dict[str, Any]]] = defaultdict(list)
        by_image: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for image in images:
            alt = str(image.get("alt_normalized") or "").casefold()
            identity = str(image.get("image_identity") or "")
            if alt:
                by_alt[alt].append(image)
            if identity:
                by_image[identity].append(image)
        candidates: list[tuple[str, str, list[dict[str, Any]]]] = []
        for alt, rows in by_alt.items():
            if len({row.get("image_identity") for row in rows}) > 1:
                candidates.append(("same_alt_multiple_images", stable_identity(alt), rows))
        for identity, rows in by_image.items():
            if (
                len(
                    {
                        str(row.get("alt_normalized") or "").casefold()
                        for row in rows
                        if row.get("alt_normalized")
                    }
                )
                > 1
            ):
                candidates.append(("same_image_inconsistent_alt", stable_identity(identity), rows))
        result: list[dict[str, Any]] = []
        for sequence, (kind, identity, rows) in enumerate(
            sorted(candidates, key=lambda item: (item[0], item[1]))
        ):
            images_set = sorted(
                {str(row.get("resolved_src") or row.get("primary_candidate") or "") for row in rows}
            )
            pages = sorted(
                {str(row.get("source_final_url") or row["source_requested_url"]) for row in rows}
            )
            result.append(
                {
                    "group_id": stable_identity(audit_id, "group", kind, identity),
                    "group_type": kind,
                    "group_identity": identity,
                    "representative_alt": rows[0].get("alt_normalized"),
                    "image_count": len({row.get("image_identity") for row in rows}),
                    "source_page_count": len(pages),
                    "occurrence_count": len(rows),
                    "severity": Severity.MEDIUM.value
                    if len(pages) >= self.configuration.minimum_sitewide_pages
                    else Severity.LOW.value,
                    "sample_images_json": stable_json(images_set[:10]),
                    "sample_pages_json": stable_json(pages[:10]),
                    "group_sequence": sequence,
                }
            )
        return result

    def _page_summaries(
        self,
        audit_id: str,
        images: tuple[dict[str, Any], ...],
        analyses: list[dict[str, Any]],
        resources: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        images_by_id = {str(row["image_id"]): row for row in images}
        by_page: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for analysis in analyses:
            by_page[str(analysis["source_evidence_id"])].append(analysis)
        result: list[dict[str, Any]] = []
        for sequence, (page_id, rows) in enumerate(
            sorted(
                by_page.items(),
                key=lambda item: min(int(row["occurrence_sequence"]) for row in item[1]),
            )
        ):
            evidence = [images_by_id[str(row["image_evidence_id"])] for row in rows]
            states = [
                str(
                    resources[
                        str(
                            item.get("image_identity")
                            or stable_identity("unresolved", item["image_id"])
                        )
                    ]["resource_state"]
                )
                for item in evidence
            ]
            severity = max(
                (Severity(str(row["severity"])) for row in rows),
                key=lambda value: _SEVERITY_RANK[value],
            )
            result.append(
                {
                    "page_summary_id": stable_identity(audit_id, "page", page_id),
                    "source_evidence_id": page_id,
                    "source_page_url": rows[0]["source_page_url"],
                    "image_occurrence_count": len(rows),
                    "unique_image_count": len(
                        {item.get("image_identity") or item["image_id"] for item in evidence}
                    ),
                    "missing_alt_count": sum(
                        row["alt_state"] == AltTextState.MISSING.value for row in rows
                    ),
                    "empty_alt_count": sum(
                        row["alt_state"]
                        in {
                            AltTextState.EMPTY.value,
                            AltTextState.WHITESPACE.value,
                            AltTextState.LINK_EMPTY.value,
                        }
                        for row in rows
                    ),
                    "broken_image_count": states.count(ImageResourceState.BROKEN.value),
                    "redirecting_image_count": states.count(ImageResourceState.REDIRECTING.value),
                    "missing_dimensions_count": sum(
                        row["dimension_state"] != DimensionState.PRESENT.value for row in rows
                    ),
                    "loading_review_count": sum(
                        row["loading_state"]
                        in {
                            LoadingState.MISSING.value,
                            LoadingState.INVALID.value,
                            LoadingState.REVIEW.value,
                        }
                        for row in rows
                    ),
                    "generic_alt_count": sum(
                        row["alt_state"] == AltTextState.GENERIC.value for row in rows
                    ),
                    "filename_alt_count": sum(
                        row["alt_state"] == AltTextState.FILENAME.value for row in rows
                    ),
                    "duplicate_alt_count": 0,
                    "external_image_count": states.count(ImageResourceState.EXTERNAL.value),
                    "data_image_count": states.count(ImageResourceState.DATA.value),
                    "severity": severity.value,
                    "page_sequence": sequence,
                }
            )
        return result

    def _persist_findings(
        self,
        audit_id: str,
        analyses: list[dict[str, Any]],
        resources: dict[str, dict[str, Any]],
        groups: list[dict[str, Any]],
    ) -> None:
        sequence = 0
        for row in analyses:
            if row["severity"] == Severity.INFO.value:
                continue
            self._repository.persist_finding(
                audit_id,
                {
                    "finding_id": stable_identity(audit_id, "finding", sequence),
                    "resource_id": row["resource_id"],
                    "analysis_id": row["analysis_id"],
                    "page_summary_id": None,
                    "duplicate_group_id": None,
                    "stable_code": row["primary_reason"],
                    "finding_type": _finding_type(row),
                    "severity": row["severity"],
                    "safe_message": _safe_message(row["primary_reason"]),
                    "context_json": stable_json(
                        {"source_page": row["source_page_url"], "image_url": row["image_url"]}
                    ),
                    "finding_sequence": sequence,
                },
            )
            sequence += 1
        for group in groups:
            self._repository.persist_finding(
                audit_id,
                {
                    "finding_id": stable_identity(audit_id, "finding", sequence),
                    "resource_id": None,
                    "analysis_id": None,
                    "page_summary_id": None,
                    "duplicate_group_id": group["group_id"],
                    "stable_code": group["group_type"],
                    "finding_type": "duplicate",
                    "severity": group["severity"],
                    "safe_message": "Image and alternative-text reuse requires human review.",
                    "context_json": stable_json(
                        {
                            "image_count": group["image_count"],
                            "source_page_count": group["source_page_count"],
                        }
                    ),
                    "finding_sequence": sequence,
                },
            )
            sequence += 1

    def _persist_recommendations(
        self,
        audit_id: str,
        analyses: list[dict[str, Any]],
        resources: dict[str, dict[str, Any]],
        groups: list[dict[str, Any]],
    ) -> None:
        sequence = 0
        resource_by_id = {str(row["resource_id"]): row for row in resources.values()}
        for row in analyses:
            action, confidence = _recommendation(row)
            if action is ImageAction.NO_ACTION:
                continue
            resource = resource_by_id[str(row["resource_id"])]
            self._repository.persist_recommendation(
                audit_id,
                {
                    "recommendation_id": stable_identity(audit_id, "recommendation", sequence),
                    "analysis_id": row["analysis_id"],
                    "resource_id": row["resource_id"],
                    "source_page_url": row["source_page_url"],
                    "image_url": row["image_url"],
                    "image_identity": resource["image_identity"],
                    "action": action.value,
                    "confidence": confidence.value,
                    "severity": row["severity"],
                    "reason_code": row["primary_reason"],
                    "human_review_state": "required",
                    "supporting_metrics_json": stable_json(
                        {
                            "unique_source_pages": resource["unique_source_page_count"],
                            "total_occurrences": resource["total_occurrence_count"],
                            "linked": row["linked_image"],
                            "decorative": row["decorative"],
                        }
                    ),
                    "recommendation_sequence": sequence,
                },
            )
            sequence += 1
        for group in groups:
            self._repository.persist_recommendation(
                audit_id,
                {
                    "recommendation_id": stable_identity(audit_id, "recommendation", sequence),
                    "analysis_id": None,
                    "resource_id": None,
                    "source_page_url": None,
                    "image_url": None,
                    "image_identity": None,
                    "action": ImageAction.REVIEW_DUPLICATE.value,
                    "confidence": Confidence.LOW.value,
                    "severity": group["severity"],
                    "reason_code": group["group_type"],
                    "human_review_state": "required",
                    "supporting_metrics_json": stable_json(
                        {
                            "image_count": group["image_count"],
                            "source_page_count": group["source_page_count"],
                            "occurrence_count": group["occurrence_count"],
                        }
                    ),
                    "recommendation_sequence": sequence,
                },
            )
            sequence += 1

    def get(self, audit_id: str) -> dict[str, Any]:
        value = self._repository.get(audit_id)
        if value is None:
            raise ValueError("image_audit_not_found")
        return value

    def summary(self, audit_id: str) -> dict[str, Any]:
        return self.get(audit_id)

    def list_audits(
        self, cursor: str | None = None, page_size: int | None = None
    ) -> dict[str, Any]:
        return self._page(
            self._repository.list_audits(), "audits", AUDIT_ORDERING, cursor, page_size, {}
        )

    def list_resources(
        self,
        audit_id: str,
        cursor: str | None = None,
        page_size: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._model_page(
            audit_id,
            ImageAuditResourceModel,
            "resources",
            RESOURCE_ORDERING,
            (ImageAuditResourceModel.resource_sequence, ImageAuditResourceModel.resource_id),
            cursor,
            page_size,
            filters or {},
        )

    def list_occurrences(
        self,
        audit_id: str,
        cursor: str | None = None,
        page_size: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._model_page(
            audit_id,
            ImageOccurrenceAnalysisModel,
            "occurrences",
            OCCURRENCE_ORDERING,
            (
                ImageOccurrenceAnalysisModel.occurrence_sequence,
                ImageOccurrenceAnalysisModel.analysis_id,
            ),
            cursor,
            page_size,
            filters or {},
        )

    def list_pages(
        self,
        audit_id: str,
        cursor: str | None = None,
        page_size: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._model_page(
            audit_id,
            ImagePageSummaryModel,
            "pages",
            PAGE_ORDERING,
            (ImagePageSummaryModel.page_sequence, ImagePageSummaryModel.page_summary_id),
            cursor,
            page_size,
            filters or {},
        )

    def list_groups(
        self,
        audit_id: str,
        cursor: str | None = None,
        page_size: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._model_page(
            audit_id,
            ImageDuplicateGroupModel,
            "groups",
            GROUP_ORDERING,
            (ImageDuplicateGroupModel.group_sequence, ImageDuplicateGroupModel.group_id),
            cursor,
            page_size,
            filters or {},
        )

    def list_broken(
        self, audit_id: str, cursor: str | None = None, page_size: int | None = None
    ) -> dict[str, Any]:
        return self.list_resources(
            audit_id, cursor, page_size, {"resource_state": ImageResourceState.BROKEN.value}
        )

    def list_redirecting(
        self, audit_id: str, cursor: str | None = None, page_size: int | None = None
    ) -> dict[str, Any]:
        return self.list_resources(
            audit_id, cursor, page_size, {"resource_state": ImageResourceState.REDIRECTING.value}
        )

    def list_findings(
        self,
        audit_id: str,
        kind: str | None = None,
        cursor: str | None = None,
        page_size: int | None = None,
    ) -> dict[str, Any]:
        filters = {"finding_type": kind} if kind else {}
        return self._model_page(
            audit_id,
            ImageFindingModel,
            f"findings:{kind or 'all'}",
            "finding_sequence_asc_finding_id_asc-v1",
            (ImageFindingModel.finding_sequence, ImageFindingModel.finding_id),
            cursor,
            page_size,
            filters,
        )

    def list_recommendations(
        self,
        audit_id: str,
        cursor: str | None = None,
        page_size: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._model_page(
            audit_id,
            ImageRecommendationModel,
            "recommendations",
            RECOMMENDATION_ORDERING,
            (
                ImageRecommendationModel.recommendation_sequence,
                ImageRecommendationModel.recommendation_id,
            ),
            cursor,
            page_size,
            filters or {},
        )

    def _model_page(
        self,
        audit_id: str,
        model: Any,
        kind: str,
        ordering: str,
        order: tuple[Any, ...],
        cursor: str | None,
        page_size: int | None,
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        self.get(audit_id)
        clauses: list[Any] = []
        for key, value in filters.items():
            if value is None:
                continue
            if hasattr(model, key):
                clauses.append(getattr(model, key) == value)
            elif key == "url_search":
                columns = [
                    getattr(model, name)
                    for name in (
                        "representative_url",
                        "image_url",
                        "source_page_url",
                        "sample_images_json",
                        "sample_pages_json",
                        "context_json",
                    )
                    if hasattr(model, name)
                ]
                if not columns:
                    raise ValueError("image_audit_invalid_filter")
                clauses.append(or_(*(column.contains(value) for column in columns)))
            elif key == "alt_search":
                columns = [
                    getattr(model, name)
                    for name in ("alt_normalized", "representative_alt")
                    if hasattr(model, name)
                ]
                if not columns:
                    raise ValueError("image_audit_invalid_filter")
                clauses.append(or_(*(column.contains(value) for column in columns)))
            elif key == "source_page":
                if not hasattr(model, "source_page_url"):
                    raise ValueError("image_audit_invalid_filter")
                clauses.append(model.source_page_url.contains(value))
            elif key in {"minimum_source_page_count", "minimum_image_count"}:
                column_name = (
                    "unique_source_page_count"
                    if key == "minimum_source_page_count"
                    and hasattr(model, "unique_source_page_count")
                    else "source_page_count"
                    if key == "minimum_source_page_count"
                    else "image_count"
                )
                if not hasattr(model, column_name):
                    raise ValueError("image_audit_invalid_filter")
                clauses.append(getattr(model, column_name) >= value)
            else:
                raise ValueError("image_audit_invalid_filter")
        rows = self._repository.list_model(model, audit_id, order=order, filters=tuple(clauses))
        return self._page(rows, kind, ordering, cursor, page_size, filters)

    def _page(
        self,
        rows: tuple[dict[str, Any], ...],
        kind: str,
        ordering: str,
        cursor: str | None,
        page_size: int | None,
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        size = self._size(page_size)
        fingerprint = filter_fingerprint(filters)
        offset = decode_cursor(cursor, kind, ordering, fingerprint) if cursor else 0
        selected = rows[offset : offset + size + 1]
        return {
            "items": selected[:size],
            "next_cursor": encode_cursor(kind, ordering, fingerprint, offset + size)
            if len(selected) > size
            else None,
            "page_size": size,
            "ordering": ordering,
        }

    def create_export(self, audit_id: str, export_format: ImageExportFormat) -> dict[str, Any]:
        audit = self.get(audit_id)
        if audit["state"] not in {"completed", "completed_with_warnings"}:
            raise ValueError("image_audit_export_conflict")
        if self._artifacts is None or not self._artifacts.configuration.enabled:
            raise ValueError("image_audit_export_failed")
        limit = self.configuration.maximum_export_rows
        datasets = self._export_datasets(audit_id)
        content, row_count, truncated = _export_bytes(audit, export_format, datasets, limit)
        extension = (
            "csv"
            if export_format.value.endswith("_csv")
            else "md"
            if export_format is ImageExportFormat.MARKDOWN
            else "json"
        )
        artifact_type = (
            ArtifactType.CSV_EXPORT
            if extension == "csv"
            else ArtifactType.RUN_SUMMARY_MARKDOWN
            if extension == "md"
            else ArtifactType.RUN_SUMMARY_JSON
        )
        artifact = self._artifacts.store_bytes(
            job_id=str(audit["job_id"]),
            run_id=str(audit["run_id"]),
            artifact_type=artifact_type,
            filename=f"image-audit-{audit_id}-{export_format.value}.{extension}",
            content=content,
        )
        return self._repository.upsert_export(
            audit_id,
            stable_identity(audit_id, export_format.value),
            export_format.value,
            artifact.artifact_id,
            row_count,
            truncated,
            "completed",
        )

    def list_exports(self, audit_id: str) -> tuple[dict[str, Any], ...]:
        self.get(audit_id)
        return self._repository.list_exports(audit_id)

    def _export_datasets(self, audit_id: str) -> dict[str, list[dict[str, Any]]]:
        resources = list(
            self._repository.list_model(
                ImageAuditResourceModel,
                audit_id,
                order=(ImageAuditResourceModel.resource_sequence,),
            )
        )
        occurrences = list(
            self._repository.list_model(
                ImageOccurrenceAnalysisModel,
                audit_id,
                order=(ImageOccurrenceAnalysisModel.occurrence_sequence,),
            )
        )
        groups = list(
            self._repository.list_model(
                ImageDuplicateGroupModel,
                audit_id,
                order=(ImageDuplicateGroupModel.group_sequence,),
            )
        )
        pages = list(
            self._repository.list_model(
                ImagePageSummaryModel, audit_id, order=(ImagePageSummaryModel.page_sequence,)
            )
        )
        findings = list(
            self._repository.list_model(
                ImageFindingModel, audit_id, order=(ImageFindingModel.finding_sequence,)
            )
        )
        recommendations = list(
            self._repository.list_model(
                ImageRecommendationModel,
                audit_id,
                order=(ImageRecommendationModel.recommendation_sequence,),
            )
        )
        resource_by_id = {str(row["resource_id"]): row for row in resources}
        occurrence_by_id = {str(row["analysis_id"]): row for row in occurrences}

        def with_evidence(row: dict[str, Any]) -> dict[str, Any]:
            resource = resource_by_id.get(str(row.get("resource_id")), {})
            occurrence = occurrence_by_id.get(str(row.get("analysis_id")), {})
            return {**resource, **occurrence, **row}

        return {
            "resources": resources,
            "occurrences": [with_evidence(row) for row in occurrences],
            "groups": groups,
            "pages": pages,
            "findings": [with_evidence(row) for row in findings],
            "recommendations": [with_evidence(row) for row in recommendations],
        }

    def diagnostics(self) -> dict[str, Any]:
        return {
            "enabled": self.configuration.enabled,
            "persistence_ready": True,
            "migration_ready": True,
            "interrupted_reconciled": True,
        }

    def cleanup(self) -> int:
        return self._repository.cleanup()

    def _context(self, run_id: str) -> tuple[str, str, bool, int, int]:
        context = self._repository.run_context(run_id)
        if context is None:
            raise ValueError("image_audit_run_not_found")
        if not context[2]:
            raise ValueError("image_audit_run_not_terminal")
        if context[3] == 0:
            raise ValueError("image_audit_page_evidence_unavailable")
        if context[4] == 0:
            raise ValueError("image_audit_image_evidence_unavailable")
        return context

    def _size(self, value: int | None) -> int:
        size = value or self.configuration.default_page_size
        if not 1 <= size <= self.configuration.maximum_page_size:
            raise ValueError("image_audit_invalid_page_size")
        return size


_SEVERITY_RANK = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}
_ACCEPTED_IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/svg+xml",
    "image/avif",
    "image/x-icon",
    "image/vnd.microsoft.icon",
}


def _resource_state(
    status: Any, content_type: Any, redirects: int, url: str = ""
) -> ImageResourceState:
    if status is None:
        return ImageResourceState.UNVERIFIED
    code = int(status)
    media_type = str(content_type or "").split(";", 1)[0].strip().casefold()
    if code >= 400:
        return ImageResourceState.BROKEN
    if (
        not 200 <= code < 300
        or media_type not in _ACCEPTED_IMAGE_TYPES
        or not _mime_matches_extension(url, media_type)
    ):
        return ImageResourceState.UNVERIFIED
    return ImageResourceState.REDIRECTING if redirects else ImageResourceState.VALID


def _mime_matches_extension(url: str, media_type: str) -> bool:
    extension = (
        urlsplit(url).path.rsplit(".", 1)[-1].casefold() if "." in urlsplit(url).path else ""
    )
    accepted = {
        "jpg": {"image/jpeg"},
        "jpeg": {"image/jpeg"},
        "png": {"image/png"},
        "gif": {"image/gif"},
        "webp": {"image/webp"},
        "svg": {"image/svg+xml"},
        "avif": {"image/avif"},
        "ico": {"image/x-icon", "image/vnd.microsoft.icon"},
    }
    return extension not in accepted or media_type in accepted[extension]


def _resource_severity(state: ImageResourceState, occurrences: list[dict[str, Any]]) -> Severity:
    if state is ImageResourceState.BROKEN:
        pages = len({row["source_evidence_id"] for row in occurrences})
        return Severity.CRITICAL if pages >= 5 else Severity.HIGH
    if state is ImageResourceState.REDIRECTING:
        return Severity.MEDIUM
    return Severity.INFO if state is ImageResourceState.VALID else Severity.LOW


def _is_placeholder_url(url: str) -> bool:
    filename = urlsplit(url).path.rsplit("/", 1)[-1].casefold()
    return any(
        token in filename
        for token in ("placeholder", "coming-soon", "default-image", "image-unavailable")
    )


def _occurrence_severity(
    alt: AltTextState,
    dimension: DimensionState,
    loading: LoadingState,
    resource: str,
    linked: bool,
    reuse: int,
) -> tuple[Severity, str]:
    if resource == ImageResourceState.BROKEN.value:
        return (Severity.CRITICAL if reuse >= 5 else Severity.HIGH), "broken_internal_image"
    if resource == ImageResourceState.REDIRECTING.value:
        return Severity.MEDIUM, "redirecting_image_source"
    if resource == ImageResourceState.PLACEHOLDER.value:
        return Severity.MEDIUM, "placeholder_image"
    if resource in {
        ImageResourceState.EXTERNAL.value,
        ImageResourceState.OUT_OF_SCOPE.value,
    }:
        return Severity.INFO, "external_image_review"
    if alt in {AltTextState.MISSING, AltTextState.LINK_EMPTY}:
        return (
            Severity.HIGH if linked or reuse > 1 else Severity.MEDIUM
        ), "missing_alt_linked" if linked else "missing_alt"
    if alt in {AltTextState.GENERIC, AltTextState.FILENAME, AltTextState.URL}:
        return Severity.MEDIUM, alt.value
    if alt in {AltTextState.EMPTY, AltTextState.WHITESPACE}:
        return Severity.LOW, "empty_alt_review"
    if alt is AltTextState.OVERLONG:
        return Severity.LOW, "overlong_alt_review"
    if dimension is not DimensionState.PRESENT:
        return Severity.MEDIUM if reuse >= 5 else Severity.LOW, "missing_or_invalid_dimensions"
    if loading in {LoadingState.INVALID, LoadingState.MISSING, LoadingState.REVIEW}:
        return Severity.LOW, "loading_attribute_review"
    return Severity.INFO, "valid_image_occurrence"


def _finding_type(row: dict[str, Any]) -> str:
    reason = str(row["primary_reason"])
    if "alt" in reason:
        return "alt"
    if "dimension" in reason:
        return "dimension"
    if "loading" in reason:
        return "loading"
    return "resource"


def _safe_message(reason: str) -> str:
    return {
        "broken_internal_image": "An internal image resource is broken.",
        "redirecting_image_source": "An image source redirects and should be reviewed.",
        "placeholder_image": "A placeholder image should be replaced or confirmed.",
        "missing_alt": "An image is missing an alt attribute.",
        "missing_alt_linked": "A linked image is missing an accessible alternative.",
        "empty_alt_review": "An empty alternative requires decorative-context review.",
        "missing_or_invalid_dimensions": "Image width and height evidence requires review.",
        "loading_attribute_review": "Image loading behavior requires human review.",
    }.get(reason, "Image evidence requires human review.")


def _recommendation(row: dict[str, Any]) -> tuple[ImageAction, Confidence]:
    reason = str(row["primary_reason"])
    if reason == "broken_internal_image":
        return ImageAction.FIX_URL, Confidence.HIGH
    if reason == "redirecting_image_source":
        return ImageAction.UPDATE_DESTINATION, Confidence.HIGH
    if reason == "placeholder_image":
        return ImageAction.REPLACE_PLACEHOLDER, Confidence.HIGH
    if reason == "external_image_review":
        return ImageAction.REVIEW, Confidence.LOW
    if reason in {"missing_alt", "missing_alt_linked"}:
        return ImageAction.ADD_ALT, Confidence.HIGH if row["linked_image"] else Confidence.MEDIUM
    if reason in {
        AltTextState.GENERIC.value,
        AltTextState.FILENAME.value,
        AltTextState.URL.value,
        "overlong_alt_review",
    }:
        return (
            ImageAction.REPLACE_ALT,
            Confidence.HIGH if reason == AltTextState.FILENAME.value else Confidence.MEDIUM,
        )
    if reason == "empty_alt_review":
        return ImageAction.CONFIRM_DECORATIVE, Confidence.LOW
    if reason == "missing_or_invalid_dimensions":
        return ImageAction.ADD_DIMENSIONS, Confidence.MEDIUM
    if reason == "loading_attribute_review":
        return ImageAction.REVIEW_LOADING, Confidence.LOW
    return ImageAction.NO_ACTION, Confidence.LOW


_CSV_COLUMNS: dict[ImageExportFormat, tuple[str, ...]] = {
    ImageExportFormat.INVENTORY_CSV: (
        "audit_id",
        "resource_sequence",
        "image_identity",
        "representative_url",
        "scope_state",
        "fetch_state",
        "http_status",
        "status_class",
        "content_type",
        "redirect_state",
        "final_image_url",
        "response_byte_count",
        "resource_state",
        "unique_source_page_count",
        "total_occurrence_count",
        "unique_alt_count",
        "missing_alt_count",
        "empty_alt_count",
        "linked_occurrence_count",
        "broken_occurrence_count",
        "redirecting_occurrence_count",
        "width_consistent",
        "height_consistent",
        "loading_distribution_json",
        "earliest_discovery_sequence",
        "minimum_source_depth",
        "maximum_source_depth",
        "sitewide_state",
        "severity",
    ),
    ImageExportFormat.ALT_FINDINGS_CSV: (
        "audit_id",
        "finding_sequence",
        "source_page_url",
        "image_url",
        "raw_src",
        "primary_candidate",
        "element_type",
        "occurrence_sequence",
        "alt_raw",
        "alt_normalized",
        "alt_state",
        "linked_image",
        "decorative",
        "resource_state",
        "stable_code",
        "severity",
        "safe_message",
    ),
    ImageExportFormat.BROKEN_REDIRECTING_CSV: (
        "audit_id",
        "resource_sequence",
        "image_identity",
        "representative_url",
        "scope_state",
        "fetch_state",
        "http_status",
        "status_class",
        "content_type",
        "redirect_state",
        "final_image_url",
        "resource_state",
        "unique_source_page_count",
        "total_occurrence_count",
        "sitewide_state",
        "severity",
    ),
    ImageExportFormat.DUPLICATE_GROUPS_CSV: (
        "audit_id",
        "group_sequence",
        "group_type",
        "representative_alt",
        "image_count",
        "source_page_count",
        "occurrence_count",
        "severity",
        "sample_images_json",
        "sample_pages_json",
    ),
    ImageExportFormat.PAGE_SUMMARIES_CSV: (
        "audit_id",
        "page_sequence",
        "source_page_url",
        "image_occurrence_count",
        "unique_image_count",
        "missing_alt_count",
        "empty_alt_count",
        "broken_image_count",
        "redirecting_image_count",
        "missing_dimensions_count",
        "loading_review_count",
        "generic_alt_count",
        "filename_alt_count",
        "duplicate_alt_count",
        "external_image_count",
        "data_image_count",
        "severity",
    ),
    ImageExportFormat.RECOMMENDATIONS_CSV: (
        "audit_id",
        "recommendation_sequence",
        "source_page_url",
        "image_url",
        "image_identity",
        "action",
        "confidence",
        "severity",
        "reason_code",
        "human_review_state",
        "supporting_metrics_json",
    ),
}


def _csv_bytes(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _csv_safe(row.get(key)) for key in fields})
    return output.getvalue().encode("utf-8")


def _csv_safe(value: Any) -> str:
    rendered = (
        stable_json(value)
        if isinstance(value, (dict, list, tuple))
        else ""
        if value is None
        else str(value)
    )
    return "'" + rendered if rendered.startswith(("=", "+", "-", "@", "\t", "\r")) else rendered


def _export_bytes(
    audit: dict[str, Any],
    export_format: ImageExportFormat,
    datasets: dict[str, list[dict[str, Any]]],
    limit: int,
) -> tuple[bytes, int, bool]:
    mapping = {
        ImageExportFormat.INVENTORY_CSV: "resources",
        ImageExportFormat.ALT_FINDINGS_CSV: "findings",
        ImageExportFormat.BROKEN_REDIRECTING_CSV: "resources",
        ImageExportFormat.DUPLICATE_GROUPS_CSV: "groups",
        ImageExportFormat.PAGE_SUMMARIES_CSV: "pages",
        ImageExportFormat.RECOMMENDATIONS_CSV: "recommendations",
    }
    truncated = any(len(rows) > limit for rows in datasets.values())
    if export_format in mapping:
        rows = datasets[mapping[export_format]]
        if export_format is ImageExportFormat.ALT_FINDINGS_CSV:
            rows = [row for row in rows if row.get("finding_type") == "alt"]
        if export_format is ImageExportFormat.BROKEN_REDIRECTING_CSV:
            rows = [
                row
                for row in rows
                if row.get("resource_state") in {"broken_image", "redirecting_image"}
            ]
        selected = rows[:limit]
        return _csv_bytes(selected, _CSV_COLUMNS[export_format]), len(selected), len(rows) > limit
    if export_format is ImageExportFormat.JSON:
        value = {
            "schema_version": "seo-toolkit-image-export-v1",
            "audit": audit,
            "configuration": json.loads(str(audit["configuration_json"])),
            **{key: rows[:limit] for key, rows in datasets.items()},
            "truncated": truncated,
        }
        return (
            (
                json.dumps(value, sort_keys=True, indent=2, default=str, ensure_ascii=False) + "\n"
            ).encode(),
            sum(min(len(rows), limit) for rows in datasets.values()),
            truncated,
        )
    resources = datasets["resources"]
    occurrences = datasets["occurrences"]
    groups = datasets["groups"]
    pages = datasets["pages"]
    recommendations = datasets["recommendations"][:limit]

    def count(key: str, value: str) -> int:
        return sum(row.get(key) == value for row in occurrences)

    lines = [
        f"# Image audit {audit['audit_id']}",
        "",
        "## Audit identity",
        f"Audit: `{audit['audit_id']}`; state: `{audit['state']}`.",
        "",
        "## Source crawl evidence",
        f"Run: `{audit['run_id']}`",
        "",
        "## Configuration",
        f"`{audit['configuration_json']}`",
        "",
        "## Summary",
        f"Occurrences: {audit['image_occurrence_count']}; unique images: {audit['unique_image_count']}; broken: {audit['broken_image_count']}; missing alt: {audit['missing_alt_count']}.",
        "",
        "## Broken images",
        f"{sum(row.get('resource_state') == 'broken_image' for row in resources)} resources.",
        "",
        "## Redirecting images",
        f"{sum(row.get('resource_state') == 'redirecting_image' for row in resources)} resources.",
        "",
        "## Missing alt",
        f"{count('alt_state', AltTextState.MISSING.value)} occurrences.",
        "",
        "## Empty alt review",
        f"{count('alt_state', AltTextState.EMPTY.value) + count('alt_state', AltTextState.WHITESPACE.value)} occurrences.",
        "",
        "## Generic and filename-like alt",
        f"{count('alt_state', AltTextState.GENERIC.value) + count('alt_state', AltTextState.FILENAME.value)} occurrences.",
        "",
        "## Duplicate and inconsistent alt",
        f"{len(groups)} durable groups.",
        "",
        "## Missing dimensions",
        f"{sum(row.get('dimension_state') != DimensionState.PRESENT.value for row in occurrences)} occurrences require review.",
        "",
        "## Loading review",
        f"{sum(row.get('loading_state') in {LoadingState.MISSING.value, LoadingState.INVALID.value, LoadingState.REVIEW.value} for row in occurrences)} occurrences require review.",
        "",
        "## Sitewide impact",
        f"{sum(row.get('sitewide_state') == 'sitewide_candidate' for row in resources)} resources meet the configured sitewide threshold.",
        "",
        "## Page summaries",
        f"{len(pages)} pages summarized.",
        "",
        "## Recommendations",
    ]
    lines.extend(
        f"- {row['severity']}: {row['action']} — {row['reason_code']}" for row in recommendations
    )
    lines.extend(
        [
            "",
            "## Methodology",
            "Parser-owned bounded image evidence is grouped by normalized URL and analyzed conservatively.",
            "",
            "## Limitations",
            "No browser layout selection, CSS stylesheet parsing, binary duplicate detection, OCR, image recognition, or generated replacement alt text.",
            "",
            "## Version information",
            "seo-toolkit-image-export-v1",
            "",
        ]
    )
    return "\n".join(lines).encode(), len(recommendations), len(datasets["recommendations"]) > limit
