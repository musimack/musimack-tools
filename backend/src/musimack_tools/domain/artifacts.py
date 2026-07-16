"""Immutable contracts for local durable artifact storage and retrieval."""

# ruff: noqa: TRY003 - domain validation messages are stable public evidence.

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

ARTIFACT_STORAGE_VERSION = "seo-toolkit-artifact-storage-v1"
ARTIFACT_RETRIEVAL_VERSION = "seo-toolkit-artifact-retrieval-v1"
ARTIFACT_RECONCILIATION_VERSION = "seo-toolkit-artifact-reconciliation-v1"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_MIN_CHUNK = 1_024
_MAX_CHUNK = 1_048_576
_MAX_FILE = 1_073_741_824
_MAX_CLEANUP_BATCH = 1_000


class ArtifactType(StrEnum):
    SITEMAP_XML = "sitemap_xml"
    SITEMAP_INDEX = "sitemap_index"
    PUBLICATION_MANIFEST = "publication_manifest"
    RUN_SUMMARY_JSON = "run_summary_json"
    RUN_SUMMARY_MARKDOWN = "run_summary_markdown"
    CSV_EXPORT = "csv_export"


class ArtifactLifecycleState(StrEnum):
    PLANNED = "planned"
    AVAILABLE = "available"
    MISSING = "missing"
    CORRUPT = "corrupt"
    EXPIRED = "expired"
    DELETED = "deleted"
    RETAINED = "retained"


class ArtifactIntegrityState(StrEnum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    MISSING = "missing"
    SIZE_MISMATCH = "size_mismatch"
    HASH_MISMATCH = "hash_mismatch"
    TYPE_MISMATCH = "type_mismatch"
    UNSAFE_PATH = "unsafe_path"
    READ_FAILED = "read_failed"
    MANIFEST_MISMATCH = "manifest_mismatch"


class ArtifactRetentionState(StrEnum):
    NORMAL = "normal"
    RETAINED = "retained"
    EXPIRED = "expired"
    CLEANUP_PENDING = "cleanup_pending"
    DELETED = "deleted"


class ArtifactFailureCode(StrEnum):
    STORAGE_DISABLED = "artifact_storage_disabled"
    ROOT_NOT_CONFIGURED = "artifact_root_not_configured"
    ROOT_UNAVAILABLE = "artifact_root_unavailable"
    ROOT_NOT_WRITABLE = "artifact_root_not_writable"
    ROOT_UNSAFE = "artifact_root_unsafe"
    TYPE_UNSUPPORTED = "artifact_type_unsupported"
    PATH_INVALID = "artifact_path_invalid"
    PATH_OUTSIDE_ROOT = "artifact_path_outside_root"
    SYMLINK_BLOCKED = "artifact_symlink_blocked"
    JUNCTION_BLOCKED = "artifact_junction_blocked"
    NOT_FOUND = "artifact_not_found"
    NOT_AVAILABLE = "artifact_not_available"
    MISSING = "artifact_missing"
    CORRUPT = "artifact_corrupt"
    EXPIRED = "artifact_expired"
    DELETED = "artifact_deleted"
    RETAINED = "artifact_retained"
    SIZE_EXCEEDED = "artifact_size_exceeded"
    SIZE_MISMATCH = "artifact_size_mismatch"
    HASH_MISMATCH = "artifact_hash_mismatch"
    CONTENT_TYPE_MISMATCH = "artifact_content_type_mismatch"
    REGISTRATION_CONFLICT = "artifact_registration_conflict"
    VERIFICATION_FAILED = "artifact_verification_failed"
    DOWNLOAD_DENIED = "artifact_download_denied"
    CLEANUP_NOT_ALLOWED = "artifact_cleanup_not_allowed"
    CLEANUP_FAILED = "artifact_cleanup_failed"
    RECONCILIATION_FAILED = "artifact_reconciliation_failed"
    MANIFEST_MISMATCH = "artifact_manifest_mismatch"


_VALID_LIFECYCLE_TRANSITIONS = {
    ArtifactLifecycleState.PLANNED: {
        ArtifactLifecycleState.AVAILABLE,
        ArtifactLifecycleState.MISSING,
        ArtifactLifecycleState.CORRUPT,
    },
    ArtifactLifecycleState.AVAILABLE: {
        ArtifactLifecycleState.AVAILABLE,
        ArtifactLifecycleState.MISSING,
        ArtifactLifecycleState.CORRUPT,
        ArtifactLifecycleState.EXPIRED,
        ArtifactLifecycleState.DELETED,
        ArtifactLifecycleState.RETAINED,
    },
    ArtifactLifecycleState.MISSING: {
        ArtifactLifecycleState.MISSING,
        ArtifactLifecycleState.AVAILABLE,
        ArtifactLifecycleState.CORRUPT,
        ArtifactLifecycleState.EXPIRED,
        ArtifactLifecycleState.DELETED,
    },
    ArtifactLifecycleState.CORRUPT: {
        ArtifactLifecycleState.CORRUPT,
        ArtifactLifecycleState.AVAILABLE,
        ArtifactLifecycleState.MISSING,
        ArtifactLifecycleState.EXPIRED,
        ArtifactLifecycleState.DELETED,
    },
    ArtifactLifecycleState.EXPIRED: {
        ArtifactLifecycleState.EXPIRED,
        ArtifactLifecycleState.DELETED,
        ArtifactLifecycleState.RETAINED,
    },
    ArtifactLifecycleState.DELETED: {ArtifactLifecycleState.DELETED},
    ArtifactLifecycleState.RETAINED: {
        ArtifactLifecycleState.RETAINED,
        ArtifactLifecycleState.AVAILABLE,
        ArtifactLifecycleState.MISSING,
        ArtifactLifecycleState.CORRUPT,
        ArtifactLifecycleState.EXPIRED,
    },
}


def validate_artifact_transition(
    current: ArtifactLifecycleState, target: ArtifactLifecycleState
) -> None:
    if target not in _VALID_LIFECYCLE_TRANSITIONS[current]:
        raise ArtifactError(
            ArtifactFailureCode.CLEANUP_NOT_ALLOWED,
            "Artifact lifecycle transition is not allowed.",
        )


class ArtifactError(RuntimeError):
    """Typed safe failure that never embeds a filesystem path."""

    def __init__(self, code: ArtifactFailureCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ArtifactTypePolicy:
    content_type: str
    extension: str
    text: bool
    maximum_bytes: int
    integrity_required: bool = True
    may_expire: bool = True


ARTIFACT_TYPE_POLICIES = {
    ArtifactType.SITEMAP_XML: ArtifactTypePolicy(
        "application/xml", ".xml", text=True, maximum_bytes=52_428_800
    ),
    ArtifactType.SITEMAP_INDEX: ArtifactTypePolicy(
        "application/xml", ".xml", text=True, maximum_bytes=52_428_800
    ),
    ArtifactType.PUBLICATION_MANIFEST: ArtifactTypePolicy(
        "application/json; charset=utf-8", ".json", text=True, maximum_bytes=5_242_880
    ),
    ArtifactType.RUN_SUMMARY_JSON: ArtifactTypePolicy(
        "application/json; charset=utf-8", ".json", text=True, maximum_bytes=10_485_760
    ),
    ArtifactType.RUN_SUMMARY_MARKDOWN: ArtifactTypePolicy(
        "text/markdown; charset=utf-8", ".md", text=True, maximum_bytes=10_485_760
    ),
    ArtifactType.CSV_EXPORT: ArtifactTypePolicy(
        "text/csv; charset=utf-8", ".csv", text=True, maximum_bytes=52_428_800
    ),
}


@dataclass(frozen=True, slots=True)
class ArtifactStorageRootConfiguration:
    root_id: str
    path: Path = field(repr=False, compare=False)
    enabled: bool = True
    writes_enabled: bool = True

    def __post_init__(self) -> None:
        if _SAFE_ID.fullmatch(self.root_id) is None:
            raise ValueError("artifact root identifier is invalid")
        if not self.path.is_absolute():
            raise ValueError("artifact root path must be absolute")
        if ".." in self.path.parts:
            raise ValueError("artifact root path contains unresolved traversal")


@dataclass(frozen=True, slots=True)
class ArtifactStorageConfiguration:
    enabled: bool = False
    default_root_id: str = "default"
    roots: tuple[ArtifactStorageRootConfiguration, ...] = ()
    maximum_file_bytes: int = 52_428_800
    stream_chunk_bytes: int = 65_536
    retention_days: int | None = 90
    cleanup_batch_size: int = 100
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

    def __post_init__(self) -> None:  # noqa: C901, PLR0912
        if self.storage_version != ARTIFACT_STORAGE_VERSION:
            raise ValueError("unsupported artifact storage version")
        if self.retrieval_version != ARTIFACT_RETRIEVAL_VERSION:
            raise ValueError("unsupported artifact retrieval version")
        if self.reconciliation_version != ARTIFACT_RECONCILIATION_VERSION:
            raise ValueError("unsupported artifact reconciliation version")
        if not 1 <= self.maximum_file_bytes <= _MAX_FILE:
            raise ValueError("artifact maximum file bytes is invalid")
        if not _MIN_CHUNK <= self.stream_chunk_bytes <= _MAX_CHUNK:
            raise ValueError("artifact stream chunk bytes is invalid")
        if self.stream_chunk_bytes > self.maximum_file_bytes:
            raise ValueError("artifact stream chunk exceeds maximum file bytes")
        if self.retention_days is not None and self.retention_days <= 0:
            raise ValueError("artifact retention days must be positive or null")
        if not 1 <= self.cleanup_batch_size <= _MAX_CLEANUP_BATCH:
            raise ValueError("artifact cleanup batch size is invalid")
        identifiers = tuple(root.root_id for root in self.roots)
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("artifact root identifiers must be unique")
        if self.enabled and not self.roots:
            raise ValueError("artifact storage requires an explicit root")
        if self.enabled and self.default_root_id not in identifiers:
            raise ValueError("artifact default root is not configured")
        resolved = tuple(root.path.resolve(strict=False) for root in self.roots)
        for index, left in enumerate(resolved):
            for right in resolved[index + 1 :]:
                if left == right or left in right.parents or right in left.parents:
                    raise ValueError("artifact storage roots overlap")

    def type_enabled(self, kind: ArtifactType) -> bool:
        return {
            ArtifactType.SITEMAP_XML: self.allow_sitemap_xml,
            ArtifactType.SITEMAP_INDEX: self.allow_sitemap_index,
            ArtifactType.PUBLICATION_MANIFEST: self.allow_manifest,
            ArtifactType.RUN_SUMMARY_JSON: self.allow_summary_json,
            ArtifactType.RUN_SUMMARY_MARKDOWN: self.allow_summary_markdown,
            ArtifactType.CSV_EXPORT: self.allow_csv,
        }[kind]

    def expiration_for(self, created_at: datetime) -> datetime | None:
        return (
            None
            if self.retention_days is None
            else created_at + timedelta(days=self.retention_days)
        )


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    artifact_id: str
    job_id: str
    run_id: str
    artifact_type: ArtifactType
    root_id: str
    relative_path: str = field(repr=False)
    filename: str
    content_type: str
    lifecycle_state: ArtifactLifecycleState
    integrity_state: ArtifactIntegrityState
    expected_byte_count: int
    observed_byte_count: int | None
    expected_sha256: str
    observed_sha256: str | None
    created_at: datetime
    available_at: datetime | None
    last_verified_at: datetime | None
    expires_at: datetime | None
    deleted_at: datetime | None
    retention_state: ArtifactRetentionState
    reason_code: str | None = None
    storage_version: str = ARTIFACT_STORAGE_VERSION
    retrieval_version: str = ARTIFACT_RETRIEVAL_VERSION
    reconciliation_version: str = ARTIFACT_RECONCILIATION_VERSION


@dataclass(frozen=True, slots=True)
class ArtifactRootReadiness:
    root_id: str
    ready: bool
    readable: bool
    writable: bool
    capacity_bytes: int | None
    checked_at: datetime
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class ArtifactDownloadDescriptor:
    artifact_id: str
    filename: str
    content_type: str
    byte_count: int
    lifecycle_state: ArtifactLifecycleState
    integrity_state: ArtifactIntegrityState
    last_verified_at: datetime | None
    iterator_factory: Callable[[], Iterator[bytes]] = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class ArtifactCleanupResult:
    considered: int
    deleted: int
    missing: int
    failed: int
    dry_run: bool
    artifact_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ArtifactReconciliationResult:
    checked: int
    updated: int
    orphans: int
    failures: int
    bounded: bool
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ArtifactRegistrationBatchResult:
    registered: tuple[ArtifactRecord, ...]
    failure_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ArtifactDiagnostics:
    enabled: bool
    configured_root_count: int
    default_root_id: str | None
    ready_roots: int
    readable_roots: int
    writable_roots: int
    lifecycle_counts: tuple[tuple[str, int], ...]
    retained_count: int
    pending_cleanup_count: int
    verification_failure_count: int
    last_cleanup: ArtifactCleanupResult | None
    last_reconciliation: ArtifactReconciliationResult | None
    storage_version: str = ARTIFACT_STORAGE_VERSION
    retrieval_version: str = ARTIFACT_RETRIEVAL_VERSION
    reconciliation_version: str = ARTIFACT_RECONCILIATION_VERSION
