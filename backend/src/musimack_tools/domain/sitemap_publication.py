"""Immutable contracts for safe local sitemap package publication."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

SITEMAP_PUBLICATION_MANIFEST_VERSION = "sitemap-publication-manifest-v1"
SITEMAP_PUBLICATION_VERSION = "sitemap-publication-v1"
SITEMAP_MANIFEST_LOGICAL_NAME = "sitemap-manifest.json"


class ExistingFilePolicy(StrEnum):
    """Controlled behavior when an intended target already exists."""

    FAIL_IF_EXISTS = "fail_if_exists"
    OVERWRITE = "overwrite"


class PublicationMode(StrEnum):
    """Whether a validated plan is previewed or executed."""

    DRY_RUN = "dry_run"
    PUBLISH = "publish"


class PublicationDocumentType(StrEnum):
    """Stable package file classifications."""

    URL_SITEMAP = "url_sitemap"
    SITEMAP_INDEX = "sitemap_index"
    MANIFEST = "manifest"


class PublicationPlanState(StrEnum):
    """Outcome of publication planning."""

    READY = "ready"
    BLOCKED = "blocked"


class PublicationState(StrEnum):
    """Explicit orchestration publication outcomes."""

    NOT_REQUESTED = "not_requested"
    DRY_RUN = "dry_run"
    PUBLISHED = "published"
    BLOCKED = "blocked"
    PARTIALLY_FAILED = "partially_failed"


class PublicationFailureCode(StrEnum):
    """Stable configuration, safety, conflict, and filesystem failures."""

    MISSING_OUTPUT_ROOT = "missing_output_root"
    OUTPUT_ROOT_NOT_ABSOLUTE = "output_root_not_absolute"
    OUTPUT_ROOT_IS_FILE = "output_root_is_file"
    OUTPUT_ROOT_MISSING = "output_root_missing"
    OUTPUT_ROOT_PROHIBITED = "output_root_prohibited"
    OUTPUT_ROOT_UNSAFE_SYMLINK = "output_root_unsafe_symlink"
    INVALID_EXISTING_FILE_POLICY = "invalid_existing_file_policy"
    INVALID_LOGICAL_FILENAME = "invalid_logical_filename"
    UNSAFE_PATH = "unsafe_path"
    DUPLICATE_LOGICAL_FILENAME = "duplicate_logical_filename"
    RESERVED_MANIFEST_COLLISION = "reserved_manifest_collision"
    CASE_NORMALIZED_COLLISION = "case_normalized_collision"
    TARGET_EXISTS = "target_exists"
    TARGET_IS_DIRECTORY = "target_is_directory"
    TARGET_UNSAFE_SYMLINK = "target_unsafe_symlink"
    DIRECTORY_CREATION_FAILED = "directory_creation_failed"
    TEMPORARY_FILE_CREATION_FAILED = "temporary_file_creation_failed"
    WRITE_FAILED = "write_failed"
    FLUSH_FAILED = "flush_failed"
    ATOMIC_REPLACE_FAILED = "atomic_replace_failed"
    NO_CLOBBER_FINALIZATION_UNSUPPORTED = "no_clobber_finalization_unsupported"
    NO_CLOBBER_FINALIZATION_PERMISSION_DENIED = "no_clobber_finalization_permission_denied"
    NO_CLOBBER_FINALIZATION_FAILED = "no_clobber_finalization_failed"
    CLEANUP_FAILED = "cleanup_failed"
    INTEGRITY_VERIFICATION_FAILED = "integrity_verification_failed"
    MANIFEST_GENERATION_FAILED = "manifest_generation_failed"
    PUBLICATION_PLAN_INVALID = "publication_plan_invalid"
    PARTIAL_PACKAGE_PUBLICATION = "partial_package_publication"


@dataclass(frozen=True, slots=True)
class SitemapPublicationConfiguration:
    """Explicit local publication configuration for one package."""

    output_root: Path
    existing_file_policy: ExistingFilePolicy = ExistingFilePolicy.FAIL_IF_EXISTS
    create_output_directory: bool = False
    mode: PublicationMode = PublicationMode.PUBLISH

    def __post_init__(self) -> None:
        output_root_value: object = self.output_root
        policy_value: object = self.existing_file_policy
        mode_value: object = self.mode
        if not isinstance(output_root_value, Path):
            message = "output root must be an explicit pathlib.Path"
            raise TypeError(message)
        if not isinstance(policy_value, ExistingFilePolicy):
            message = "existing file policy must be an ExistingFilePolicy"
            raise TypeError(message)
        if not isinstance(mode_value, PublicationMode):
            message = "publication mode must be a PublicationMode"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class PublicationFailure:
    """One bounded planning or execution failure."""

    code: PublicationFailureCode
    explanation: str
    logical_name: str | None = None
    target_path: Path | None = None


@dataclass(frozen=True, slots=True)
class ManifestFileRecord:
    """Integrity and count evidence for one XML payload file."""

    logical_name: str
    document_type: PublicationDocumentType
    media_type: str
    byte_count: int
    sha256: str
    entry_count: int


@dataclass(frozen=True, slots=True)
class SitemapPublicationManifest:
    """Typed deterministic manifest content before JSON serialization."""

    schema_version: str
    xml_format_version: str
    recommendation_rule_set_version: str
    xml_file_count: int
    url_sitemap_document_count: int
    index_present: bool
    total_serialized_url_entries: int
    total_xml_bytes: int
    duplicate_suppression_count: int
    rejected_url_count: int
    skipped_non_include_count: int
    index_blockage_codes: tuple[str, ...]
    existing_file_policy: ExistingFilePolicy
    create_output_directory: bool
    files: tuple[ManifestFileRecord, ...]


@dataclass(frozen=True, slots=True)
class ManifestArtifact:
    """Serialized manifest bytes and non-recursive integrity evidence."""

    logical_name: str
    manifest: SitemapPublicationManifest
    content: bytes
    byte_count: int
    sha256: str


@dataclass(frozen=True, slots=True)
class PlannedPublicationFile:
    """One completely validated intended filesystem mutation."""

    logical_name: str
    document_type: PublicationDocumentType
    target_path: Path
    content: bytes
    byte_count: int
    sha256: str
    entry_count: int | None
    existed_at_planning: bool


@dataclass(frozen=True, slots=True)
class SitemapPublicationPlan:
    """Immutable package plan produced before any filesystem mutation."""

    state: PublicationPlanState
    output_root: Path
    files: tuple[PlannedPublicationFile, ...]
    manifest_artifact: ManifestArtifact
    failures: tuple[PublicationFailure, ...]
    configuration_snapshot: SitemapPublicationConfiguration
    output_directory_would_be_created: bool
    publication_version: str = SITEMAP_PUBLICATION_VERSION


@dataclass(frozen=True, slots=True)
class PublishedFileResult:
    """Integrity-verified result for one atomically published file."""

    logical_name: str
    document_type: PublicationDocumentType
    target_path: Path
    byte_count: int
    sha256: str
    replaced_existing: bool


@dataclass(frozen=True, slots=True)
class SitemapPublicationResult:
    """Complete typed result of planning, preview, or execution."""

    state: PublicationState
    plan: SitemapPublicationPlan | None
    published_files: tuple[PublishedFileResult, ...]
    failures: tuple[PublicationFailure, ...]
    published_file_count: int
    published_byte_count: int
    manifest_sha256: str | None
    publication_version: str = SITEMAP_PUBLICATION_VERSION
