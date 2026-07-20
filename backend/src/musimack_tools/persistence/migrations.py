"""Internal Alembic runner and schema-revision inspection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect, text

if TYPE_CHECKING:
    from pathlib import Path

INITIAL_PERSISTENCE_REVISION = "0001_persistence"
DURABLE_EXECUTION_REVISION = "0002_durable_execution"
ARTIFACT_STORAGE_REVISION = "0003_artifact_storage"
HISTORY_API_REVISION = "0004_history_api"
AUTHENTICATION_AUTHORIZATION_REVISION = "0005_authentication_authorization"
PAGE_CRAWL_EVIDENCE_REVISION = "0006_page_crawl_evidence"
METADATA_AUDIT_REVISION = "0007_metadata_audit"
SITEMAP_AUDIT_REVISION = "0008_sitemap_audit"
BROKEN_LINK_REDIRECT_ANALYSIS_REVISION = "0009_broken_link_redirect_analysis"
INTERNAL_LINK_ANALYSIS_REVISION = "0010_internal_link_analysis"
IMAGE_ALT_TEXT_AUDIT_REVISION = "0011_image_alt_text_audit"
STRUCTURED_DATA_AUDIT_REVISION = "0012_structured_data_audit"
WEBSITE_MIGRATION_QA_REVISION = "0013_website_migration_qa"
DURABLE_RESULT_PROJECTION_REVISION = "0014_durable_result_projection"
SITEMAP_RECOMMENDATION_RETENTION_REVISION = "0015_sitemap_recommendation_retention"
SITE_AUDIT_SETTINGS_REVISION = "0016_site_audit_settings"
PERSISTENCE_HEAD_REVISION = SITE_AUDIT_SETTINGS_REVISION
PERSISTENCE_HEAD_PARENT_REVISION = SITEMAP_RECOMMENDATION_RETENTION_REVISION


def alembic_configuration(database_url: str, *, backend_root: Path) -> Config:
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def upgrade_to_head(database_url: str, *, backend_root: Path) -> None:
    command.upgrade(alembic_configuration(database_url, backend_root=backend_root), "head")


def downgrade_to_base(database_url: str, *, backend_root: Path) -> None:
    command.downgrade(alembic_configuration(database_url, backend_root=backend_root), "base")


def current_revision(engine: Engine) -> str | None:
    if "alembic_version" not in inspect(engine).get_table_names():
        return None
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()


def schema_is_current(engine: Engine) -> bool:
    return current_revision(engine) == PERSISTENCE_HEAD_REVISION
