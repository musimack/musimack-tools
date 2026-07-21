"""Deterministic, bounded CSA artifact rendering without target-site writes."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from typing import Any
from xml.sax.saxutils import escape

from musimack_tools.domain.artifacts import ArtifactType
from musimack_tools.domain.site_audit_orchestration import (
    ARTIFACT_FILENAMES,
    MAXIMUM_ARTIFACT_ROWS,
    ArtifactPurpose,
)


@dataclass(frozen=True, slots=True)
class GeneratedSiteAuditArtifact:
    purpose: ArtifactPurpose
    artifact_type: ArtifactType
    schema_version: str
    content: bytes
    row_count: int | None
    truncated: bool

    @property
    def filename(self) -> str:
        return ARTIFACT_FILENAMES[self.purpose]


def generate_site_audit_artifacts(  # noqa: PLR0913
    *,
    audit: dict[str, Any],
    snapshot: dict[str, Any],
    summary: dict[str, Any],
    urls: tuple[dict[str, Any], ...],
    findings: tuple[dict[str, Any], ...],
    issue_groups: tuple[dict[str, Any], ...],
    rule_matches: tuple[dict[str, Any], ...],
    evidence: dict[str, dict[str, Any]],
) -> tuple[GeneratedSiteAuditArtifact, ...]:
    selected_urls = urls[:MAXIMUM_ARTIFACT_ROWS]
    truncated = len(urls) > len(selected_urls)
    return (
        _artifact(
            ArtifactPurpose.EXECUTIVE,
            ArtifactType.RUN_SUMMARY_MARKDOWN,
            "site-audit-executive-v1",
            _executive(audit, snapshot, summary, issue_groups),
            rows=None,
            truncated=False,
        ),
        _artifact(
            ArtifactPurpose.PAGE_INVENTORY,
            ArtifactType.CSV_EXPORT,
            "site-audit-pages-v1",
            _pages_csv(selected_urls, findings, evidence),
            rows=len(selected_urls),
            truncated=truncated,
        ),
        _artifact(
            ArtifactPurpose.EVIDENCE,
            ArtifactType.RUN_SUMMARY_JSON,
            "site-audit-evidence-v1",
            _evidence_json(
                audit,
                snapshot,
                summary,
                selected_urls,
                evidence,
                truncated=truncated,
            ),
            rows=len(selected_urls),
            truncated=truncated,
        ),
        _artifact(
            ArtifactPurpose.ISSUES,
            ArtifactType.CSV_EXPORT,
            "site-audit-issues-v1",
            _issues_csv(issue_groups),
            rows=len(issue_groups),
            truncated=False,
        ),
        _artifact(
            ArtifactPurpose.SITEMAP_COMPARISON,
            ArtifactType.CSV_EXPORT,
            "site-audit-sitemap-comparison-v1",
            _simple_url_csv(
                selected_urls,
                ("normalized_url", "existing_sitemap_state", "recommended_sitemap_state"),
            ),
            rows=len(selected_urls),
            truncated=truncated,
        ),
        _artifact(
            ArtifactPurpose.EXCLUSIONS,
            ArtifactType.CSV_EXPORT,
            "site-audit-exclusions-v1",
            _exclusions_csv(selected_urls),
            rows=sum(item.get("discovery_decision") != "enqueue" for item in selected_urls),
            truncated=truncated,
        ),
        _artifact(
            ArtifactPurpose.RULES,
            ArtifactType.CSV_EXPORT,
            "site-audit-applied-rules-v1",
            _rules_csv(rule_matches),
            rows=len(rule_matches),
            truncated=len(rule_matches) > MAXIMUM_ARTIFACT_ROWS,
        ),
        _artifact(
            ArtifactPurpose.SITEMAP_XML,
            ArtifactType.SITEMAP_XML,
            "site-audit-sitemap-v1",
            _sitemap_xml(selected_urls),
            rows=sum(item.get("recommended_sitemap_state") == "include" for item in selected_urls),
            truncated=truncated,
        ),
        _artifact(
            ArtifactPurpose.ACTION_PLAN,
            ArtifactType.CSV_EXPORT,
            "site-audit-action-plan-v1",
            _action_plan_csv(issue_groups),
            rows=len(issue_groups),
            truncated=False,
        ),
        _artifact(
            ArtifactPurpose.CONFIGURATION,
            ArtifactType.RUN_SUMMARY_JSON,
            "site-audit-configuration-v1",
            _configuration_json(snapshot, summary),
            rows=None,
            truncated=False,
        ),
    )


def _artifact(  # noqa: PLR0913
    purpose: ArtifactPurpose,
    artifact_type: ArtifactType,
    schema: str,
    text: str,
    *,
    rows: int | None,
    truncated: bool,
) -> GeneratedSiteAuditArtifact:
    return GeneratedSiteAuditArtifact(
        purpose, artifact_type, schema, text.encode("utf-8"), rows, truncated
    )


def _executive(
    audit: dict[str, Any],
    snapshot: dict[str, Any],
    summary: dict[str, Any],
    groups: tuple[dict[str, Any], ...],
) -> str:
    partial = bool(audit.get("partial")) or summary.get("partial_urls", 0) > 0
    lines = [
        "# Combined Site Audit",
        "",
        f"- Audit: {audit['audit_name']}",
        f"- Seed: {audit['normalized_seed_url']}",
        f"- Lifecycle: {audit['lifecycle']}",
        f"- Population completeness: {audit['population_completeness']}",
        f"- Module completeness: {audit['module_completeness']}",
        f"- Snapshot: {snapshot['sha256']}",
        f"- Partial data: {'yes' if partial else 'no'}",
        "",
        "## Explicit denominators",
        "",
        f"- Discovered: {summary.get('urls_discovered', 0)}",
        f"- Fetched: {summary.get('urls_fetched', 0)}",
        f"- Parsed HTML: {summary.get('html_urls', 0)}",
        "- Executive metadata denominator: indexable, canonical, "
        "metadata-scoring-eligible HTML pages",
        f"- Executive denominator count: {summary.get('metadata_scoring_eligible_urls', 0)}",
        f"- URL ceiling effect: {_url_limit_explanation(summary)}",
        "",
        "## Top issue groups",
        "",
    ]
    lines.extend(
        f"- {item['title']} ({item['severity']}): {item['affected_url_count']} URL(s)"
        for item in groups[:10]
    )
    if not groups:
        lines.append("- No retained issue groups.")
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            "Specialist details remain owned by their linked audit. Unavailable and partial "
            "modules are not reported as zero findings.",
            "No artifact publishes XML or writes to the audited website.",
            "",
        ]
    )
    return "\n".join(lines)


def _pages_csv(
    urls: tuple[dict[str, Any], ...],
    findings: tuple[dict[str, Any], ...],
    evidence: dict[str, dict[str, Any]],
) -> str:
    counts: dict[str, int] = {}
    for finding in findings:
        if finding.get("url_id"):
            counts[str(finding["url_id"])] = counts.get(str(finding["url_id"]), 0) + 1
    columns = (
        "original_url",
        "requested_url",
        "normalized_url",
        "final_url",
        "fetch_state",
        "http_status",
        "content_type",
        "indexability_state",
        "canonical_state",
        "existing_sitemap_state",
        "recommended_sitemap_state",
        "metadata_scoring_decision",
        "title",
        "title_length",
        "meta_description",
        "description_length",
        "meta_robots",
        "x_robots_tag",
        "issue_count",
        "highest_severity",
        "business_importance",
        "crawl_depth",
        "rule_reason",
        "partial",
    )
    rows = []
    for item in urls:
        source = evidence.get(str(item.get("evidence_id")), {})
        rows.append(
            {
                **item,
                "title": source.get("title_value"),
                "title_length": source.get("title_length"),
                "meta_description": source.get("description_value"),
                "description_length": source.get("description_length"),
                "meta_robots": source.get("meta_robots_json"),
                "x_robots_tag": source.get("x_robots_json"),
                "issue_count": counts.get(str(item["url_id"]), 0),
                "rule_reason": item.get("discovery_decision"),
            }
        )
    return _csv(columns, rows)


def _evidence_json(  # noqa: PLR0913 - final retained artifact inputs are explicit.
    audit: dict[str, Any],
    snapshot: dict[str, Any],
    summary: dict[str, Any],
    urls: tuple[dict[str, Any], ...],
    evidence: dict[str, dict[str, Any]],
    *,
    truncated: bool,
) -> str:
    safe = []
    for item in urls:
        page = evidence.get(str(item.get("evidence_id")), {})
        safe.append(
            {
                "sequence": item["sequence"],
                "url": item["normalized_url"],
                "final_url": item.get("final_url"),
                "http_status": item.get("http_status"),
                "content_type": item.get("content_type"),
                "fetch_state": item.get("fetch_state"),
                "indexability_state": item.get("indexability_state"),
                "canonical_state": item.get("canonical_state"),
                "robots_state": item.get("robots_state"),
                "title_presence": page.get("title_presence"),
                "title": page.get("title_value"),
                "title_length": page.get("title_length"),
                "description_presence": page.get("description_presence"),
                "meta_description": page.get("description_value"),
                "description_length": page.get("description_length"),
                "canonical": page.get("canonical_url"),
                "meta_robots": page.get("meta_robots_json"),
                "x_robots_tag": page.get("x_robots_json"),
                "parse_warning_count": page.get("parse_warning_count"),
                "evidence_id": item.get("evidence_id"),
            }
        )
    return json.dumps(
        {
            "schema_version": "site-audit-evidence-v1",
            "audit_id": audit["audit_id"],
            "snapshot_sha256": snapshot["sha256"],
            "partial": bool(audit.get("partial")),
            "truncated": truncated,
            "operational_accounting": _operational_accounting(summary),
            "urls": safe,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def _issues_csv(groups: tuple[dict[str, Any], ...]) -> str:
    columns = (
        "code",
        "category",
        "title",
        "severity",
        "priority_band",
        "priority_explanation",
        "affected_url_count",
        "highest_business_importance",
        "sitemap_impact",
        "metadata_impact",
        "indexability_impact",
        "internal_link_impact",
        "confidence",
        "determinacy",
        "recommended_action",
        "sample_urls_json",
    )
    return _csv(columns, list(groups[:MAXIMUM_ARTIFACT_ROWS]))


def _simple_url_csv(urls: tuple[dict[str, Any], ...], columns: tuple[str, ...]) -> str:
    return _csv(columns, list(urls))


def _exclusions_csv(urls: tuple[dict[str, Any], ...]) -> str:
    selected = [
        item
        for item in urls
        if item.get("discovery_decision") != "enqueue"
        or item.get("metadata_scoring_decision") == "exclude_from_metadata_scoring"
        or item.get("sitemap_policy_decision") == "exclude"
    ]
    columns = (
        "normalized_url",
        "discovery_decision",
        "metadata_scoring_decision",
        "sitemap_policy_decision",
        "fetch_state",
        "created_at",
    )
    return _csv(columns, selected)


def _rules_csv(matches: tuple[dict[str, Any], ...]) -> str:
    columns = (
        "snapshot_rule_id",
        "decision_layer",
        "primary_rule",
        "contributed",
        "disabled",
        "overridden",
        "priority",
        "specificity",
        "conflict_code",
        "reason",
        "matched_normalized_url",
    )
    return _csv(columns, list(matches[:MAXIMUM_ARTIFACT_ROWS]))


def _sitemap_xml(urls: tuple[dict[str, Any], ...]) -> str:
    included = sorted(
        str(item["normalized_url"])
        for item in urls
        if item.get("recommended_sitemap_state") == "include"
    )
    body = "".join(f"  <url><loc>{escape(url)}</loc></url>\n" for url in included)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + body
        + "</urlset>\n"
    )


def _action_plan_csv(groups: tuple[dict[str, Any], ...]) -> str:
    columns = (
        "priority_band",
        "code",
        "title",
        "recommended_action",
        "affected_url_count",
        "priority_explanation",
    )
    return _csv(columns, list(groups[:MAXIMUM_ARTIFACT_ROWS]))


def _configuration_json(snapshot: dict[str, Any], summary: dict[str, Any]) -> str:
    module_counts = summary.get("module_counts_json")
    decoded_counts: dict[str, Any] = {}
    if isinstance(module_counts, str):
        try:
            candidate = json.loads(module_counts)
        except json.JSONDecodeError:
            candidate = {}
        if isinstance(candidate, dict):
            decoded_counts = candidate
    return json.dumps(
        {
            "schema_version": "site-audit-configuration-v1",
            "snapshot_id": snapshot["snapshot_id"],
            "sha256": snapshot["sha256"],
            "configuration": snapshot["configuration"],
            "rules": snapshot.get("rules", ()),
            "disabled_inherited_rules": snapshot.get("disabled_inherited_rules", ()),
            "operational_accounting": decoded_counts.get("operational_accounting"),
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def _operational_accounting(summary: dict[str, Any]) -> object:
    module_counts = summary.get("module_counts_json")
    if not isinstance(module_counts, str):
        return None
    try:
        decoded = json.loads(module_counts)
    except json.JSONDecodeError:
        return None
    return decoded.get("operational_accounting") if isinstance(decoded, dict) else None


def _url_limit_explanation(summary: dict[str, Any]) -> str:
    operational = _operational_accounting(summary)
    if not isinstance(operational, dict):
        return "No retained URL-ceiling accounting is available."
    admission = operational.get("url_admission")
    if not isinstance(admission, dict):
        return "No retained URL-ceiling accounting is available."
    over_limit = int(admission.get("over_limit", 0))
    admitted = int(admission.get("admitted", 0))
    if over_limit:
        return (
            f"{admitted} URLs were admitted; {over_limit} additional unique discoveries "
            "were not admitted, while queued work continued."
        )
    return f"{admitted} URLs were admitted; no over-limit discoveries were retained."


def _csv(columns: tuple[str, ...], rows: list[dict[str, Any]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column) for column in columns})
    return output.getvalue()
