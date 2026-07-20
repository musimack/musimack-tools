"""Deterministic JSON mapping for accepted run requests across restarts."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from musimack_tools.crawl.normalization import normalize_url
from musimack_tools.domain.crawl import (
    CrawlExclusionRule,
    CrawlRequest,
    ExclusionRuleType,
)
from musimack_tools.domain.run import CrawlRunRequest, RunStage
from musimack_tools.domain.run_summary import RunSummaryConfiguration
from musimack_tools.domain.sitemap import RecommendationPolicy
from musimack_tools.domain.sitemap_publication import (
    ExistingFilePolicy,
    PublicationMode,
    SitemapPublicationConfiguration,
)
from musimack_tools.domain.urls import AllowedOrigin, CrawlScopePolicy, ScopeMode
from musimack_tools.sitemap.limits import SitemapXmlConfiguration

_EXPECTED_OBJECT = "durable request field must be an object"
_EXPECTED_ARRAY = "durable request field must be an array"
_EXPECTED_STRING = "durable request field must be a string"
_EXPECTED_INTEGER = "durable request field must be an integer"
_EXPECTED_NUMBER = "durable request field must be numeric"
_EXPECTED_BOOLEAN = "durable request field must be boolean"
_MISSING_FIELD = "durable request is missing a required field"


def serialize_run_request(request: CrawlRunRequest) -> str:
    crawl = request.crawl_request
    publication = request.publication_configuration
    summary = request.summary_configuration
    payload = {
        "crawl": {
            "seed_url": crawl.seed_url.normalized,
            "scope_mode": crawl.scope_policy.mode.value,
            "approved_hosts": sorted(crawl.scope_policy.approved_hosts),
            "allowed_origins": [
                {"scheme": item.scheme, "port": item.effective_port}
                for item in sorted(
                    crawl.scope_policy.allowed_origins,
                    key=lambda item: (item.scheme, item.effective_port),
                )
            ],
            "maximum_unique_urls": crawl.maximum_unique_urls,
            "maximum_depth": crawl.maximum_depth,
            "maximum_duration_seconds": crawl.maximum_duration_seconds,
            "maximum_total_fetched_bytes": crawl.maximum_total_fetched_bytes,
            "maximum_concurrent_fetches": crawl.maximum_concurrent_fetches,
            "maximum_queued_urls": crawl.maximum_queued_urls,
            "minimum_per_origin_delay_seconds": crawl.minimum_per_origin_delay_seconds,
            "query_urls_allowed": crawl.query_urls_allowed,
            "exclusion_rules": [
                {"rule_type": item.rule_type.value, "value": item.value}
                for item in crawl.exclusion_rules
            ],
            "strip_query_parameters": list(crawl.strip_query_parameters),
            "correlation_id": crawl.correlation_id,
        },
        "requested_stages": [stage.value for stage in request.requested_stages],
        "recommendation_policy": asdict(request.recommendation_policy),
        "xml_configuration": asdict(request.xml_configuration),
        "publication_configuration": (
            None
            if publication is None
            else {
                "output_root": str(publication.output_root),
                "existing_file_policy": publication.existing_file_policy.value,
                "create_output_directory": publication.create_output_directory,
                "mode": publication.mode.value,
            }
        ),
        "summary_configuration": (
            None
            if summary is None
            else {
                "output_root": str(summary.output_root),
                "existing_file_policy": summary.existing_file_policy.value,
                "create_output_directory": summary.create_output_directory,
                "dry_run": summary.dry_run,
            }
        ),
        "caller_label": request.caller_label,
        "robots_product_token": request.robots_product_token,
        "orchestration_version": request.orchestration_version,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def deserialize_run_request(value: str) -> CrawlRunRequest:
    try:
        return _deserialize_run_request(value)
    except KeyError as error:
        raise TypeError(_MISSING_FIELD) from error


def _deserialize_run_request(value: str) -> CrawlRunRequest:
    payload = _mapping(json.loads(value))
    crawl = _mapping(payload["crawl"])
    seed = normalize_url(_string(crawl["seed_url"]))
    origins = frozenset(
        AllowedOrigin(_string(item["scheme"]), _integer(item["port"]))
        for item in (_mapping(raw) for raw in _list(crawl["allowed_origins"]))
    )
    scope = CrawlScopePolicy(
        seed,
        ScopeMode(_string(crawl["scope_mode"])),
        frozenset(_string(item) for item in _list(crawl["approved_hosts"])),
        origins,
    )
    crawl_request = CrawlRequest(
        seed_url=seed,
        scope_policy=scope,
        maximum_unique_urls=_integer(crawl["maximum_unique_urls"]),
        maximum_depth=_integer(crawl["maximum_depth"]),
        maximum_duration_seconds=_number(crawl["maximum_duration_seconds"]),
        maximum_total_fetched_bytes=_integer(crawl["maximum_total_fetched_bytes"]),
        maximum_concurrent_fetches=_integer(crawl["maximum_concurrent_fetches"]),
        maximum_queued_urls=_integer(crawl["maximum_queued_urls"]),
        minimum_per_origin_delay_seconds=_number(crawl["minimum_per_origin_delay_seconds"]),
        query_urls_allowed=_boolean(crawl["query_urls_allowed"]),
        exclusion_rules=tuple(
            CrawlExclusionRule(
                ExclusionRuleType(_string(item["rule_type"])), _string(item["value"])
            )
            for item in (_mapping(raw) for raw in _list(crawl["exclusion_rules"]))
        ),
        strip_query_parameters=tuple(
            _string(item) for item in _list(crawl.get("strip_query_parameters", []))
        ),
        correlation_id=_optional_string(crawl["correlation_id"]),
    )
    recommendation = RecommendationPolicy(**_mapping(payload["recommendation_policy"]))
    xml = SitemapXmlConfiguration(**_mapping(payload["xml_configuration"]))
    publication_raw = payload["publication_configuration"]
    publication = None
    if publication_raw is not None:
        item = _mapping(publication_raw)
        publication = SitemapPublicationConfiguration(
            output_root=Path(_string(item["output_root"])),
            existing_file_policy=ExistingFilePolicy(_string(item["existing_file_policy"])),
            create_output_directory=_boolean(item["create_output_directory"]),
            mode=PublicationMode(_string(item["mode"])),
        )
    summary_raw = payload["summary_configuration"]
    summary = None
    if summary_raw is not None:
        item = _mapping(summary_raw)
        summary = RunSummaryConfiguration(
            output_root=Path(_string(item["output_root"])),
            existing_file_policy=ExistingFilePolicy(_string(item["existing_file_policy"])),
            create_output_directory=_boolean(item["create_output_directory"]),
            dry_run=_boolean(item["dry_run"]),
        )
    return CrawlRunRequest(
        crawl_request=crawl_request,
        requested_stages=tuple(
            RunStage(_string(item)) for item in _list(payload["requested_stages"])
        ),
        recommendation_policy=recommendation,
        xml_configuration=xml,
        publication_configuration=publication,
        summary_configuration=summary,
        caller_label=_optional_string(payload["caller_label"]),
        robots_product_token=_string(payload["robots_product_token"]),
        orchestration_version=_string(payload["orchestration_version"]),
    )


def _mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(_EXPECTED_OBJECT)
    return cast("dict[str, Any]", value)


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(_EXPECTED_ARRAY)
    return cast("list[object]", value)


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(_EXPECTED_STRING)
    return value


def _optional_string(value: object) -> str | None:
    return None if value is None else _string(value)


def _integer(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(_EXPECTED_INTEGER)
    return value


def _number(value: object) -> int | float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError(_EXPECTED_NUMBER)
    return value


def _boolean(value: object) -> bool:
    if not isinstance(value, bool):
        raise TypeError(_EXPECTED_BOOLEAN)
    return value
