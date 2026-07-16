"""Portable deterministic crawl-run identity and configuration snapshots."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from musimack_tools.domain.run import (
    CRAWL_RUN_ORCHESTRATION_VERSION,
    CrawlRunRequest,
    RunConfigurationSnapshot,
)
from musimack_tools.domain.sitemap_publication import (
    SITEMAP_PUBLICATION_MANIFEST_VERSION,
    SITEMAP_PUBLICATION_VERSION,
)


def configuration_snapshot(request: CrawlRunRequest) -> RunConfigurationSnapshot:
    """Return a safe immutable snapshot without machine-local output paths."""
    crawl = request.crawl_request
    publication = request.publication_configuration
    limits: tuple[tuple[str, int | float | bool], ...] = (
        ("maximum_unique_urls", crawl.maximum_unique_urls),
        ("maximum_depth", crawl.maximum_depth),
        ("maximum_duration_seconds", crawl.maximum_duration_seconds),
        ("maximum_total_fetched_bytes", crawl.maximum_total_fetched_bytes),
        ("maximum_concurrent_fetches", crawl.maximum_concurrent_fetches),
        ("maximum_queued_urls", crawl.maximum_queued_urls),
        ("minimum_per_origin_delay_seconds", crawl.minimum_per_origin_delay_seconds),
        ("query_urls_allowed", crawl.query_urls_allowed),
    )
    return RunConfigurationSnapshot(
        normalized_seed_url=crawl.seed_url.normalized,
        crawl_limits=limits,
        scope_mode=crawl.scope_policy.mode.value,
        approved_hosts=tuple(sorted(crawl.scope_policy.approved_hosts)),
        robots_product_token=request.robots_product_token,
        recommendation_rule_set_version=request.recommendation_policy.rule_set_version,
        xml_format_version=request.xml_configuration.format_version,
        publication_version=SITEMAP_PUBLICATION_VERSION,
        manifest_version=SITEMAP_PUBLICATION_MANIFEST_VERSION,
        requested_stages=tuple(stage.value for stage in request.requested_stages),
        publication_mode=publication.mode.value if publication is not None else None,
        existing_file_policy=(
            publication.existing_file_policy.value if publication is not None else None
        ),
        create_output_directory=(
            publication.create_output_directory if publication is not None else None
        ),
    )


def canonical_identity_bytes(request: CrawlRunRequest) -> bytes:
    """Serialize all portable, meaningful request settings deterministically."""
    snapshot = configuration_snapshot(request)
    payload = {
        "configuration": asdict(snapshot),
        "crawl_exclusion_rules": [
            {"type": item.rule_type.value, "value": item.value}
            for item in request.crawl_request.exclusion_rules
        ],
        "recommendation_policy": asdict(request.recommendation_policy),
        "scope_origins": sorted(
            (item.scheme, item.effective_port)
            for item in request.crawl_request.scope_policy.allowed_origins
        ),
        "summary": (
            None
            if request.summary_configuration is None
            else {
                "create_output_directory": request.summary_configuration.create_output_directory,
                "dry_run": request.summary_configuration.dry_run,
                "existing_file_policy": (request.summary_configuration.existing_file_policy.value),
            }
        ),
        "xml_configuration": {
            key: value
            for key, value in asdict(request.xml_configuration).items()
            if key != "sitemap_base_url"
        }
        | {"sitemap_base_url": request.xml_configuration.sitemap_base_url},
        "orchestration_version": CRAWL_RUN_ORCHESTRATION_VERSION,
    }
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


def run_identity(request: CrawlRunRequest) -> tuple[str, str]:
    """Return the display ID and full lowercase SHA-256 digest."""
    digest = hashlib.sha256(canonical_identity_bytes(request)).hexdigest()
    return f"run-{digest[:12]}", digest
