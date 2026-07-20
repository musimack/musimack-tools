"""Safe local artifact registration, verification, retrieval, cleanup, and reconciliation."""

# ruff: noqa: PLR0913, TRY004, TRY301 - bounded artifact contracts use explicit keyword inputs.

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from musimack_tools.artifacts.path_safety import (
    check_root,
    resolve_artifact_path,
    validate_filename,
    validate_relative_path,
)
from musimack_tools.domain.artifacts import (
    ARTIFACT_TYPE_POLICIES,
    ArtifactCleanupResult,
    ArtifactDiagnostics,
    ArtifactDownloadDescriptor,
    ArtifactError,
    ArtifactFailureCode,
    ArtifactIntegrityState,
    ArtifactLifecycleState,
    ArtifactReconciliationResult,
    ArtifactRecord,
    ArtifactRegistrationBatchResult,
    ArtifactRetentionState,
    ArtifactRootReadiness,
    ArtifactStorageConfiguration,
    ArtifactStorageRootConfiguration,
    ArtifactType,
)

if TYPE_CHECKING:
    from musimack_tools.artifacts.repository import ArtifactRepository

Clock = Callable[[], datetime]
_LOGGER = logging.getLogger("musimack_tools.artifacts")
_MAX_LIST = 200
_MAX_RECONCILE_FILES = 10_000
_SHA256_LENGTH = 64


class ArtifactService:
    """Application boundary whose projections contain no absolute filesystem paths."""

    def __init__(
        self,
        configuration: ArtifactStorageConfiguration,
        repository: ArtifactRepository,
        *,
        clock: Clock | None = None,
    ) -> None:
        self.configuration = configuration
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(UTC))
        self._roots = {root.root_id: root for root in configuration.roots}
        self._last_cleanup: ArtifactCleanupResult | None = None
        self._last_reconciliation: ArtifactReconciliationResult | None = None

    def readiness(self) -> tuple[ArtifactRootReadiness, ...]:
        if not self.configuration.enabled:
            return ()
        outcomes: list[ArtifactRootReadiness] = []
        for root in self.configuration.roots:
            checked = self._clock()
            try:
                readable, writable = check_root(root.path, require_writable=root.writes_enabled)
                capacity = shutil.disk_usage(root.path).free
                outcome = ArtifactRootReadiness(
                    root_id=root.root_id,
                    ready=True,
                    readable=readable,
                    writable=writable,
                    capacity_bytes=capacity,
                    checked_at=checked,
                )
            except (ArtifactError, OSError) as error:
                code = (
                    error.code.value
                    if isinstance(error, ArtifactError)
                    else ArtifactFailureCode.ROOT_UNAVAILABLE.value
                )
                outcome = ArtifactRootReadiness(
                    root_id=root.root_id,
                    ready=False,
                    readable=False,
                    writable=False,
                    capacity_bytes=None,
                    checked_at=checked,
                    reason_code=code,
                )
            self._repository.register_root(outcome)
            outcomes.append(outcome)
            _LOGGER.info(
                "artifact_root_readiness root_id=%s ready=%s reason_code=%s",
                root.root_id,
                outcome.ready,
                outcome.reason_code,
            )
        return tuple(outcomes)

    def diagnostics(self) -> ArtifactDiagnostics:
        readiness = self.readiness()
        records = self._repository.list(offset=0, limit=_MAX_RECONCILE_FILES)
        counts = {
            state.value: sum(record.lifecycle_state is state for record in records)
            for state in ArtifactLifecycleState
        }
        return ArtifactDiagnostics(
            enabled=self.configuration.enabled,
            configured_root_count=len(self.configuration.roots),
            default_root_id=(
                self.configuration.default_root_id if self.configuration.enabled else None
            ),
            ready_roots=sum(item.ready for item in readiness),
            readable_roots=sum(item.readable for item in readiness),
            writable_roots=sum(item.writable for item in readiness),
            lifecycle_counts=tuple(sorted(counts.items())),
            retained_count=sum(
                item.retention_state is ArtifactRetentionState.RETAINED for item in records
            ),
            pending_cleanup_count=sum(
                item.retention_state is ArtifactRetentionState.CLEANUP_PENDING for item in records
            ),
            verification_failure_count=sum(
                item.integrity_state
                not in {ArtifactIntegrityState.UNVERIFIED, ArtifactIntegrityState.VERIFIED}
                for item in records
            ),
            last_cleanup=self._last_cleanup,
            last_reconciliation=self._last_reconciliation,
        )

    @staticmethod
    def managed_relative_path(job_id: str, run_id: str, filename: str) -> str:
        validate_filename(filename)
        for identifier in (job_id, run_id):
            validate_filename(identifier)
        return f"jobs/{job_id}/runs/{run_id}/artifacts/{filename}"

    def register(
        self,
        *,
        job_id: str,
        run_id: str,
        artifact_type: ArtifactType,
        relative_path: str,
        expected_byte_count: int,
        expected_sha256: str,
        root_id: str | None = None,
    ) -> ArtifactRecord:
        root = self._root(root_id)
        normalized = self._validate_contract(
            job_id, run_id, artifact_type, relative_path, expected_byte_count, expected_sha256
        )
        now = self._clock()
        artifact_id = _artifact_id(run_id, artifact_type, root.root_id, normalized)
        existing = self._repository.get(artifact_id)
        if existing is not None:
            if (
                existing.expected_byte_count == expected_byte_count
                and existing.expected_sha256 == expected_sha256
                and existing.relative_path == normalized
            ):
                return existing
            raise ArtifactError(
                ArtifactFailureCode.REGISTRATION_CONFLICT,
                "Artifact registration conflicts with existing metadata.",
            )
        record = ArtifactRecord(
            artifact_id,
            job_id,
            run_id,
            artifact_type,
            root.root_id,
            normalized,
            PurePosixPath(normalized).name,
            ARTIFACT_TYPE_POLICIES[artifact_type].content_type,
            ArtifactLifecycleState.PLANNED,
            ArtifactIntegrityState.UNVERIFIED,
            expected_byte_count,
            None,
            expected_sha256.lower(),
            None,
            now,
            None,
            None,
            self.configuration.expiration_for(now),
            None,
            ArtifactRetentionState.NORMAL,
        )
        self._repository.add(record)
        if not self.configuration.verify_on_register:
            return record
        verified = self.verify(artifact_id)
        if verified.integrity_state is not ArtifactIntegrityState.VERIFIED:
            raise ArtifactError(
                ArtifactFailureCode.VERIFICATION_FAILED,
                "Artifact registration verification failed.",
            )
        _LOGGER.info(
            "artifact_registered artifact_id=%s root_id=%s type=%s",
            artifact_id,
            root.root_id,
            artifact_type.value,
        )
        return verified

    def store_bytes(
        self,
        *,
        job_id: str,
        run_id: str,
        artifact_type: ArtifactType,
        filename: str,
        content: bytes,
        root_id: str | None = None,
    ) -> ArtifactRecord:
        """Write bounded generated content under an accepted root and register it atomically."""
        if not self.configuration.type_enabled(artifact_type):
            raise ArtifactError(ArtifactFailureCode.TYPE_UNSUPPORTED, "Artifact type is disabled.")
        readiness = {item.root_id: item for item in self.readiness()}
        selected_root_id = root_id or self.configuration.default_root_id
        if selected_root_id not in readiness or not readiness[selected_root_id].ready:
            raise ArtifactError(
                ArtifactFailureCode.ROOT_UNAVAILABLE, "Artifact root is unavailable."
            )
        policy = ARTIFACT_TYPE_POLICIES[artifact_type]
        if len(content) > min(policy.maximum_bytes, self.configuration.maximum_file_bytes):
            raise ArtifactError(ArtifactFailureCode.SIZE_EXCEEDED, "Artifact size limit exceeded.")
        relative_path = self.managed_relative_path(job_id, run_id, filename)
        root = self._root(root_id)
        target = resolve_artifact_path(root.path, relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(target)
        except FileExistsError:
            if not target.is_file() or target.read_bytes() != content:
                raise ArtifactError(
                    ArtifactFailureCode.REGISTRATION_CONFLICT,
                    "Generated artifact conflicts with existing content.",
                ) from None
        except OSError:
            raise ArtifactError(
                ArtifactFailureCode.ROOT_NOT_WRITABLE,
                "Generated artifact could not be written.",
            ) from None
        finally:
            temporary.unlink(missing_ok=True)
        return self.register(
            job_id=job_id,
            run_id=run_id,
            artifact_type=artifact_type,
            relative_path=relative_path,
            expected_byte_count=len(content),
            expected_sha256=hashlib.sha256(content).hexdigest(),
            root_id=root.root_id,
        )

    def verify(self, artifact_id: str) -> ArtifactRecord:
        record = self._required(artifact_id)
        now = self._clock()
        observed_bytes: int | None = None
        observed_sha256: str | None = None
        integrity = ArtifactIntegrityState.READ_FAILED
        reason: str | None = ArtifactFailureCode.VERIFICATION_FAILED.value
        try:
            path = self._path(record)
            if not path.exists():
                integrity = ArtifactIntegrityState.MISSING
                reason = ArtifactFailureCode.MISSING.value
            elif not path.is_file():
                integrity = ArtifactIntegrityState.TYPE_MISMATCH
                reason = ArtifactFailureCode.CONTENT_TYPE_MISMATCH.value
            else:
                observed_bytes, observed_sha256 = _hash_file(
                    path, self.configuration.maximum_file_bytes
                )
                if observed_bytes != record.expected_byte_count:
                    integrity = ArtifactIntegrityState.SIZE_MISMATCH
                    reason = ArtifactFailureCode.SIZE_MISMATCH.value
                elif observed_sha256 != record.expected_sha256:
                    integrity = ArtifactIntegrityState.HASH_MISMATCH
                    reason = ArtifactFailureCode.HASH_MISMATCH.value
                elif not record.filename.casefold().endswith(
                    ARTIFACT_TYPE_POLICIES[record.artifact_type].extension.casefold()
                ):
                    integrity = ArtifactIntegrityState.TYPE_MISMATCH
                    reason = ArtifactFailureCode.CONTENT_TYPE_MISMATCH.value
                elif record.artifact_type is ArtifactType.PUBLICATION_MANIFEST:
                    integrity, reason = self._verify_manifest(record, path)
                else:
                    integrity = ArtifactIntegrityState.VERIFIED
                    reason = None
        except ArtifactError as error:
            integrity = ArtifactIntegrityState.UNSAFE_PATH
            reason = error.code.value
        except OSError:
            integrity = ArtifactIntegrityState.READ_FAILED
            reason = ArtifactFailureCode.VERIFICATION_FAILED.value
        lifecycle = (
            ArtifactLifecycleState.RETAINED
            if integrity is ArtifactIntegrityState.VERIFIED
            and record.retention_state is ArtifactRetentionState.RETAINED
            else ArtifactLifecycleState.AVAILABLE
            if integrity is ArtifactIntegrityState.VERIFIED
            else ArtifactLifecycleState.MISSING
            if integrity is ArtifactIntegrityState.MISSING
            else ArtifactLifecycleState.CORRUPT
        )
        updated = self._repository.update_verification(
            artifact_id,
            lifecycle=lifecycle,
            integrity=integrity,
            observed_bytes=observed_bytes,
            observed_sha256=observed_sha256,
            checked_at=now,
            reason_code=reason,
        )
        _LOGGER.info(
            "artifact_verification artifact_id=%s integrity=%s reason_code=%s",
            artifact_id,
            integrity.value,
            reason,
        )
        return updated

    def get(self, artifact_id: str) -> ArtifactRecord:
        return self._required(artifact_id)

    def list(self, *, offset: int = 0, limit: int = 50) -> tuple[ArtifactRecord, ...]:
        if offset < 0 or not 1 <= limit <= _MAX_LIST:
            raise ArtifactError(ArtifactFailureCode.NOT_FOUND, "Artifact list bounds are invalid.")
        return self._repository.list(offset=offset, limit=limit)

    def prepare_download(self, artifact_id: str) -> ArtifactDownloadDescriptor:
        record = self._required(artifact_id)
        if self.configuration.verify_on_download:
            record = self.verify(artifact_id)
        allowed = (
            record.lifecycle_state
            in {ArtifactLifecycleState.AVAILABLE, ArtifactLifecycleState.RETAINED}
            and record.integrity_state is ArtifactIntegrityState.VERIFIED
        )
        if not allowed:
            code = {
                ArtifactLifecycleState.MISSING: ArtifactFailureCode.MISSING,
                ArtifactLifecycleState.CORRUPT: ArtifactFailureCode.CORRUPT,
                ArtifactLifecycleState.EXPIRED: ArtifactFailureCode.EXPIRED,
                ArtifactLifecycleState.DELETED: ArtifactFailureCode.DELETED,
            }.get(record.lifecycle_state, ArtifactFailureCode.NOT_AVAILABLE)
            raise ArtifactError(code, "Artifact is not available for download.")
        authorized_path = self._path(record)
        authorized_identity = _file_identity(authorized_path.stat())

        def iterator() -> Iterator[bytes]:
            path = self._path(record)
            stat = path.stat()
            if (
                not path.is_file()
                or stat.st_size != record.expected_byte_count
                or _file_identity(stat) != authorized_identity
            ):
                raise ArtifactError(
                    ArtifactFailureCode.DOWNLOAD_DENIED, "Artifact changed before download."
                )
            with path.open("rb") as handle:
                opened = os.fstat(handle.fileno())
                if (
                    opened.st_size != record.expected_byte_count
                    or _file_identity(opened) != authorized_identity
                ):
                    raise ArtifactError(
                        ArtifactFailureCode.DOWNLOAD_DENIED, "Artifact changed before download."
                    )
                remaining = record.expected_byte_count
                while remaining:
                    chunk = handle.read(min(self.configuration.stream_chunk_bytes, remaining))
                    if not chunk:
                        raise ArtifactError(
                            ArtifactFailureCode.DOWNLOAD_DENIED, "Artifact changed during download."
                        )
                    remaining -= len(chunk)
                    yield chunk

        _LOGGER.info("artifact_retrieval_authorized artifact_id=%s", artifact_id)
        return ArtifactDownloadDescriptor(
            record.artifact_id,
            record.filename,
            record.content_type,
            record.expected_byte_count,
            record.lifecycle_state,
            record.integrity_state,
            record.last_verified_at,
            iterator,
        )

    def retain(self, artifact_id: str) -> ArtifactRecord:
        record = self._required(artifact_id)
        if record.lifecycle_state is ArtifactLifecycleState.DELETED:
            raise ArtifactError(ArtifactFailureCode.DELETED, "Deleted artifact cannot be retained.")
        return self._repository.transition(
            artifact_id,
            lifecycle=(
                ArtifactLifecycleState.RETAINED
                if record.integrity_state is ArtifactIntegrityState.VERIFIED
                else record.lifecycle_state
            ),
            retention=ArtifactRetentionState.RETAINED,
            occurred_at=self._clock(),
            reason_code=ArtifactFailureCode.RETAINED.value,
        )

    def release_retention(self, artifact_id: str) -> ArtifactRecord:
        record = self._required(artifact_id)
        if record.retention_state is not ArtifactRetentionState.RETAINED:
            return record
        now = self._clock()
        expired = record.expires_at is not None and record.expires_at <= now
        return self._repository.transition(
            artifact_id,
            lifecycle=(
                ArtifactLifecycleState.EXPIRED if expired else ArtifactLifecycleState.AVAILABLE
            ),
            retention=(
                ArtifactRetentionState.EXPIRED if expired else ArtifactRetentionState.NORMAL
            ),
            occurred_at=now,
            reason_code=(ArtifactFailureCode.EXPIRED.value if expired else None),
        )

    def cleanup(self, *, dry_run: bool = False) -> ArtifactCleanupResult:
        now = self._clock()
        candidates = self._repository.cleanup_candidates(now, self.configuration.cleanup_batch_size)
        deleted = missing = failed = 0
        selected: list[str] = []
        for record in candidates:
            selected.append(record.artifact_id)
            if dry_run:
                continue
            try:
                cleanup_record = record
                if record.lifecycle_state is not ArtifactLifecycleState.EXPIRED:
                    cleanup_record = self._repository.transition(
                        record.artifact_id,
                        lifecycle=ArtifactLifecycleState.EXPIRED,
                        retention=ArtifactRetentionState.EXPIRED,
                        occurred_at=now,
                        reason_code=ArtifactFailureCode.EXPIRED.value,
                    )
                path = self._path(cleanup_record)
                if path.exists():
                    if not path.is_file():
                        raise ArtifactError(
                            ArtifactFailureCode.CLEANUP_NOT_ALLOWED,
                            "Artifact cleanup target is not a regular file.",
                        )
                    path.unlink()
                    deleted += 1
                    outcome = "deleted"
                else:
                    missing += 1
                    outcome = "already_missing"
                self._repository.transition(
                    record.artifact_id,
                    lifecycle=ArtifactLifecycleState.DELETED,
                    retention=ArtifactRetentionState.DELETED,
                    occurred_at=now,
                    deleted_at=now,
                    reason_code=None,
                )
                self._repository.record_cleanup(record.artifact_id, now, outcome, None)
            except (ArtifactError, OSError) as error:
                failed += 1
                code = (
                    error.code.value
                    if isinstance(error, ArtifactError)
                    else ArtifactFailureCode.CLEANUP_FAILED.value
                )
                self._repository.record_cleanup(record.artifact_id, now, "failed", code)
        result = ArtifactCleanupResult(
            len(candidates), deleted, missing, failed, dry_run, tuple(selected)
        )
        self._last_cleanup = result
        _LOGGER.info(
            "artifact_cleanup considered=%d deleted=%d failed=%d dry_run=%s",
            result.considered,
            result.deleted,
            result.failed,
            result.dry_run,
        )
        return result

    def reconcile(self) -> ArtifactReconciliationResult:  # noqa: C901, PLR0912, PLR0915
        now = self._clock()
        records = self._repository.list(offset=0, limit=_MAX_RECONCILE_FILES)
        known = {(record.root_id, record.relative_path) for record in records}
        updated = failures = orphans = checked = 0
        reasons: list[str] = []
        for record in records:
            checked += 1
            if record.lifecycle_state is ArtifactLifecycleState.DELETED:
                try:
                    present = self._path(record).exists()
                except ArtifactError as error:
                    present = False
                    failures += 1
                    reasons.append(error.code.value)
                if present:
                    failures += 1
                    reasons.append("artifact_deleted_file_present")
                    self._repository.record_reconciliation(
                        record.root_id,
                        record.artifact_id,
                        now,
                        "artifact_deleted_file_present",
                        "reported",
                    )
                continue
            if record.lifecycle_state is ArtifactLifecycleState.PLANNED:
                try:
                    present = self._path(record).exists()
                except ArtifactError as error:
                    present = False
                    failures += 1
                    reasons.append(error.code.value)
                if present:
                    failures += 1
                    reasons.append("artifact_planned_file_present")
                    self._repository.record_reconciliation(
                        record.root_id,
                        record.artifact_id,
                        now,
                        "artifact_planned_file_present",
                        "reported",
                    )
                continue
            verified = self.verify(record.artifact_id)
            if verified.lifecycle_state != record.lifecycle_state:
                updated += 1
            if verified.integrity_state is not ArtifactIntegrityState.VERIFIED:
                failures += 1
                if verified.reason_code is not None:
                    reasons.append(verified.reason_code)
            self._repository.record_reconciliation(
                record.root_id,
                record.artifact_id,
                now,
                verified.reason_code or "artifact_verified",
                "updated" if verified != record else "unchanged",
            )
        bounded = len(records) >= _MAX_RECONCILE_FILES
        remaining = max(0, _MAX_RECONCILE_FILES - checked)
        for root in self.configuration.roots:
            if remaining == 0:
                bounded = True
                break
            try:
                check_root(root.path, require_writable=False)
                managed = root.path / "jobs"
                if not managed.exists():
                    continue
                for candidate in managed.rglob("*"):
                    if remaining == 0:
                        bounded = True
                        break
                    if candidate.is_symlink() or (os.name == "nt" and candidate.is_junction()):
                        failures += 1
                        reasons.append(ArtifactFailureCode.SYMLINK_BLOCKED.value)
                        continue
                    if not candidate.is_file():
                        continue
                    remaining -= 1
                    relative = candidate.relative_to(root.path).as_posix()
                    if (root.root_id, relative) not in known:
                        orphans += 1
                        self._repository.record_reconciliation(
                            root.root_id, None, now, "artifact_orphan_detected", "reported"
                        )
            except ArtifactError, OSError:
                failures += 1
                reasons.append(ArtifactFailureCode.ROOT_UNAVAILABLE.value)
        result = ArtifactReconciliationResult(
            checked, updated, orphans, failures, bounded, tuple(sorted(set(reasons)))
        )
        self._last_reconciliation = result
        _LOGGER.info(
            "artifact_reconciliation checked=%d updated=%d orphans=%d failures=%d",
            checked,
            updated,
            orphans,
            failures,
        )
        return result

    def register_run_result(self, job_id: str, result: object) -> ArtifactRegistrationBatchResult:
        """Register each successfully written run output independently."""
        from musimack_tools.domain.run import CrawlRunResult  # noqa: PLC0415
        from musimack_tools.domain.sitemap_publication import (  # noqa: PLC0415
            PublicationDocumentType,
        )

        if not isinstance(result, CrawlRunResult):
            raise TypeError("artifact integration requires a CrawlRunResult")  # noqa: TRY003
        generated = self.retain_generated_xml(job_id, result)
        registered: list[ArtifactRecord] = list(generated.registered)
        failures: list[str] = list(generated.failure_codes)

        def attempt(kind: ArtifactType, target: Path, byte_count: int, sha256: str) -> None:
            try:
                root, relative = self._configured_location(target)
                registered.append(
                    self.register(
                        job_id=job_id,
                        run_id=result.run_id,
                        artifact_type=kind,
                        root_id=root.root_id,
                        relative_path=relative,
                        expected_byte_count=byte_count,
                        expected_sha256=sha256,
                    )
                )
            except (ArtifactError, OSError) as error:
                code = (
                    error.code.value
                    if isinstance(error, ArtifactError)
                    else ArtifactFailureCode.VERIFICATION_FAILED.value
                )
                failures.append(code)
                _LOGGER.warning(
                    "artifact_registration_failed job_id=%s run_id=%s reason_code=%s",
                    job_id,
                    result.run_id,
                    code,
                )

        publication = result.publication_result
        if publication is not None:
            mapping = {
                PublicationDocumentType.URL_SITEMAP: ArtifactType.SITEMAP_XML,
                PublicationDocumentType.SITEMAP_INDEX: ArtifactType.SITEMAP_INDEX,
                PublicationDocumentType.MANIFEST: ArtifactType.PUBLICATION_MANIFEST,
            }
            for item in publication.published_files:
                attempt(mapping[item.document_type], item.target_path, item.byte_count, item.sha256)
        if result.summary_write_result is not None:
            by_name = {item.logical_name: item for item in result.summaries}
            for written in result.summary_write_result.written_files:
                artifact = by_name.get(written.logical_name)
                if artifact is None:
                    continue
                kind = (
                    ArtifactType.RUN_SUMMARY_JSON
                    if artifact.format.value == "json"
                    else ArtifactType.RUN_SUMMARY_MARKDOWN
                )
                relative = self.managed_relative_path(job_id, result.run_id, written.logical_name)
                root = self._root(None)
                attempt(
                    kind,
                    root.path.joinpath(*PurePosixPath(relative).parts),
                    written.byte_count,
                    written.sha256,
                )
        return ArtifactRegistrationBatchResult(tuple(registered), tuple(failures))

    def retain_generated_xml(self, job_id: str, result: object) -> ArtifactRegistrationBatchResult:
        """Durably retain generated XML independently of publication and summaries."""
        from musimack_tools.domain.run import CrawlRunResult  # noqa: PLC0415

        if not isinstance(result, CrawlRunResult):
            raise TypeError("artifact integration requires a CrawlRunResult")  # noqa: TRY003
        bundle = result.xml_bundle
        if bundle is None:
            return ArtifactRegistrationBatchResult((), ())
        registered: list[ArtifactRecord] = []
        failures: list[str] = []

        def attempt(kind: ArtifactType, filename: str, content: bytes) -> None:
            try:
                registered.append(
                    self.store_bytes(
                        job_id=job_id,
                        run_id=result.run_id,
                        artifact_type=kind,
                        filename=filename,
                        content=content,
                    )
                )
            except (ArtifactError, OSError) as error:
                code = (
                    error.code.value
                    if isinstance(error, ArtifactError)
                    else ArtifactFailureCode.VERIFICATION_FAILED.value
                )
                failures.append(code)
                _LOGGER.warning(
                    "generated_xml_retention_failed job_id=%s run_id=%s reason_code=%s",
                    job_id,
                    result.run_id,
                    code,
                )

        for document in bundle.documents:
            attempt(ArtifactType.SITEMAP_XML, document.logical_name, document.xml_bytes)
        if bundle.index_document is not None:
            attempt(
                ArtifactType.SITEMAP_INDEX,
                bundle.index_document.logical_name,
                bundle.index_document.xml_bytes,
            )
        return ArtifactRegistrationBatchResult(tuple(registered), tuple(failures))

    def _root(self, root_id: str | None) -> ArtifactStorageRootConfiguration:
        if not self.configuration.enabled:
            raise ArtifactError(
                ArtifactFailureCode.STORAGE_DISABLED, "Artifact storage is disabled."
            )
        selected = root_id or self.configuration.default_root_id
        root = self._roots.get(selected)
        if root is None or not root.enabled:
            raise ArtifactError(
                ArtifactFailureCode.ROOT_NOT_CONFIGURED, "Artifact root is not configured."
            )
        check_root(root.path, require_writable=root.writes_enabled)
        return root

    def _configured_location(self, target: Path) -> tuple[ArtifactStorageRootConfiguration, str]:
        resolved = target.resolve(strict=False)
        for root in self.configuration.roots:
            root_path = root.path.resolve(strict=False)
            if resolved == root_path or root_path in resolved.parents:
                relative = target.relative_to(root.path).as_posix()
                validate_relative_path(relative)
                return root, relative
        raise ArtifactError(
            ArtifactFailureCode.PATH_OUTSIDE_ROOT,
            "Published artifact is outside configured storage roots.",
        )

    def _path(self, record: ArtifactRecord) -> Path:
        root = self._roots.get(record.root_id)
        if root is None:
            raise ArtifactError(
                ArtifactFailureCode.ROOT_NOT_CONFIGURED, "Artifact root is not configured."
            )
        return resolve_artifact_path(root.path, record.relative_path)

    def _required(self, artifact_id: str) -> ArtifactRecord:
        record = self._repository.get(artifact_id)
        if record is None:
            raise ArtifactError(ArtifactFailureCode.NOT_FOUND, "Artifact was not found.")
        return record

    def _validate_contract(
        self,
        job_id: str,
        run_id: str,
        artifact_type: ArtifactType,
        relative_path: str,
        expected_byte_count: int,
        expected_sha256: str,
    ) -> str:
        if not self.configuration.type_enabled(artifact_type):
            raise ArtifactError(
                ArtifactFailureCode.TYPE_UNSUPPORTED, "Artifact type is not enabled."
            )
        maximum = min(
            self.configuration.maximum_file_bytes,
            ARTIFACT_TYPE_POLICIES[artifact_type].maximum_bytes,
        )
        if not 0 <= expected_byte_count <= maximum:
            raise ArtifactError(
                ArtifactFailureCode.SIZE_EXCEEDED, "Artifact exceeds its configured size limit."
            )
        if len(expected_sha256) != _SHA256_LENGTH or any(
            character not in "0123456789abcdefABCDEF" for character in expected_sha256
        ):
            raise ArtifactError(
                ArtifactFailureCode.HASH_MISMATCH, "Artifact expected hash is invalid."
            )
        normalized = validate_relative_path(relative_path)
        expected = self.managed_relative_path(job_id, run_id, PurePosixPath(normalized).name)
        if normalized != expected:
            raise ArtifactError(
                ArtifactFailureCode.PATH_INVALID, "Artifact path is outside the managed layout."
            )
        extension = ARTIFACT_TYPE_POLICIES[artifact_type].extension
        if not normalized.casefold().endswith(extension.casefold()):
            raise ArtifactError(
                ArtifactFailureCode.CONTENT_TYPE_MISMATCH,
                "Artifact filename does not match its type.",
            )
        return normalized

    def _verify_manifest(
        self, record: ArtifactRecord, path: Path
    ) -> tuple[ArtifactIntegrityState, str | None]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError
            files = payload.get("files")
            if not isinstance(files, list):
                raise ValueError
            registered = {
                item.filename: item
                for item in self._repository.list(offset=0, limit=_MAX_RECONCILE_FILES)
                if item.run_id == record.run_id and item.root_id == record.root_id
            }
            for raw_entry in files:
                if not isinstance(raw_entry, dict):
                    raise ValueError
                name = raw_entry.get("logical_name")
                byte_count = raw_entry.get("byte_count")
                sha256 = raw_entry.get("sha256")
                if not isinstance(name, str):
                    raise ValueError
                validate_filename(name)
                target = registered.get(name)
                if (
                    target is None
                    or byte_count != target.expected_byte_count
                    or sha256 != target.expected_sha256
                ):
                    return (
                        ArtifactIntegrityState.MANIFEST_MISMATCH,
                        ArtifactFailureCode.MANIFEST_MISMATCH.value,
                    )
        except OSError, UnicodeError, ValueError, json.JSONDecodeError, ArtifactError:
            return (
                ArtifactIntegrityState.MANIFEST_MISMATCH,
                ArtifactFailureCode.MANIFEST_MISMATCH.value,
            )
        return ArtifactIntegrityState.VERIFIED, None


def _artifact_id(run_id: str, kind: ArtifactType, root_id: str, relative_path: str) -> str:
    digest = hashlib.sha256(
        f"{run_id}\0{kind.value}\0{root_id}\0{relative_path}".encode()
    ).hexdigest()
    return f"artifact-{digest[:32]}"


def _hash_file(path: Path, maximum_bytes: int) -> tuple[int, str]:
    digest = hashlib.sha256()
    observed = 0
    with path.open("rb") as handle:
        while chunk := handle.read(65_536):
            observed += len(chunk)
            if observed > maximum_bytes:
                raise ArtifactError(
                    ArtifactFailureCode.SIZE_EXCEEDED,
                    "Artifact exceeds its configured size limit.",
                )
            digest.update(chunk)
    return observed, digest.hexdigest()


def _file_identity(value: os.stat_result) -> tuple[int, int, int, int]:
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns
