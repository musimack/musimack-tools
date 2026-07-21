"""Safe deterministic mapping from accepted domain evidence to storage values."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

from musimack_tools.domain.job import DurableResultProjection
from musimack_tools.run.identity import configuration_snapshot

_INVALID_DURABLE_RESULT_OBJECT = "durable result projection must be an object"
_INVALID_DURABLE_RESULT_ARRAY = "durable result projection field must be an array"

if TYPE_CHECKING:
    from musimack_tools.domain.persistence import ArtifactType
    from musimack_tools.domain.run import CrawlRunRequest, CrawlRunResult


def canonical_configuration(request: CrawlRunRequest) -> tuple[str, str]:
    payload = asdict(configuration_snapshot(request))
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return content, digest


def safe_url(value: str | None) -> str | None:
    if value is None:
        return None
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def safe_message(value: str, maximum: int = 512) -> str:
    normalized = " ".join(value.split())
    return normalized[:maximum]


def stage_states_json(result: CrawlRunResult) -> str:
    return json.dumps(
        [{"stage": item.stage.value, "state": item.state.value} for item in result.stages],
        sort_keys=True,
        separators=(",", ":"),
    )


def durable_result_projection(result: CrawlRunResult) -> DurableResultProjection:
    crawl = result.crawl_result
    recommendations = result.recommendation_projection
    xml = result.xml_bundle
    publication = result.publication_result
    fetches = (
        ()
        if crawl is None
        else tuple(
            record.fetch_result for record in crawl.url_records if record.fetch_result is not None
        )
    )
    robots = () if crawl is None else crawl.robots_origins
    address_fingerprints = tuple(
        sorted(
            {
                hashlib.sha256(address.encode("ascii")).hexdigest()
                for fetch in fetches
                for evidence in fetch.dns_evidence
                for address in evidence.addresses
            }
            | {fingerprint for record in robots for fingerprint in record.address_fingerprints}
        )[:256]
    )
    rejected_codes = {
        "unsupported_scheme",
        "credentials_not_allowed",
        "invalid_hostname",
        "ip_literal_not_allowed",
        "unsafe_hostname",
        "unsafe_resolved_address",
        "mixed_safe_unsafe_dns_answers",
        "port_not_allowed",
        "redirect_scope_denied",
        "redirect_unsafe_destination",
    }
    all_failure_codes = (
        *(
            fetch.failure_code.value if fetch.failure_code is not None else None
            for fetch in fetches
        ),
        *(record.fetch_failure_code for record in robots),
    )
    robots_counts: dict[str, int] = {}
    if crawl is not None:
        for record in crawl.robots_origins:
            key = record.fetch_outcome.value
            robots_counts[key] = robots_counts.get(key, 0) + 1
    return DurableResultProjection(
        run_lifecycle=result.lifecycle.value,
        stage_states=tuple((item.stage.value, item.state.value) for item in result.stages),
        crawl_counts=(
            ()
            if crawl is None
            else (
                ("urls_discovered", crawl.counters.unique_urls_discovered),
                ("urls_admitted", crawl.counters.urls_queued),
                ("urls_over_limit", crawl.counters.urls_over_limit),
                ("urls_fetched", crawl.counters.urls_fetched),
                ("urls_parsed", crawl.counters.html_pages_parsed),
                ("accepted_bytes", crawl.total_accepted_bytes),
            )
        ),
        crawl_error_codes=(
            () if crawl is None else tuple(item.code.value for item in crawl.errors)
        ),
        recommendation_counts=(
            ()
            if recommendations is None
            else (
                ("include", recommendations.included_url_count),
                ("exclude", recommendations.excluded_url_count),
                ("review", recommendations.review_count),
                ("indeterminate", recommendations.indeterminate_count),
            )
        ),
        xml_document_count=xml.total_documents if xml is not None else None,
        xml_entry_count=xml.total_entries if xml is not None else None,
        publication_state=publication.state.value if publication is not None else None,
        published_file_count=(publication.published_file_count if publication is not None else 0),
        publication_filenames=(
            ()
            if publication is None
            else tuple(item.logical_name for item in publication.published_files)
        ),
        manifest_sha256=publication.manifest_sha256 if publication is not None else None,
        summary_hashes=tuple((item.logical_name, item.sha256) for item in result.summaries),
        warning_codes=tuple(item.code for item in result.warnings),
        failure_codes=tuple(item.code.value for item in result.failures),
        downstream_versions=(
            ("run", result.orchestration_version),
            ("recommendation", result.configuration.recommendation_rule_set_version),
            ("xml", result.configuration.xml_format_version),
            ("publication", result.configuration.publication_version),
            ("manifest", result.configuration.manifest_version),
        ),
        crawl_elapsed_seconds=(
            max(0.0, crawl.ended_at_seconds - crawl.started_at_seconds)
            if crawl is not None
            else None
        ),
        outbound_request_count=sum(fetch.attempt_count for fetch in fetches)
        + sum(record.request_attempt_count for record in robots),
        outbound_redirect_count=sum(len(fetch.redirect_chain) for fetch in fetches)
        + sum(record.redirect_count for record in robots),
        rejected_destination_count=sum(code in rejected_codes for code in all_failure_codes),
        resolved_address_fingerprints=address_fingerprints,
        robots_outcome_counts=tuple(sorted(robots_counts.items())),
        dns_resolution_count=sum(len(fetch.dns_evidence) for fetch in fetches)
        + sum(record.dns_resolution_count for record in robots),
        robots_request_count=sum(record.request_attempt_count for record in robots),
        page_request_count=sum(fetch.attempt_count for fetch in fetches),
        accepted_byte_count=crawl.total_accepted_bytes if crawl is not None else 0,
        scope_denial_count=sum(
            code in {"scope_denied", "redirect_scope_denied"} for code in all_failure_codes
        ),
        retry_count=sum(max(0, fetch.attempt_count - 1) for fetch in fetches)
        + sum(max(0, record.request_attempt_count - 1) for record in robots),
        timeout_count=sum(
            code
            in {
                "connect_timeout",
                "read_timeout",
                "write_timeout",
                "pool_timeout",
                "request_deadline_exceeded",
                "dns_resolution_timeout",
            }
            for code in all_failure_codes
        ),
        response_size_rejection_count=sum(
            code == "response_too_large" for code in all_failure_codes
        ),
    )


def durable_result_projection_json(result: CrawlRunResult) -> str:
    return json.dumps(
        asdict(durable_result_projection(result)),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def load_durable_result_projection(value: str) -> DurableResultProjection:
    payload = json.loads(value)
    if not isinstance(payload, dict):
        raise TypeError(_INVALID_DURABLE_RESULT_OBJECT)

    def pairs(name: str) -> tuple[tuple[str, int], ...]:
        raw = payload[name]
        if not isinstance(raw, list):
            raise TypeError(_INVALID_DURABLE_RESULT_ARRAY)
        return tuple((str(item[0]), int(item[1])) for item in raw)

    def string_pairs(name: str) -> tuple[tuple[str, str], ...]:
        raw = payload[name]
        if not isinstance(raw, list):
            raise TypeError(_INVALID_DURABLE_RESULT_ARRAY)
        return tuple((str(item[0]), str(item[1])) for item in raw)

    def strings(name: str) -> tuple[str, ...]:
        raw = payload[name]
        if not isinstance(raw, list):
            raise TypeError(_INVALID_DURABLE_RESULT_ARRAY)
        return tuple(str(item) for item in raw)

    def optional_integer(name: str) -> int | None:
        raw = payload[name]
        return None if raw is None else int(raw)

    return DurableResultProjection(
        run_lifecycle=str(payload["run_lifecycle"]),
        stage_states=string_pairs("stage_states"),
        crawl_counts=pairs("crawl_counts"),
        crawl_error_codes=strings("crawl_error_codes"),
        recommendation_counts=pairs("recommendation_counts"),
        xml_document_count=optional_integer("xml_document_count"),
        xml_entry_count=optional_integer("xml_entry_count"),
        publication_state=(
            None if payload["publication_state"] is None else str(payload["publication_state"])
        ),
        published_file_count=int(payload["published_file_count"]),
        publication_filenames=strings("publication_filenames"),
        manifest_sha256=(
            None if payload["manifest_sha256"] is None else str(payload["manifest_sha256"])
        ),
        summary_hashes=string_pairs("summary_hashes"),
        warning_codes=strings("warning_codes"),
        failure_codes=strings("failure_codes"),
        downstream_versions=string_pairs("downstream_versions"),
        crawl_elapsed_seconds=_crawl_elapsed_seconds(payload),
        outbound_request_count=int(payload.get("outbound_request_count", 0)),
        outbound_redirect_count=int(payload.get("outbound_redirect_count", 0)),
        rejected_destination_count=int(payload.get("rejected_destination_count", 0)),
        resolved_address_fingerprints=(
            tuple(str(item) for item in payload.get("resolved_address_fingerprints", ()))
        ),
        robots_outcome_counts=(
            tuple((str(item[0]), int(item[1])) for item in payload.get("robots_outcome_counts", ()))
        ),
        dns_resolution_count=int(payload.get("dns_resolution_count", 0)),
        robots_request_count=int(payload.get("robots_request_count", 0)),
        page_request_count=int(payload.get("page_request_count", 0)),
        accepted_byte_count=int(payload.get("accepted_byte_count", 0)),
        scope_denial_count=int(payload.get("scope_denial_count", 0)),
        retry_count=int(payload.get("retry_count", 0)),
        timeout_count=int(payload.get("timeout_count", 0)),
        response_size_rejection_count=int(payload.get("response_size_rejection_count", 0)),
    )


def _crawl_elapsed_seconds(payload: dict[str, object]) -> float | None:
    current = payload.get("crawl_elapsed_seconds")
    if current is not None:
        return max(0.0, _result_number(current))
    started = payload.get("crawl_started_at_seconds")
    ended = payload.get("crawl_ended_at_seconds")
    if started is None or ended is None:
        return None
    elapsed = _result_number(ended) - _result_number(started)
    return elapsed if elapsed >= 0 else None


def _result_number(value: object) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError(_INVALID_DURABLE_RESULT_OBJECT)
    return float(value)


def artifact_identifier(run_id: str, kind: ArtifactType, logical_name: str) -> str:
    digest = hashlib.sha256(f"{run_id}\0{kind.value}\0{logical_name}".encode()).hexdigest()
    return f"artifact-{digest[:32]}"


def sitemap_recommendation_identifier(run_id: str, sequence: int, url: str) -> str:
    digest = hashlib.sha256(f"{run_id}\0{sequence}\0{url}".encode()).hexdigest()
    return f"recommendation-{digest[:32]}"


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
