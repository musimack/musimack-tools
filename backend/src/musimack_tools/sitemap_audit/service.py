"""Bounded safe-fetch sitemap discovery, recursive audit, comparison, and exports."""

# ruff: noqa: ANN401, C901, FBT001, PLR0912, PLR0915

from __future__ import annotations

import asyncio
import csv
import io
import json
from contextlib import suppress
from typing import TYPE_CHECKING, Any, Protocol

from musimack_tools.crawl.normalization import normalize_url
from musimack_tools.crawl.robots import RobotsTxtParser
from musimack_tools.crawl.scope import create_scope_policy, evaluate_scope
from musimack_tools.domain.artifacts import ArtifactType
from musimack_tools.domain.fetching import FetchOutcome, FetchRequest, FetchResult
from musimack_tools.domain.sitemap_audit import (
    COMMON_SITEMAP_PATHS,
    SITEMAP_AUDIT_EXPORT_VERSION,
    AuditLifecycle,
    DiscoveryOptions,
    DiscoverySource,
    ExportFormat,
    FetchState,
    ParsedSitemap,
    ParseState,
    SitemapAuditConfiguration,
    SitemapCandidate,
    SitemapFinding,
    SitemapRootType,
    ValidationCode,
    ValidationSeverity,
    audit_identity,
    compare_evidence,
    parse_sitemap,
)
from musimack_tools.domain.urls import CrawlScopePolicy, UrlNormalizationError

if TYPE_CHECKING:
    from musimack_tools.artifacts.service import ArtifactService
    from musimack_tools.persistence.sitemap_audit_repository import (
        SQLAlchemySitemapAuditRepository,
    )

_SUCCESS_MINIMUM = 200
_SUCCESS_MAXIMUM = 300


class SafeFetcher(Protocol):
    async def fetch(self, request: FetchRequest, scope: CrawlScopePolicy) -> FetchResult: ...


class SitemapAuditService:
    """Execute audits only from authoritative terminal-run evidence."""

    def __init__(
        self,
        configuration: SitemapAuditConfiguration,
        repository: SQLAlchemySitemapAuditRepository,
        fetcher: SafeFetcher,
        artifacts: ArtifactService | None = None,
    ) -> None:
        self.configuration = configuration
        self._repository = repository
        self._fetcher = fetcher
        self._artifacts = artifacts
        self._repository.reconcile_interrupted()

    async def discover(
        self, run_id: str, options: DiscoveryOptions
    ) -> tuple[tuple[SitemapCandidate, ...], tuple[SitemapFinding, ...]]:
        context = self._context(run_id)
        _, seed, _, _ = context
        normalized_seed = normalize_url(seed)
        scope = self._scope(run_id, seed)
        candidates: list[tuple[str, DiscoverySource, str]] = []
        findings: list[SitemapFinding] = []
        if options.explicit_url:
            try:
                explicit = normalize_url(options.explicit_url)
            except UrlNormalizationError:
                raise ValueError("sitemap_audit_invalid_filter") from None
            if not evaluate_scope(scope, explicit).allowed:
                raise ValueError("sitemap_audit_invalid_filter")
            candidates.append(
                (options.explicit_url, DiscoverySource.EXPLICIT, options.explicit_url)
            )
        if options.discover_robots:
            robots_url = normalize_url(f"{normalized_seed.origin}/robots.txt")
            result = await self._fetcher.fetch(
                FetchRequest(robots_url, correlation_id=f"sitemap-discovery-{run_id}"), scope
            )
            if result.outcome is FetchOutcome.SUCCESS and result.body is not None:
                parsed = RobotsTxtParser().parse(result.body)
                for directive in parsed.sitemap_directives:
                    if directive.valid and directive.normalized_url:
                        candidates.append(
                            (
                                directive.normalized_url,
                                DiscoverySource.ROBOTS,
                                directive.raw_value,
                            )
                        )
                    else:
                        findings.append(
                            SitemapFinding(
                                ValidationCode.ROBOTS_SITEMAP_INVALID,
                                ValidationSeverity.WARNING,
                                "A robots.txt Sitemap directive was invalid",
                                len(findings),
                            )
                        )
        if options.discover_common_locations:
            candidates.extend(
                (f"{normalized_seed.origin}{path}", DiscoverySource.COMMON_LOCATION, path)
                for path in COMMON_SITEMAP_PATHS
            )
        return _deduplicate(candidates, scope, findings), tuple(findings)

    async def create_and_run(self, run_id: str, options: DiscoveryOptions) -> dict[str, Any]:
        if not self.configuration.enabled:
            raise ValueError("sitemap_audit_disabled")
        job_id, seed, _terminal, _page_count = self._context(run_id)
        if options.explicit_url:
            try:
                explicit = normalize_url(options.explicit_url)
            except UrlNormalizationError:
                raise ValueError("sitemap_audit_invalid_filter") from None
            if not evaluate_scope(self._scope(run_id, seed), explicit).allowed:
                raise ValueError("sitemap_audit_invalid_filter")
        audit_id = audit_identity(run_id, options, self.configuration)
        existing = self._repository.get(audit_id)
        if existing and existing["state"] not in {
            AuditLifecycle.ACCEPTED.value,
            AuditLifecycle.DISCOVERING.value,
            AuditLifecycle.FETCHING.value,
            AuditLifecycle.PARSING.value,
            AuditLifecycle.COMPARING.value,
        }:
            return existing
        self._repository.create(audit_id, job_id, run_id, seed, options, self.configuration)
        if not self._repository.claim_execution(audit_id):
            raise ValueError("sitemap_audit_already_exists")
        candidates, discovery_findings = await self.discover(run_id, options)
        for finding in discovery_findings:
            self._repository.persist_finding(audit_id, finding)
        scope = self._scope(run_id, seed)
        queue: list[tuple[SitemapCandidate, str | None, int]] = [
            (candidate, None, 0) for candidate in candidates
        ]
        fetched: set[str] = set()
        final_identities: set[str] = set()
        total_urls = 0
        partial = False
        valid_root = False
        sequence = len(queue)
        self._repository.transition(audit_id, AuditLifecycle.FETCHING)
        while queue:
            candidate, parent_document_id, depth = queue.pop(0)
            if candidate.normalized_url in fetched:
                continue
            if len(fetched) >= self.configuration.maximum_documents:
                self._repository.persist_finding(
                    audit_id,
                    _finding(
                        ValidationCode.SITEMAP_DOCUMENT_LIMIT_EXCEEDED,
                        "The sitemap document limit was reached",
                    ),
                    parent_document_id,
                )
                partial = True
                break
            if depth > self.configuration.maximum_depth:
                self._repository.persist_finding(
                    audit_id,
                    _finding(
                        ValidationCode.MAXIMUM_DEPTH_EXCEEDED,
                        "The sitemap-index depth limit was reached",
                    ),
                    parent_document_id,
                )
                partial = True
                continue
            fetched.add(candidate.normalized_url)
            target = normalize_url(candidate.normalized_url)
            result = await self._fetcher.fetch(FetchRequest(target, correlation_id=audit_id), scope)
            payload = result.body or b""
            final_url = None
            with suppress(UrlNormalizationError):
                final_url = normalize_url(result.final_url).normalized
            if final_url and final_url in final_identities:
                parsed = _empty_parsed(
                    _finding(
                        ValidationCode.REDIRECT_ALIAS_DUPLICATE,
                        "A redirected sitemap alias was already processed",
                    )
                )
                self._repository.persist_document(
                    audit_id,
                    candidate,
                    parent_document_id=parent_document_id,
                    depth=depth,
                    final_url=None,
                    fetch_state=FetchState.SKIPPED.value,
                    http_status=result.status_code,
                    content_type=result.content_type,
                    payload=b"",
                    redirects=result.redirect_chain,
                    parsed=parsed,
                )
                partial = True
                continue
            if final_url:
                final_identities.add(final_url)
            success = (
                result.outcome is FetchOutcome.SUCCESS
                and result.status_code is not None
                and _SUCCESS_MINIMUM <= result.status_code < _SUCCESS_MAXIMUM
                and result.body is not None
            )
            if success:
                self._repository.transition(audit_id, AuditLifecycle.PARSING)
                parsed = parse_sitemap(
                    payload,
                    content_type=result.content_type,
                    document_url=final_url or candidate.normalized_url,
                    scope=scope,
                    configuration=self.configuration,
                )
                fetch_state = FetchState.FETCHED.value
            else:
                code = (
                    ValidationCode.CHILD_FETCH_FAILED
                    if parent_document_id
                    else ValidationCode.FETCH_FAILED
                )
                parsed = _empty_parsed(_finding(code, "The sitemap document could not be fetched"))
                fetch_state = FetchState.FAILED.value
                partial = partial or parent_document_id is not None
            doc_id = self._repository.persist_document(
                audit_id,
                candidate,
                parent_document_id=parent_document_id,
                depth=depth,
                final_url=final_url,
                fetch_state=fetch_state,
                http_status=result.status_code,
                content_type=result.content_type,
                payload=payload,
                redirects=result.redirect_chain,
                parsed=parsed,
            )
            if parent_document_id is None and parsed.parse_state in {
                ParseState.PARSED,
                ParseState.PARSED_WITH_WARNINGS,
            }:
                valid_root = True
            total_urls += sum(1 for entry in parsed.entries if entry.valid and not entry.duplicate)
            if total_urls > self.configuration.maximum_total_urls:
                self._repository.persist_finding(
                    audit_id,
                    _finding(
                        ValidationCode.TOTAL_URL_LIMIT_EXCEEDED,
                        "The total unique sitemap URL limit was reached",
                    ),
                    doc_id,
                )
                partial = True
                break
            for child in parsed.children:
                if not child.valid or child.duplicate or child.normalized_url is None:
                    continue
                if child.normalized_url in fetched:
                    self._repository.persist_finding(
                        audit_id,
                        _finding(
                            ValidationCode.SITEMAP_INDEX_LOOP,
                            "A repeated sitemap-index reference was not fetched again",
                        ),
                        doc_id,
                    )
                    continue
                queue.append(
                    (
                        SitemapCandidate(
                            child.normalized_url,
                            DiscoverySource.CHILD_INDEX,
                            sequence,
                            (DiscoverySource.CHILD_INDEX,),
                            child.raw_location or child.normalized_url,
                        ),
                        doc_id,
                        depth + 1,
                    )
                )
                sequence += 1
            self._repository.transition(audit_id, AuditLifecycle.FETCHING)
        if not valid_root:
            self._repository.transition(
                audit_id, AuditLifecycle.FAILED, "sitemap_audit_no_valid_root"
            )
            return self.get(audit_id)
        self._repository.transition(audit_id, AuditLifecycle.COMPARING)
        records = compare_evidence(
            self._repository.sitemap_entries(audit_id), self._repository.evidence(run_id)
        )
        self._repository.persist_comparisons(audit_id, records)
        return self._repository.finish(audit_id, partial=partial)

    def create_audit(self, run_id: str, options: DiscoveryOptions) -> dict[str, Any]:
        """Persist an accepted audit so a separate explicit request can execute it."""
        if not self.configuration.enabled:
            raise ValueError("sitemap_audit_disabled")
        job_id, seed, _terminal, _page_count = self._context(run_id)
        if options.explicit_url:
            try:
                explicit = normalize_url(options.explicit_url)
            except UrlNormalizationError:
                raise ValueError("sitemap_audit_invalid_filter") from None
            if not evaluate_scope(self._scope(run_id, seed), explicit).allowed:
                raise ValueError("sitemap_audit_invalid_filter")
        audit_id = audit_identity(run_id, options, self.configuration)
        return self._repository.create(audit_id, job_id, run_id, seed, options, self.configuration)

    async def execute_audit(self, audit_id: str) -> dict[str, Any]:
        """Execute one accepted audit synchronously while durable reads remain available."""
        audit = self.get(audit_id)
        if audit["state"] != AuditLifecycle.ACCEPTED.value:
            raise ValueError("sitemap_audit_already_exists")
        raw = json.loads(str(audit["discovery_settings_json"]))
        options = DiscoveryOptions(
            explicit_url=raw.get("explicit_url"),
            discover_robots=bool(raw.get("discover_robots", True)),
            discover_common_locations=bool(raw.get("discover_common_locations", True)),
        )
        try:
            return await self.create_and_run(str(audit["run_id"]), options)
        except asyncio.CancelledError:
            self._repository.fail_if_running(audit_id, "sitemap_audit_execution_interrupted")
            raise
        except Exception:
            self._repository.fail_if_running(audit_id, "sitemap_audit_execution_failed")
            raise

    def get(self, audit_id: str) -> dict[str, Any]:
        value = self._repository.get(audit_id)
        if value is None:
            raise ValueError("sitemap_audit_not_found")
        return value

    def list_audits(
        self, offset: int = 0, page_size: int | None = None
    ) -> tuple[dict[str, Any], ...]:
        return self._repository.list_audits(offset, self._size(page_size))

    def list_documents(
        self,
        audit_id: str,
        offset: int = 0,
        page_size: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        self.get(audit_id)
        return self._repository.list_documents(audit_id, offset, self._size(page_size), filters)

    def list_entries(
        self,
        audit_id: str,
        offset: int = 0,
        page_size: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        del filters
        self.get(audit_id)
        return self._repository.list_entries(audit_id, offset, self._size(page_size))

    def list_findings(
        self,
        audit_id: str,
        offset: int = 0,
        page_size: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        self.get(audit_id)
        return self._repository.list_findings(audit_id, offset, self._size(page_size), filters)

    def list_comparisons(
        self,
        audit_id: str,
        offset: int = 0,
        page_size: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        self.get(audit_id)
        return self._repository.list_comparisons(audit_id, offset, self._size(page_size), filters)

    def summary(self, audit_id: str) -> dict[str, Any]:
        audit = self.get(audit_id)
        return {
            key: audit[key]
            for key in (
                "document_count",
                "unique_url_count",
                "warning_count",
                "comparison_count",
                "add_count",
                "remove_count",
                "review_count",
                "unchanged_count",
            )
        }

    def create_export(self, audit_id: str, export_format: ExportFormat) -> dict[str, Any]:
        audit = self.get(audit_id)
        enabled = {
            ExportFormat.CSV: self.configuration.csv_enabled,
            ExportFormat.JSON: self.configuration.json_enabled,
            ExportFormat.MARKDOWN: self.configuration.markdown_enabled,
        }[export_format]
        if not enabled:
            raise ValueError("sitemap_audit_export_unsupported")
        if self._artifacts is None or not self._artifacts.configuration.enabled:
            raise ValueError("sitemap_audit_export_failed")
        records = list(
            self._repository.list_comparisons(
                audit_id, 0, self.configuration.maximum_export_rows + 1
            )
        )
        truncated = len(records) > self.configuration.maximum_export_rows
        records = records[: self.configuration.maximum_export_rows]
        content = _export_bytes(audit, export_format, records, truncated)
        kind = {
            ExportFormat.CSV: ArtifactType.CSV_EXPORT,
            ExportFormat.JSON: ArtifactType.RUN_SUMMARY_JSON,
            ExportFormat.MARKDOWN: ArtifactType.RUN_SUMMARY_MARKDOWN,
        }[export_format]
        extension = "md" if export_format is ExportFormat.MARKDOWN else export_format.value
        artifact = self._artifacts.store_bytes(
            job_id=audit["job_id"],
            run_id=audit["run_id"],
            artifact_type=kind,
            filename=f"sitemap-audit-{audit_id}.{extension}",
            content=content,
        )
        return self._repository.upsert_export(
            audit_id, export_format.value, artifact.artifact_id, len(records), truncated
        )

    def list_exports(self, audit_id: str) -> tuple[dict[str, Any], ...]:
        self.get(audit_id)
        return self._repository.list_exports(audit_id)

    def diagnostics(self) -> dict[str, Any]:
        return self._repository.diagnostics()

    def _context(self, run_id: str) -> tuple[str, str, bool, int]:
        context = self._repository.run_context(run_id)
        if context is None:
            raise ValueError("sitemap_audit_run_not_found")
        if not context[2]:
            raise ValueError("sitemap_audit_run_not_terminal")
        if context[3] == 0:
            raise ValueError("sitemap_audit_page_evidence_unavailable")
        return context

    def _scope(self, run_id: str, seed: str) -> CrawlScopePolicy:
        snapshot = self._repository.run_scope_snapshot(run_id)
        if snapshot is None:
            raise ValueError("sitemap_audit_scope_unavailable")
        mode, approved_hosts = snapshot
        return create_scope_policy(normalize_url(seed), mode=mode, approved_hosts=approved_hosts)

    def _size(self, value: int | None) -> int:
        size = value or self.configuration.default_page_size
        if not 1 <= size <= self.configuration.maximum_page_size:
            raise ValueError("sitemap_audit_invalid_page_size")
        return size


def _deduplicate(
    values: list[tuple[str, DiscoverySource, str]],
    scope: CrawlScopePolicy,
    findings: list[SitemapFinding],
) -> tuple[SitemapCandidate, ...]:
    ordered: dict[str, SitemapCandidate] = {}
    for raw, source, provenance in values:
        try:
            normalized = normalize_url(raw)
        except UrlNormalizationError:
            findings.append(
                SitemapFinding(
                    ValidationCode.INVALID_LOCATION,
                    ValidationSeverity.WARNING,
                    "A sitemap candidate URL was invalid",
                    len(findings),
                )
            )
            continue
        if not evaluate_scope(scope, normalized).allowed:
            findings.append(
                SitemapFinding(
                    ValidationCode.OUT_OF_SCOPE_LOCATION,
                    ValidationSeverity.WARNING,
                    "A sitemap candidate was outside the selected crawl scope",
                    len(findings),
                    normalized_url=normalized.normalized,
                )
            )
            continue
        current = ordered.get(normalized.normalized)
        if current is None:
            ordered[normalized.normalized] = SitemapCandidate(
                normalized.normalized,
                source,
                len(ordered),
                (source,),
                provenance,
            )
        elif source not in current.provenance:
            ordered[normalized.normalized] = SitemapCandidate(
                current.normalized_url,
                current.discovery_source,
                current.discovery_sequence,
                (*current.provenance, source),
                current.raw_url,
            )
    return tuple(ordered.values())


def _finding(code: ValidationCode, message: str) -> SitemapFinding:
    return SitemapFinding(code, ValidationSeverity.WARNING, message, 0)


def _empty_parsed(finding: SitemapFinding) -> ParsedSitemap:
    return ParsedSitemap(
        SitemapRootType.UNSUPPORTED,
        ParseState.UNSUPPORTED,
        None,
        (),
        (),
        (finding,),
    )


def _export_bytes(
    audit: dict[str, Any],
    export_format: ExportFormat,
    records: list[dict[str, Any]],
    truncated: bool,
) -> bytes:
    if export_format is ExportFormat.JSON:
        return json.dumps(
            {
                "version": SITEMAP_AUDIT_EXPORT_VERSION,
                "audit_id": audit["audit_id"],
                "truncated": truncated,
                "comparisons": records,
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    if export_format is ExportFormat.MARKDOWN:
        lines = [
            f"# Sitemap audit {audit['audit_id']}",
            "",
            f"Export version: `{SITEMAP_AUDIT_EXPORT_VERSION}`",
            f"Truncated: `{str(truncated).lower()}`",
            "",
            "| Action | URL | State | Reason |",
            "| --- | --- | --- | --- |",
        ]
        lines.extend(
            f"| {row['action']} | {row['url']} | {row['comparison_state']} | {row['reason_code']} |"
            for row in records
        )
        return ("\n".join(lines) + "\n").encode()
    output = io.StringIO(newline="")
    fields = [
        "action",
        "url",
        "comparison_state",
        "reason_code",
        "recommendation_state",
        "http_status",
        "content_type",
    ]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in records:
        writer.writerow({key: _csv_safe(row.get(key)) for key in fields})
    return output.getvalue().encode("utf-8-sig")


def _csv_safe(value: Any) -> Any:
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value
