"""Stable capability declarations for the internal application facade."""

from dataclasses import dataclass
from enum import StrEnum

from musimack_tools.domain.application import APPLICATION_SERVICE_VERSION


class SupportedCapability(StrEnum):
    CRAWL = "crawl"
    ROBOTS = "robots"
    METADATA = "metadata"
    RECOMMENDATION = "recommendation"
    XML = "xml"
    XML_SPLIT = "xml_split"
    SITEMAP_INDEX = "sitemap_index"
    LOCAL_PUBLICATION = "local_publication"
    PUBLICATION_DRY_RUN = "publication_dry_run"
    MANIFEST = "manifest"
    RUN_SUMMARY = "run_summary"
    LIVE_PROGRESS = "live_progress"
    COOPERATIVE_CANCELLATION = "cooperative_cancellation"
    JOB_QUEUE = "job_queue"
    BOUNDED_CONCURRENCY = "bounded_concurrency"
    JOB_RETENTION = "job_retention"


class UnsupportedCapability(StrEnum):
    PUBLIC_API = "public_api"
    AUTHENTICATION = "authentication"
    PERSISTENT_JOBS = "persistent_jobs"
    REMOTE_PUBLICATION = "remote_publication"
    SITEMAP_SUBMISSION = "sitemap_submission"
    COMPRESSION = "compression"
    LASTMOD = "lastmod"
    PRIORITY = "priority"
    CHANGEFREQ = "changefreq"
    FRONTEND = "frontend"


@dataclass(frozen=True, slots=True)
class ApplicationCapabilityReport:
    supported: tuple[SupportedCapability, ...] = tuple(SupportedCapability)
    unsupported: tuple[UnsupportedCapability, ...] = tuple(UnsupportedCapability)
    application_service_version: str = APPLICATION_SERVICE_VERSION
