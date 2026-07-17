"""Environment-backed settings for optional local persistence."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 -- Pydantic resolves this field type at runtime.

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from musimack_tools.domain.internal_link import InternalLinkConfiguration
from musimack_tools.domain.link_audit import LinkAuditConfiguration
from musimack_tools.domain.metadata_audit import MetadataAuditConfiguration
from musimack_tools.domain.page_evidence import PageEvidenceConfiguration
from musimack_tools.domain.persistence import (
    PersistenceConfiguration,
    PersistenceRetentionPolicy,
    SQLiteJournalMode,
    SQLiteSynchronousMode,
)
from musimack_tools.domain.sitemap_audit import SitemapAuditConfiguration

_MISSING_PATH = "an explicit database path is required when persistence is enabled"


class PersistenceSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="MUSIMACK_PERSISTENCE_",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    enabled: bool = False
    database_path: Path | None = None
    echo_sql: bool = False
    foreign_keys: bool = True
    busy_timeout_milliseconds: int = Field(default=5_000, ge=100, le=120_000)
    journal_mode: SQLiteJournalMode = SQLiteJournalMode.WAL
    synchronous_mode: SQLiteSynchronousMode = SQLiteSynchronousMode.NORMAL
    connection_timeout_seconds: float = Field(default=10.0, ge=0.1, le=120.0)
    auto_migrate: bool = False
    reconcile_on_startup: bool = True
    create_parent_directory: bool = False
    maximum_terminal_jobs: int = Field(default=100, ge=0, le=100_000)
    maximum_progress_rows_per_job: int = Field(default=100, ge=0, le=10_000)
    maximum_warning_rows_per_parent: int = Field(default=100, ge=0, le=10_000)
    maximum_failure_rows_per_parent: int = Field(default=100, ge=0, le=10_000)
    maximum_artifact_rows_per_run: int = Field(default=100, ge=0, le=10_000)
    maximum_summary_rows_per_run: int = Field(default=2, ge=0, le=100)
    retain_evicted_job_metadata: bool = True
    retain_interrupted_job_metadata: bool = True
    page_evidence_enabled: bool = False
    page_evidence_batch_size: int = Field(default=250, ge=1, le=10_000)
    page_evidence_default_page_size: int = Field(default=50, ge=1, le=1_000)
    page_evidence_max_page_size: int = Field(default=200, ge=1, le=1_000)
    page_evidence_max_pages_per_run: int = Field(default=100_000, ge=1, le=1_000_000)
    page_evidence_max_redirect_hops: int = Field(default=20, ge=1, le=100)
    page_evidence_max_parse_warnings_per_page: int = Field(default=50, ge=1, le=1_000)
    page_evidence_max_metadata_chars: int = Field(default=4_096, ge=64, le=65_536)
    page_evidence_retention_days: int = Field(default=180, ge=1, le=3_650)
    page_evidence_preserve_terminal_failures: bool = True
    page_evidence_persist_partial_runs: bool = True
    page_evidence_cleanup_batch_size: int = Field(default=500, ge=1, le=10_000)
    metadata_audit_enabled: bool = False
    metadata_audit_title_short_threshold: int = Field(default=20, ge=1, le=999)
    metadata_audit_title_long_threshold: int = Field(default=60, ge=2, le=1_000)
    metadata_audit_description_short_threshold: int = Field(default=70, ge=1, le=1_999)
    metadata_audit_description_long_threshold: int = Field(default=160, ge=2, le=2_000)
    metadata_audit_batch_size: int = Field(default=250, ge=1, le=10_000)
    metadata_audit_default_page_size: int = Field(default=50, ge=1, le=1_000)
    metadata_audit_max_page_size: int = Field(default=200, ge=1, le=1_000)
    metadata_audit_max_pages: int = Field(default=100_000, ge=1, le=1_000_000)
    metadata_audit_max_issues_per_page: int = Field(default=100, ge=1, le=1_000)
    metadata_audit_max_export_rows: int = Field(default=100_000, ge=1, le=1_000_000)
    metadata_audit_duplicate_sample_size: int = Field(default=20, ge=1, le=1_000)
    sitemap_audit_enabled: bool = False
    sitemap_audit_maximum_response_bytes: int = Field(default=5_000_000, ge=1, le=50_000_000)
    sitemap_audit_maximum_urlset_entries: int = Field(default=50_000, ge=1, le=50_000)
    sitemap_audit_maximum_index_children: int = Field(default=50_000, ge=1, le=50_000)
    sitemap_audit_maximum_documents: int = Field(default=100, ge=1, le=10_000)
    sitemap_audit_maximum_depth: int = Field(default=3, ge=0, le=20)
    sitemap_audit_maximum_total_urls: int = Field(default=250_000, ge=1, le=1_000_000)
    sitemap_audit_default_page_size: int = Field(default=50, ge=1, le=1_000)
    sitemap_audit_maximum_page_size: int = Field(default=200, ge=1, le=1_000)
    sitemap_audit_maximum_export_rows: int = Field(default=100_000, ge=1, le=1_000_000)
    sitemap_audit_retention_days: int = Field(default=180, ge=1, le=3_650)
    link_audit_enabled: bool = False
    link_audit_default_page_size: int = Field(default=50, ge=1, le=1_000)
    link_audit_maximum_page_size: int = Field(default=200, ge=1, le=1_000)
    link_audit_maximum_export_rows: int = Field(default=100_000, ge=1, le=1_000_000)
    link_audit_maximum_redirect_chain_depth: int = Field(default=10, ge=1, le=20)
    link_audit_minimum_sitewide_source_pages: int = Field(default=5, ge=2, le=100_000)
    link_audit_minimum_sitewide_crawl_pages: int = Field(default=10, ge=2, le=1_000_000)
    link_audit_sitewide_ratio: float = Field(default=0.5, gt=0, le=1)
    link_audit_retention_days: int = Field(default=180, ge=1, le=3_650)
    internal_link_enabled: bool = False
    internal_link_default_page_size: int = Field(default=50, ge=1, le=1_000)
    internal_link_maximum_page_size: int = Field(default=200, ge=1, le=1_000)
    internal_link_maximum_export_rows: int = Field(default=100_000, ge=1, le=1_000_000)
    internal_link_retention_days: int = Field(default=180, ge=1, le=3_650)

    @model_validator(mode="after")
    def validate_enabled_path(self) -> PersistenceSettings:
        if self.enabled and self.database_path is None:
            raise ValueError(_MISSING_PATH)
        return self

    def to_configuration(self) -> PersistenceConfiguration:
        return PersistenceConfiguration(
            enabled=self.enabled,
            database_path=self.database_path,
            echo_sql=self.echo_sql,
            foreign_keys=self.foreign_keys,
            busy_timeout_milliseconds=self.busy_timeout_milliseconds,
            journal_mode=self.journal_mode,
            synchronous_mode=self.synchronous_mode,
            connection_timeout_seconds=self.connection_timeout_seconds,
            auto_migrate=self.auto_migrate,
            reconcile_on_startup=self.reconcile_on_startup,
            create_parent_directory=self.create_parent_directory,
            retention=PersistenceRetentionPolicy(
                maximum_terminal_jobs=self.maximum_terminal_jobs,
                maximum_progress_rows_per_job=self.maximum_progress_rows_per_job,
                maximum_warning_rows_per_parent=self.maximum_warning_rows_per_parent,
                maximum_failure_rows_per_parent=self.maximum_failure_rows_per_parent,
                maximum_artifact_rows_per_run=self.maximum_artifact_rows_per_run,
                maximum_summary_rows_per_run=self.maximum_summary_rows_per_run,
                retain_evicted_job_metadata=self.retain_evicted_job_metadata,
                retain_interrupted_job_metadata=self.retain_interrupted_job_metadata,
            ),
            page_evidence=PageEvidenceConfiguration(
                enabled=self.page_evidence_enabled,
                batch_size=self.page_evidence_batch_size,
                default_page_size=self.page_evidence_default_page_size,
                maximum_page_size=self.page_evidence_max_page_size,
                maximum_pages_per_run=self.page_evidence_max_pages_per_run,
                maximum_redirect_hops=self.page_evidence_max_redirect_hops,
                maximum_parse_warnings_per_page=self.page_evidence_max_parse_warnings_per_page,
                maximum_metadata_characters=self.page_evidence_max_metadata_chars,
                retention_days=self.page_evidence_retention_days,
                preserve_terminal_failures=self.page_evidence_preserve_terminal_failures,
                persist_partial_runs=self.page_evidence_persist_partial_runs,
                cleanup_batch_size=self.page_evidence_cleanup_batch_size,
            ),
            metadata_audit=MetadataAuditConfiguration(
                enabled=self.metadata_audit_enabled,
                title_short_threshold=self.metadata_audit_title_short_threshold,
                title_long_threshold=self.metadata_audit_title_long_threshold,
                description_short_threshold=self.metadata_audit_description_short_threshold,
                description_long_threshold=self.metadata_audit_description_long_threshold,
                batch_size=self.metadata_audit_batch_size,
                default_page_size=self.metadata_audit_default_page_size,
                maximum_page_size=self.metadata_audit_max_page_size,
                maximum_pages=self.metadata_audit_max_pages,
                maximum_issues_per_page=self.metadata_audit_max_issues_per_page,
                maximum_export_rows=self.metadata_audit_max_export_rows,
                duplicate_sample_size=self.metadata_audit_duplicate_sample_size,
            ),
            sitemap_audit=SitemapAuditConfiguration(
                enabled=self.sitemap_audit_enabled,
                maximum_response_bytes=self.sitemap_audit_maximum_response_bytes,
                maximum_urlset_entries=self.sitemap_audit_maximum_urlset_entries,
                maximum_index_children=self.sitemap_audit_maximum_index_children,
                maximum_documents=self.sitemap_audit_maximum_documents,
                maximum_depth=self.sitemap_audit_maximum_depth,
                maximum_total_urls=self.sitemap_audit_maximum_total_urls,
                default_page_size=self.sitemap_audit_default_page_size,
                maximum_page_size=self.sitemap_audit_maximum_page_size,
                maximum_export_rows=self.sitemap_audit_maximum_export_rows,
                retention_days=self.sitemap_audit_retention_days,
            ),
            link_audit=LinkAuditConfiguration(
                enabled=self.link_audit_enabled,
                default_page_size=self.link_audit_default_page_size,
                maximum_page_size=self.link_audit_maximum_page_size,
                maximum_export_rows=self.link_audit_maximum_export_rows,
                maximum_redirect_chain_depth=self.link_audit_maximum_redirect_chain_depth,
                minimum_sitewide_source_pages=self.link_audit_minimum_sitewide_source_pages,
                minimum_sitewide_crawl_pages=self.link_audit_minimum_sitewide_crawl_pages,
                sitewide_ratio=self.link_audit_sitewide_ratio,
                retention_days=self.link_audit_retention_days,
            ),
            internal_link=InternalLinkConfiguration(
                enabled=self.internal_link_enabled,
                default_page_size=self.internal_link_default_page_size,
                maximum_page_size=self.internal_link_maximum_page_size,
                maximum_export_rows=self.internal_link_maximum_export_rows,
                retention_days=self.internal_link_retention_days,
            ),
        )
