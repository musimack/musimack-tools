"""Safe publication planning and per-file atomic local execution."""

from __future__ import annotations

import errno
import os
import re
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, Protocol

from musimack_tools.domain.sitemap_publication import (
    SITEMAP_MANIFEST_LOGICAL_NAME,
    ExistingFilePolicy,
    ManifestArtifact,
    PlannedPublicationFile,
    PublicationDocumentType,
    PublicationFailure,
    PublicationFailureCode,
    PublicationMode,
    PublicationPlanState,
    PublicationState,
    PublishedFileResult,
    SitemapPublicationConfiguration,
    SitemapPublicationPlan,
    SitemapPublicationResult,
)
from musimack_tools.sitemap.manifest import build_manifest, sha256_hex

if TYPE_CHECKING:
    from musimack_tools.domain.sitemap_xml import SitemapXmlBundle

_SAFE_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_WINDOWS_RESERVED_STEMS = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
)
_UNSUPPORTED_HARD_LINK_ERRNOS = frozenset(
    {
        errno.EXDEV,
        errno.ENOTSUP,
        errno.EOPNOTSUPP,
    }
)
_UNSUPPORTED_HARD_LINK_WINERRORS = frozenset({1, 17, 50})
_Payload = tuple[str, PublicationDocumentType, bytes, int | None]


class AtomicWriteError(Exception):
    """Bounded internal failure raised by the atomic writer."""

    def __init__(self, code: PublicationFailureCode) -> None:
        self.code = code
        super().__init__(code.value)


class AtomicWriter(Protocol):
    """Injectable individual-file atomic write boundary."""

    def write(self, planned_file: PlannedPublicationFile, policy: ExistingFilePolicy) -> None:
        """Write one planned file or raise a bounded atomic-write failure."""
        ...


class _BinaryTemporaryFile(Protocol):
    def write(self, content: bytes) -> int: ...

    def flush(self) -> None: ...

    def fileno(self) -> int: ...


class LocalAtomicWriter:
    """Write through a secure temporary file on the destination filesystem."""

    def write(self, planned_file: PlannedPublicationFile, policy: ExistingFilePolicy) -> None:
        temporary_path = _write_temporary_file(planned_file)
        try:
            try:
                if policy is ExistingFilePolicy.FAIL_IF_EXISTS:
                    planned_file.target_path.hardlink_to(temporary_path)
                    temporary_path.unlink()
                else:
                    temporary_path.replace(planned_file.target_path)
            except FileExistsError as error:
                raise AtomicWriteError(PublicationFailureCode.TARGET_EXISTS) from error
            except OSError as error:
                code = (
                    _no_clobber_failure_code(error)
                    if policy is ExistingFilePolicy.FAIL_IF_EXISTS
                    else PublicationFailureCode.ATOMIC_REPLACE_FAILED
                )
                raise AtomicWriteError(code) from error
        finally:
            _cleanup_temporary_file(temporary_path)


def _write_temporary_file(planned_file: PlannedPublicationFile) -> Path:
    temporary_path: Path | None = None
    try:
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{planned_file.logical_name}.",
                suffix=".tmp",
                dir=planned_file.target_path.parent,
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                _write_and_flush(temporary, planned_file.content)
        except OSError as error:
            raise AtomicWriteError(PublicationFailureCode.TEMPORARY_FILE_CREATION_FAILED) from error
    except AtomicWriteError:
        if temporary_path is not None:
            _cleanup_temporary_file(temporary_path)
        raise
    if temporary_path is None:
        raise AtomicWriteError(PublicationFailureCode.TEMPORARY_FILE_CREATION_FAILED)
    return temporary_path


def _write_and_flush(temporary: _BinaryTemporaryFile, content: bytes) -> None:
    try:
        temporary.write(content)
    except OSError as error:
        raise AtomicWriteError(PublicationFailureCode.WRITE_FAILED) from error
    try:
        temporary.flush()
        os.fsync(temporary.fileno())
    except OSError as error:
        raise AtomicWriteError(PublicationFailureCode.FLUSH_FAILED) from error


def _cleanup_temporary_file(temporary_path: Path) -> None:
    if not temporary_path.exists():
        return
    try:
        temporary_path.unlink()
    except OSError as error:
        raise AtomicWriteError(PublicationFailureCode.CLEANUP_FAILED) from error


def validate_logical_filename(logical_name: str) -> PublicationFailureCode | None:
    """Validate one platform-neutral simple package filename."""
    if not logical_name or "\x00" in logical_name:
        return PublicationFailureCode.INVALID_LOGICAL_FILENAME
    windows_path = PureWindowsPath(logical_name)
    if (
        PurePosixPath(logical_name).is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or "/" in logical_name
        or "\\" in logical_name
    ):
        return PublicationFailureCode.UNSAFE_PATH
    if not _SAFE_FILENAME.fullmatch(logical_name):
        return PublicationFailureCode.INVALID_LOGICAL_FILENAME
    if logical_name.endswith((".", " ")):
        return PublicationFailureCode.INVALID_LOGICAL_FILENAME
    if logical_name.split(".", maxsplit=1)[0].upper() in _WINDOWS_RESERVED_STEMS:
        return PublicationFailureCode.INVALID_LOGICAL_FILENAME
    return None


def plan_publication(
    bundle: SitemapXmlBundle,
    recommendation_rule_set_version: str,
    configuration: SitemapPublicationConfiguration,
) -> SitemapPublicationPlan:
    """Validate a complete package and produce an immutable plan without writing."""
    manifest = build_manifest(bundle, recommendation_rule_set_version, configuration)
    failures: list[PublicationFailure] = []
    output_root, root_exists = _validate_output_root(configuration, failures)
    payloads = _package_payloads(bundle, manifest)
    _validate_package_names(payloads, failures)
    planned_files = (
        []
        if any(_is_root_failure(item.code) for item in failures)
        else _plan_payloads(payloads, output_root, configuration, failures)
    )

    state = PublicationPlanState.BLOCKED if failures else PublicationPlanState.READY
    return SitemapPublicationPlan(
        state=state,
        output_root=output_root,
        files=tuple(planned_files),
        manifest_artifact=manifest,
        failures=tuple(failures),
        configuration_snapshot=configuration,
        output_directory_would_be_created=not root_exists,
    )


class SitemapPublicationExecutor:
    """Execute a validated plan with per-file atomicity and integrity checks."""

    def __init__(self, writer: AtomicWriter | None = None) -> None:
        self._writer = writer or LocalAtomicWriter()

    def execute(self, plan: SitemapPublicationPlan) -> SitemapPublicationResult:
        if plan.state is PublicationPlanState.BLOCKED:
            return _publication_result(PublicationState.BLOCKED, plan, (), plan.failures)
        if plan.configuration_snapshot.mode is PublicationMode.DRY_RUN:
            return _publication_result(PublicationState.DRY_RUN, plan, (), ())

        root_failure = _prepare_output_root(plan)
        if root_failure is not None:
            return _publication_result(PublicationState.BLOCKED, plan, (), (root_failure,))

        published: list[PublishedFileResult] = []
        failures: list[PublicationFailure] = []
        for planned_file in plan.files:
            result, failure = self._publish_one(planned_file, plan.configuration_snapshot)
            if failure is not None:
                failures.append(failure)
                break
            if result is not None:
                published.append(result)

        if failures:
            if published:
                state = PublicationState.PARTIALLY_FAILED
                failures.append(
                    PublicationFailure(
                        PublicationFailureCode.PARTIAL_PACKAGE_PUBLICATION,
                        "A later file failed after one or more package files were published.",
                    )
                )
            else:
                state = PublicationState.BLOCKED
        else:
            state = PublicationState.PUBLISHED
        return _publication_result(state, plan, tuple(published), tuple(failures))

    def _publish_one(
        self,
        planned_file: PlannedPublicationFile,
        configuration: SitemapPublicationConfiguration,
    ) -> tuple[PublishedFileResult | None, PublicationFailure | None]:
        failure = _revalidate_target(planned_file, configuration)
        if failure is not None:
            return None, failure
        existed = planned_file.target_path.exists()
        try:
            self._writer.write(planned_file, configuration.existing_file_policy)
            _verify_published_integrity(planned_file)
        except AtomicWriteError as error:
            return None, PublicationFailure(
                error.code,
                "Atomic publication failed at a controlled filesystem stage.",
                planned_file.logical_name,
                planned_file.target_path,
            )
        return (
            PublishedFileResult(
                logical_name=planned_file.logical_name,
                document_type=planned_file.document_type,
                target_path=planned_file.target_path,
                byte_count=planned_file.byte_count,
                sha256=planned_file.sha256,
                replaced_existing=existed,
            ),
            None,
        )


def _validate_output_root(
    configuration: SitemapPublicationConfiguration,
    failures: list[PublicationFailure],
) -> tuple[Path, bool]:
    supplied_root = configuration.output_root
    if not supplied_root.is_absolute():
        failures.append(
            PublicationFailure(
                PublicationFailureCode.OUTPUT_ROOT_NOT_ABSOLUTE,
                "Output root must be an explicit absolute filesystem path.",
                target_path=supplied_root,
            )
        )
        return supplied_root, supplied_root.exists()
    if any(part.casefold() == ".git" for part in supplied_root.parts):
        failures.append(
            PublicationFailure(
                PublicationFailureCode.OUTPUT_ROOT_PROHIBITED,
                "Output root cannot be inside repository metadata.",
                target_path=supplied_root,
            )
        )
        return supplied_root, supplied_root.exists()
    if _has_symlink_component(supplied_root):
        failures.append(
            PublicationFailure(
                PublicationFailureCode.OUTPUT_ROOT_UNSAFE_SYMLINK,
                "Output root cannot contain an existing symbolic-link component.",
                target_path=supplied_root,
            )
        )
        return supplied_root, supplied_root.exists()

    output_root = supplied_root.resolve(strict=False)
    root_exists = output_root.exists()
    if root_exists and not output_root.is_dir():
        failures.append(
            PublicationFailure(
                PublicationFailureCode.OUTPUT_ROOT_IS_FILE,
                "Configured output root exists but is not a directory.",
                target_path=output_root,
            )
        )
    elif not root_exists and not configuration.create_output_directory:
        failures.append(
            PublicationFailure(
                PublicationFailureCode.OUTPUT_ROOT_MISSING,
                "Output root does not exist and directory creation is disabled.",
                target_path=output_root,
            )
        )
    return output_root, root_exists


def _plan_payloads(
    payloads: list[_Payload],
    output_root: Path,
    configuration: SitemapPublicationConfiguration,
    failures: list[PublicationFailure],
) -> list[PlannedPublicationFile]:
    planned_files: list[PlannedPublicationFile] = []
    for name, document_type, content, entry_count in payloads:
        target = output_root / name
        filename_failure = validate_logical_filename(name)
        if filename_failure is not None:
            failures.append(
                PublicationFailure(
                    filename_failure,
                    "Package logical filename is not a safe simple filename.",
                    name,
                    target,
                )
            )
            continue
        if target.parent.resolve(strict=False) != output_root:
            failures.append(
                PublicationFailure(
                    PublicationFailureCode.UNSAFE_PATH,
                    "Resolved package target is outside the configured output root.",
                    name,
                    target,
                )
            )
            continue
        exists = target.exists() or target.is_symlink()
        planned_files.append(
            PlannedPublicationFile(
                logical_name=name,
                document_type=document_type,
                target_path=target,
                content=content,
                byte_count=len(content),
                sha256=sha256_hex(content),
                entry_count=entry_count,
                existed_at_planning=exists,
            )
        )
        target_failure = _existing_target_failure(
            name,
            target,
            configuration,
            exists=exists,
        )
        if target_failure is not None:
            failures.append(target_failure)
    return planned_files


def _existing_target_failure(
    name: str,
    target: Path,
    configuration: SitemapPublicationConfiguration,
    *,
    exists: bool,
) -> PublicationFailure | None:
    if is_unsafe_link_path(target):
        return PublicationFailure(
            PublicationFailureCode.TARGET_UNSAFE_SYMLINK,
            "Publication target cannot be a symbolic link.",
            name,
            target,
        )
    if target.is_dir():
        return PublicationFailure(
            PublicationFailureCode.TARGET_IS_DIRECTORY,
            "Publication target is an existing directory.",
            name,
            target,
        )
    if exists and configuration.existing_file_policy is ExistingFilePolicy.FAIL_IF_EXISTS:
        return PublicationFailure(
            PublicationFailureCode.TARGET_EXISTS,
            "Publication target exists and overwrite is disabled.",
            name,
            target,
        )
    return None


def _prepare_output_root(plan: SitemapPublicationPlan) -> PublicationFailure | None:
    if not plan.output_root.exists():
        try:
            plan.output_root.mkdir(parents=True, exist_ok=False)
        except OSError:
            return PublicationFailure(
                PublicationFailureCode.DIRECTORY_CREATION_FAILED,
                "Output directory could not be created.",
                target_path=plan.output_root,
            )
    if not plan.output_root.is_dir() or _has_symlink_component(plan.output_root):
        return PublicationFailure(
            PublicationFailureCode.OUTPUT_ROOT_UNSAFE_SYMLINK,
            "Output root changed after planning and is no longer safe.",
            target_path=plan.output_root,
        )
    return None


def _verify_published_integrity(planned_file: PlannedPublicationFile) -> None:
    try:
        actual = planned_file.target_path.read_bytes()
    except OSError as error:
        raise AtomicWriteError(PublicationFailureCode.INTEGRITY_VERIFICATION_FAILED) from error
    if len(actual) != planned_file.byte_count or sha256_hex(actual) != planned_file.sha256:
        raise AtomicWriteError(PublicationFailureCode.INTEGRITY_VERIFICATION_FAILED)


def _package_payloads(
    bundle: SitemapXmlBundle,
    manifest: ManifestArtifact,
) -> list[_Payload]:
    payloads: list[_Payload] = [
        (
            document.logical_name,
            PublicationDocumentType.URL_SITEMAP,
            document.xml_bytes,
            document.entry_count,
        )
        for document in bundle.documents
    ]
    if bundle.index_document is not None:
        index = bundle.index_document
        payloads.append(
            (
                index.logical_name,
                PublicationDocumentType.SITEMAP_INDEX,
                index.xml_bytes,
                index.entry_count,
            )
        )
    payloads.append(
        (
            manifest.logical_name,
            PublicationDocumentType.MANIFEST,
            manifest.content,
            None,
        )
    )
    return payloads


def _validate_package_names(
    payloads: list[_Payload],
    failures: list[PublicationFailure],
) -> None:
    seen: dict[str, str] = {}
    for name, document_type, _, _ in payloads:
        folded = name.casefold()
        if document_type is not PublicationDocumentType.MANIFEST and folded == (
            SITEMAP_MANIFEST_LOGICAL_NAME.casefold()
        ):
            failures.append(
                PublicationFailure(
                    PublicationFailureCode.RESERVED_MANIFEST_COLLISION,
                    "An XML payload uses the reserved manifest logical filename.",
                    name,
                )
            )
        if folded in seen:
            code = (
                PublicationFailureCode.DUPLICATE_LOGICAL_FILENAME
                if seen[folded] == name
                else PublicationFailureCode.CASE_NORMALIZED_COLLISION
            )
            failures.append(
                PublicationFailure(
                    code,
                    "Package logical filenames collide under safe comparison.",
                    name,
                )
            )
        else:
            seen[folded] = name


def _blocked_plan(
    output_root: Path,
    manifest: ManifestArtifact,
    failures: list[PublicationFailure],
    configuration: SitemapPublicationConfiguration,
) -> SitemapPublicationPlan:
    return SitemapPublicationPlan(
        state=PublicationPlanState.BLOCKED,
        output_root=output_root,
        files=(),
        manifest_artifact=manifest,
        failures=tuple(failures),
        configuration_snapshot=configuration,
        output_directory_would_be_created=False,
    )


def _is_root_failure(code: PublicationFailureCode) -> bool:
    return code in {
        PublicationFailureCode.OUTPUT_ROOT_IS_FILE,
        PublicationFailureCode.OUTPUT_ROOT_MISSING,
        PublicationFailureCode.OUTPUT_ROOT_NOT_ABSOLUTE,
        PublicationFailureCode.OUTPUT_ROOT_PROHIBITED,
        PublicationFailureCode.OUTPUT_ROOT_UNSAFE_SYMLINK,
    }


def _has_symlink_component(path: Path) -> bool:
    candidates = (*reversed(path.parents), path)
    return any(is_unsafe_link_path(candidate) for candidate in candidates)


def is_unsafe_link_path(path: Path) -> bool:
    """Classify standard-library-visible symbolic links and Windows junctions."""
    return link_kind_is_unsafe(
        is_symlink=path.is_symlink(),
        is_junction=path.is_junction(),
    )


def link_kind_is_unsafe(*, is_symlink: bool, is_junction: bool) -> bool:
    """Pure platform-neutral classification for the link kinds this boundary detects."""
    return is_symlink or is_junction


def _revalidate_target(
    planned_file: PlannedPublicationFile,
    configuration: SitemapPublicationConfiguration,
) -> PublicationFailure | None:
    target = planned_file.target_path
    if is_unsafe_link_path(target):
        return PublicationFailure(
            PublicationFailureCode.TARGET_UNSAFE_SYMLINK,
            "Target became a symbolic link after planning.",
            planned_file.logical_name,
            target,
        )
    if target.is_dir():
        return PublicationFailure(
            PublicationFailureCode.TARGET_IS_DIRECTORY,
            "Target became a directory after planning.",
            planned_file.logical_name,
            target,
        )
    if target.exists() and configuration.existing_file_policy is ExistingFilePolicy.FAIL_IF_EXISTS:
        return PublicationFailure(
            PublicationFailureCode.TARGET_EXISTS,
            "Target appeared after planning and overwrite is disabled.",
            planned_file.logical_name,
            target,
        )
    return None


def _no_clobber_failure_code(error: OSError) -> PublicationFailureCode:
    if isinstance(error, PermissionError):
        return PublicationFailureCode.NO_CLOBBER_FINALIZATION_PERMISSION_DENIED
    if error.errno in _UNSUPPORTED_HARD_LINK_ERRNOS or (
        getattr(error, "winerror", None) in _UNSUPPORTED_HARD_LINK_WINERRORS
    ):
        return PublicationFailureCode.NO_CLOBBER_FINALIZATION_UNSUPPORTED
    return PublicationFailureCode.NO_CLOBBER_FINALIZATION_FAILED


def _publication_result(
    state: PublicationState,
    plan: SitemapPublicationPlan,
    published_files: tuple[PublishedFileResult, ...],
    failures: tuple[PublicationFailure, ...],
) -> SitemapPublicationResult:
    return SitemapPublicationResult(
        state=state,
        plan=plan,
        published_files=published_files,
        failures=failures,
        published_file_count=len(published_files),
        published_byte_count=sum(item.byte_count for item in published_files),
        manifest_sha256=plan.manifest_artifact.sha256,
    )
