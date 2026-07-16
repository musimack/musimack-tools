"""Environment parsing and explicit preparation for artifact storage."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from musimack_tools.domain.artifacts import (
    ARTIFACT_RECONCILIATION_VERSION,
    ARTIFACT_RETRIEVAL_VERSION,
    ARTIFACT_STORAGE_VERSION,
    ArtifactStorageConfiguration,
    ArtifactStorageRootConfiguration,
)

StringTuple = Annotated[tuple[str, ...], NoDecode]
_INVALID_ROOT_SPECIFICATION = "artifact root specifications must use root-id=absolute-path"


class ArtifactStorageSettings(BaseSettings):
    """Frozen settings that never create roots merely by being imported or parsed."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="MUSIMACK_ARTIFACT_",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    enabled: bool = False
    default_root_id: str = "default"
    storage_roots: StringTuple = ()
    maximum_file_bytes: int = Field(default=52_428_800, ge=1, le=1_073_741_824)
    stream_chunk_bytes: int = Field(default=65_536, ge=1_024, le=1_048_576)
    retention_days: int | None = Field(default=90, ge=1, le=36_500)
    cleanup_batch_size: int = Field(default=100, ge=1, le=1_000)
    verify_on_register: bool = True
    verify_on_download: bool = True
    reconcile_on_startup: bool = False
    allow_summary_json: bool = True
    allow_summary_markdown: bool = True
    allow_sitemap_xml: bool = True
    allow_sitemap_index: bool = True
    allow_manifest: bool = True
    allow_csv: bool = False
    storage_version: str = ARTIFACT_STORAGE_VERSION
    retrieval_version: str = ARTIFACT_RETRIEVAL_VERSION
    reconciliation_version: str = ARTIFACT_RECONCILIATION_VERSION

    @field_validator("storage_roots", mode="before")
    @classmethod
    def parse_roots(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        return value

    def to_configuration(self) -> ArtifactStorageConfiguration:
        roots: list[ArtifactStorageRootConfiguration] = []
        for specification in self.storage_roots:
            root_id, separator, raw_path = specification.partition("=")
            if not separator or not root_id or not raw_path:
                raise ValueError(_INVALID_ROOT_SPECIFICATION)
            roots.append(ArtifactStorageRootConfiguration(root_id, Path(raw_path)))
        return ArtifactStorageConfiguration(
            enabled=self.enabled,
            default_root_id=self.default_root_id,
            roots=tuple(roots),
            maximum_file_bytes=self.maximum_file_bytes,
            stream_chunk_bytes=self.stream_chunk_bytes,
            retention_days=self.retention_days,
            cleanup_batch_size=self.cleanup_batch_size,
            verify_on_register=self.verify_on_register,
            verify_on_download=self.verify_on_download,
            reconcile_on_startup=self.reconcile_on_startup,
            allow_summary_json=self.allow_summary_json,
            allow_summary_markdown=self.allow_summary_markdown,
            allow_sitemap_xml=self.allow_sitemap_xml,
            allow_sitemap_index=self.allow_sitemap_index,
            allow_manifest=self.allow_manifest,
            allow_csv=self.allow_csv,
            storage_version=self.storage_version,
            retrieval_version=self.retrieval_version,
            reconciliation_version=self.reconciliation_version,
        )
