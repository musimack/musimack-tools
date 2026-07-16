"""Deterministic portable summaries and safe local summary publication."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import TYPE_CHECKING, cast

from musimack_tools.domain.run import CrawlRunResult, RunStageState
from musimack_tools.domain.run_summary import (
    CRAWL_RUN_SUMMARY_SCHEMA_VERSION,
    RUN_SUMMARY_JSON_NAME,
    RUN_SUMMARY_MARKDOWN_NAME,
    RunSummaryArtifact,
    RunSummaryConfiguration,
    RunSummaryFormat,
    RunSummaryWriteFailure,
    RunSummaryWriteResult,
    RunSummaryWriteState,
    RunSummaryWrittenFile,
)
from musimack_tools.domain.sitemap_publication import (
    PlannedPublicationFile,
    PublicationDocumentType,
)
from musimack_tools.sitemap.publication import (
    AtomicWriteError,
    LocalAtomicWriter,
    is_unsafe_link_path,
)

if TYPE_CHECKING:
    from pathlib import Path


def serialize_summaries(result: CrawlRunResult) -> tuple[RunSummaryArtifact, ...]:
    """Create deterministic JSON and Markdown bytes from bounded run evidence."""
    payload = _payload(result)
    json_content = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()
    markdown_content = _markdown(payload).encode()
    return (
        _artifact(RUN_SUMMARY_JSON_NAME, RunSummaryFormat.JSON, json_content),
        _artifact(RUN_SUMMARY_MARKDOWN_NAME, RunSummaryFormat.MARKDOWN, markdown_content),
    )


def _artifact(
    logical_name: str,
    format_: RunSummaryFormat,
    content: bytes,
) -> RunSummaryArtifact:
    return RunSummaryArtifact(
        logical_name=logical_name,
        format=format_,
        content=content,
        byte_count=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )


def _payload(result: CrawlRunResult) -> dict[str, object]:
    crawl = result.crawl_result
    projection = result.recommendation_projection
    bundle = result.xml_bundle
    publication = result.publication_result
    return {
        "caller_label": result.caller_label,
        "configuration": asdict(result.configuration),
        "counts": {
            "crawl": (
                {}
                if crawl is None
                else {
                    "bytes_fetched": crawl.total_accepted_bytes,
                    "urls_discovered": crawl.counters.unique_urls_discovered,
                    "urls_fetched": crawl.counters.urls_fetched,
                    "urls_parsed": crawl.counters.html_pages_parsed,
                }
            ),
            "recommendations": (
                {}
                if projection is None
                else {
                    "exclude": projection.excluded_url_count,
                    "include": projection.included_url_count,
                    "indeterminate": projection.indeterminate_count,
                    "review": projection.review_count,
                }
            ),
            "xml": (
                {}
                if bundle is None
                else {
                    "documents": bundle.total_documents,
                    "entries": bundle.total_entries,
                    "rejections": len(bundle.rejections),
                }
            ),
        },
        "failures": [
            {
                "code": item.code.value,
                "explanation": item.explanation,
                "stage": item.stage.value if item.stage is not None else None,
            }
            for item in result.failures
        ],
        "lifecycle": result.lifecycle.value,
        "publication": (
            None
            if publication is None
            else {
                "failure_count": len(publication.failures),
                "file_count": publication.published_file_count,
                "state": publication.state.value,
            }
        ),
        "run_id": result.run_id,
        "schema_version": CRAWL_RUN_SUMMARY_SCHEMA_VERSION,
        "seed_url": result.configuration.normalized_seed_url,
        "stages": [
            {
                "explanation": item.explanation,
                "stage": item.stage.value,
                "state": item.state.value,
            }
            for item in result.stages
        ],
        "versions": {
            "manifest": result.configuration.manifest_version,
            "orchestration": result.orchestration_version,
            "publication": result.configuration.publication_version,
            "recommendation": result.configuration.recommendation_rule_set_version,
            "xml": result.configuration.xml_format_version,
        },
        "warnings": [
            {
                "code": item.code,
                "message": item.message,
                "stage": item.stage.value,
                "url": item.url,
            }
            for item in result.warnings
        ],
    }


def _markdown(payload: dict[str, object]) -> str:
    stages = cast("list[dict[str, object]]", payload["stages"])
    counts = cast("dict[str, dict[str, object]]", payload["counts"])
    lines = [
        "# Crawl Run Summary",
        "",
        f"- Run ID: `{payload['run_id']}`",
        f"- Seed URL: `{payload['seed_url']}`",
        f"- Final lifecycle: `{payload['lifecycle']}`",
        "",
        "## Stages",
        "",
        "| Stage | State | Explanation |",
        "| --- | --- | --- |",
    ]
    for item in stages:
        explanation = str(item["explanation"] or "").replace("|", "\\|")
        lines.append(f"| {item['stage']} | {item['state']} | {explanation} |")
    lines.extend(["", "## Counts", ""])
    for group in ("crawl", "recommendations", "xml"):
        values = counts[group]
        lines.append(f"### {group.title()}")
        lines.append("")
        if values:
            lines.extend(f"- {key}: {value}" for key, value in sorted(values.items()))
        else:
            lines.append("- Not available")
        lines.append("")
    publication = payload["publication"]
    lines.extend(["## Publication", "", f"- {publication or 'Not requested'}", ""])
    for heading, key in (("Warnings", "warnings"), ("Failures", "failures")):
        lines.extend([f"## {heading}", ""])
        items = cast("list[dict[str, object]]", payload[key])
        lines.extend(
            f"- `{item['code']}` ({item.get('stage') or 'run'}): "
            f"{item.get('message') or item.get('explanation')}"
            for item in items
        )
        if not items:
            lines.append("- None")
        lines.append("")
    blocked = [item for item in stages if item["state"] == RunStageState.BLOCKED.value]
    lines.extend(["## Deferred or Blocked Stages", ""])
    lines.extend(f"- {item['stage']}" for item in blocked)
    if not blocked:
        lines.append("- None")
    lines.extend(["", "## Versions", ""])
    versions = cast("dict[str, object]", payload["versions"])
    lines.extend(f"- {key}: `{value}`" for key, value in sorted(versions.items()))
    lines.extend(["", "## Safe Configuration", "", "```json"])
    lines.extend(
        json.dumps(
            payload["configuration"], ensure_ascii=False, indent=2, sort_keys=True
        ).splitlines()
    )
    lines.extend(["```", ""])
    return "\n".join(lines)


class RunSummaryWriter:
    """Write fixed-name summary artifacts through the accepted atomic writer."""

    def __init__(self, writer: LocalAtomicWriter | None = None) -> None:
        self._writer = writer or LocalAtomicWriter()

    def write(
        self,
        artifacts: tuple[RunSummaryArtifact, ...],
        configuration: RunSummaryConfiguration,
    ) -> RunSummaryWriteResult:
        if tuple(item.logical_name for item in artifacts) != (
            RUN_SUMMARY_JSON_NAME,
            RUN_SUMMARY_MARKDOWN_NAME,
        ):
            return _blocked(
                "invalid_logical_filename",
                "Summary artifacts must use the two fixed v1 logical names",
            )
        failure = _validate_root(configuration)
        if failure is not None:
            return RunSummaryWriteResult(RunSummaryWriteState.BLOCKED, (), (failure,))
        root = configuration.output_root
        if configuration.dry_run:
            return RunSummaryWriteResult(RunSummaryWriteState.DRY_RUN, (), ())
        if not root.exists():
            try:
                root.mkdir(parents=True, exist_ok=False)
            except OSError:
                return _blocked(
                    "directory_creation_failed", "Summary output root could not be created"
                )
        written: list[RunSummaryWrittenFile] = []
        failures: list[RunSummaryWriteFailure] = []
        for artifact in artifacts:
            target = root / artifact.logical_name
            existed = target.exists()
            planned = PlannedPublicationFile(
                logical_name=artifact.logical_name,
                document_type=PublicationDocumentType.MANIFEST,
                target_path=target,
                content=artifact.content,
                byte_count=artifact.byte_count,
                sha256=artifact.sha256,
                entry_count=None,
                existed_at_planning=existed,
            )
            try:
                self._writer.write(planned, configuration.existing_file_policy)
            except AtomicWriteError as error:
                failures.append(
                    RunSummaryWriteFailure(
                        error.code.value,
                        "Atomic summary publication failed",
                        artifact.logical_name,
                    )
                )
                break
            written.append(
                RunSummaryWrittenFile(
                    artifact.logical_name,
                    artifact.byte_count,
                    artifact.sha256,
                    existed,
                )
            )
        state = (
            RunSummaryWriteState.WRITTEN
            if not failures
            else RunSummaryWriteState.PARTIALLY_FAILED
            if written
            else RunSummaryWriteState.BLOCKED
        )
        return RunSummaryWriteResult(state, tuple(written), tuple(failures))


def _validate_root(
    configuration: RunSummaryConfiguration,
) -> RunSummaryWriteFailure | None:
    root = configuration.output_root
    if not root.is_absolute():
        return RunSummaryWriteFailure(
            "output_root_not_absolute", "Summary output root must be absolute"
        )
    if any(part.casefold() == ".git" for part in root.parts):
        return RunSummaryWriteFailure(
            "output_root_prohibited", "Summary output root cannot be .git"
        )
    if root.exists() and not root.is_dir():
        return RunSummaryWriteFailure(
            "output_root_is_file", "Summary output root is not a directory"
        )
    if not root.exists() and not configuration.create_output_directory:
        return RunSummaryWriteFailure("output_root_missing", "Summary output root does not exist")
    for candidate in _existing_ancestors(root):
        if is_unsafe_link_path(candidate):
            return RunSummaryWriteFailure(
                "output_root_unsafe_symlink",
                "Summary output root contains a symlink or junction",
            )
    return None


def _existing_ancestors(path: Path) -> tuple[Path, ...]:
    current = path
    found: list[Path] = []
    while True:
        if current.exists():
            found.append(current)
        if current.parent == current:
            break
        current = current.parent
    return tuple(found)


def _blocked(code: str, explanation: str) -> RunSummaryWriteResult:
    return RunSummaryWriteResult(
        RunSummaryWriteState.BLOCKED,
        (),
        (RunSummaryWriteFailure(code, explanation),),
    )
