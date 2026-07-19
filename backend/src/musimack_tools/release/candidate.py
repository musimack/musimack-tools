"""Create and verify deterministic, review-only release candidates."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from musimack_tools import __version__
from musimack_tools.persistence.migrations import (
    PERSISTENCE_HEAD_REVISION,
    STRUCTURED_DATA_AUDIT_REVISION,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

RELEASE_MANIFEST_VERSION = "musimack-release-candidate-v1"
_CHECKSUM_NAME = "CHECKSUMS.sha256"
_MANIFEST_NAME = "release-manifest.json"
_CANDIDATE_PATTERN = re.compile(r"rc-[a-z0-9](?:[a-z0-9.-]{0,59}[a-z0-9])?\Z")
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
_FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_FIXED_MODE = 0o100644
_MAX_CANDIDATE_LENGTH = 64

_REQUIRED_FILES = (
    ".env.example",
    "README.md",
    "backend/alembic.ini",
    "backend/pyproject.toml",
    "backend/requirements.lock",
    "frontend/package.json",
    "frontend/package-lock.json",
)
_REQUIRED_TREES = (
    "backend/alembic",
    "backend/src",
    "frontend/dist",
)
_REQUIRED_DOCUMENTS = (
    "docs/action-pins.md",
    "docs/architecture.md",
    "docs/backup-and-restore.md",
    "docs/ci.md",
    "docs/deployment.md",
    "docs/operations.md",
    "docs/release-checklist.md",
    "docs/release-management.md",
    "docs/templates/release-notes.md",
    "docs/decisions/0073-supervisor-neutral-private-production-operations.md",
    "docs/decisions/0074-pinned-ci-and-review-only-release-candidates.md",
)
_PROHIBITED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}
_PROHIBITED_SUFFIXES = {
    ".cer",
    ".crt",
    ".db",
    ".key",
    ".log",
    ".pem",
    ".pfx",
    ".pid",
    ".pyc",
    ".sqlite",
    ".sqlite3",
    ".trace",
}


class ReleaseCandidateError(RuntimeError):
    """A bounded release-candidate validation failure."""


@dataclass(frozen=True, slots=True)
class ReleaseCandidateResult:
    """Paths and hashes produced for human review."""

    output_directory: Path
    archive: Path
    manifest: Path
    checksums: Path
    archive_sha256: str
    manifest_sha256: str


def validate_candidate_identifier(value: str) -> str:
    """Return a canonical candidate identifier or fail closed."""

    if (
        not value
        or len(value) > _MAX_CANDIDATE_LENGTH
        or not _CANDIDATE_PATTERN.fullmatch(value)
        or ".." in value
    ):
        raise ReleaseCandidateError("candidate_identifier_invalid")
    return value


def validate_git_commit(value: str) -> str:
    """Require a complete lowercase Git object ID."""

    if not _COMMIT_PATTERN.fullmatch(value):
        raise ReleaseCandidateError("git_commit_invalid")
    return value


def create_release_candidate(  # noqa: PLR0913 - explicit release evidence.
    repository_root: Path,
    output_directory: Path,
    *,
    candidate_identifier: str,
    git_commit: str,
    source_timestamp_epoch: int,
    source_ref: str = "detached-commit",
    tool_versions: Mapping[str, str] | None = None,
    validation_summary: Mapping[str, str] | None = None,
) -> ReleaseCandidateResult:
    """Build a deterministic ZIP, manifest, and external checksums."""

    candidate = validate_candidate_identifier(candidate_identifier)
    commit = validate_git_commit(git_commit)
    root = repository_root.resolve(strict=True)
    destination = output_directory.absolute()
    if destination.exists() or destination.is_symlink():
        raise ReleaseCandidateError("output_destination_exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.tmp-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        files = _release_files(root)
        payload_records = tuple(_file_record(root, relative) for relative in files)
        timestamp = (
            datetime.fromtimestamp(source_timestamp_epoch, tz=UTC)
            .isoformat()
            .replace("+00:00", "Z")
        )
        versions = dict(tool_versions or _tool_versions())
        manifest_value: dict[str, object] = {
            "schema_version": RELEASE_MANIFEST_VERSION,
            "candidate_identifier": candidate,
            "product_version": __version__,
            "git_commit": commit,
            "source_ref": source_ref,
            "source_timestamp_utc": timestamp,
            "migration": {
                "head": PERSISTENCE_HEAD_REVISION,
                "parent": STRUCTURED_DATA_AUDIT_REVISION,
            },
            "lock_hashes": {
                "backend/requirements.lock": _sha256(root / "backend/requirements.lock"),
                "frontend/package-lock.json": _sha256(root / "frontend/package-lock.json"),
            },
            "tool_versions": dict(sorted(versions.items())),
            "validation": dict(sorted((validation_summary or {}).items())),
            "known_limitations": "docs/release-management.md#known-limitations",
            "files": payload_records,
        }
        manifest_bytes = _json_bytes(manifest_value)
        manifest_path = temporary / _MANIFEST_NAME
        manifest_path.write_bytes(manifest_bytes)
        archive_name = f"musimack-{candidate}.zip"
        archive_path = temporary / archive_name
        _write_archive(archive_path, root, files, manifest_bytes)
        checksums_path = temporary / _CHECKSUM_NAME
        checksums_path.write_text(
            "".join(
                (
                    f"{_sha256(archive_path)}  {archive_name}\n",
                    f"{_sha256(manifest_path)}  {_MANIFEST_NAME}\n",
                )
            ),
            encoding="utf-8",
            newline="\n",
        )
        temporary.rename(destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    result = ReleaseCandidateResult(
        output_directory=destination,
        archive=destination / archive_name,
        manifest=destination / _MANIFEST_NAME,
        checksums=destination / _CHECKSUM_NAME,
        archive_sha256=_sha256(destination / archive_name),
        manifest_sha256=_sha256(destination / _MANIFEST_NAME),
    )
    verify_release_candidate(result.output_directory)
    return result


def verify_release_candidate(  # noqa: C901, PLR0912
    output_directory: Path,
) -> ReleaseCandidateResult:
    """Verify external checksums, archive membership, and every payload hash."""

    root = output_directory.resolve(strict=True)
    manifest_path = root / _MANIFEST_NAME
    checksums_path = root / _CHECKSUM_NAME
    if not manifest_path.is_file() or not checksums_path.is_file():
        raise ReleaseCandidateError("candidate_metadata_missing")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReleaseCandidateError("candidate_manifest_invalid") from error
    if manifest.get("schema_version") != RELEASE_MANIFEST_VERSION:
        raise ReleaseCandidateError("candidate_manifest_version_invalid")
    candidate = validate_candidate_identifier(str(manifest.get("candidate_identifier", "")))
    validate_git_commit(str(manifest.get("git_commit", "")))
    archive_path = root / f"musimack-{candidate}.zip"
    if not archive_path.is_file():
        raise ReleaseCandidateError("candidate_metadata_missing")
    expected_checksums = _parse_checksums(checksums_path)
    for path in (archive_path, manifest_path):
        if expected_checksums.get(path.name) != _sha256(path):
            raise ReleaseCandidateError("candidate_checksum_mismatch")
    records = manifest.get("files")
    if not isinstance(records, list):
        raise ReleaseCandidateError("candidate_file_manifest_invalid")
    expected: dict[str, tuple[int, str]] = {}
    for value in records:
        if not isinstance(value, dict):
            raise ReleaseCandidateError("candidate_file_manifest_invalid")
        relative = _safe_relative(str(value.get("path", "")))
        size = value.get("size")
        digest = value.get("sha256")
        if not isinstance(size, int) or size < 0 or not _valid_sha256(digest):
            raise ReleaseCandidateError("candidate_file_manifest_invalid")
        expected[relative.as_posix()] = (size, str(digest))
    try:
        with zipfile.ZipFile(archive_path) as archive:
            names = archive.namelist()
            expected_names = [*sorted(expected), _MANIFEST_NAME]
            if names != expected_names or len(names) != len(set(names)):
                raise ReleaseCandidateError("candidate_archive_members_invalid")
            if archive.read(_MANIFEST_NAME) != manifest_path.read_bytes():
                raise ReleaseCandidateError("candidate_archive_manifest_mismatch")
            for name, (size, digest) in expected.items():
                content = archive.read(name)
                if len(content) != size or hashlib.sha256(content).hexdigest() != digest:
                    raise ReleaseCandidateError("candidate_archive_file_mismatch")
    except (OSError, zipfile.BadZipFile, KeyError) as error:
        raise ReleaseCandidateError("candidate_archive_invalid") from error
    return ReleaseCandidateResult(
        output_directory=root,
        archive=archive_path,
        manifest=manifest_path,
        checksums=checksums_path,
        archive_sha256=_sha256(archive_path),
        manifest_sha256=_sha256(manifest_path),
    )


def _release_files(root: Path) -> tuple[PurePosixPath, ...]:
    selected: set[PurePosixPath] = set()
    for value in (*_REQUIRED_FILES, *_REQUIRED_DOCUMENTS):
        relative = _safe_relative(value)
        _require_source_file(root, relative)
        selected.add(relative)
    for value in _REQUIRED_TREES:
        directory = root / value
        if not directory.is_dir() or _unsafe_link(directory):
            raise ReleaseCandidateError("release_source_tree_invalid")
        for path in directory.rglob("*"):
            if path.is_dir():
                continue
            relative = PurePosixPath(path.relative_to(root).as_posix())
            if _prohibited(relative):
                continue
            _require_source_file(root, relative)
            selected.add(relative)
    return tuple(sorted(selected, key=PurePosixPath.as_posix))


def _require_source_file(root: Path, relative: PurePosixPath) -> Path:
    path = root.joinpath(*relative.parts)
    if not path.is_file() or _unsafe_link(path):
        raise ReleaseCandidateError("release_source_file_invalid")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ReleaseCandidateError("release_source_path_escape")
    current = path
    while current != root:
        if _unsafe_link(current):
            raise ReleaseCandidateError("release_source_linked_path")
        current = current.parent
    return path


def _unsafe_link(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def _prohibited(path: PurePosixPath) -> bool:
    return bool(_PROHIBITED_PARTS.intersection(path.parts)) or path.suffix.casefold() in (
        _PROHIBITED_SUFFIXES
    )


def _safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in value
        or ":" in value
        or any(part in {"", "."} for part in path.parts)
    ):
        raise ReleaseCandidateError("release_relative_path_invalid")
    return path


def _file_record(root: Path, relative: PurePosixPath) -> dict[str, object]:
    path = _require_source_file(root, relative)
    return {"path": relative.as_posix(), "size": path.stat().st_size, "sha256": _sha256(path)}


def _write_archive(
    destination: Path,
    root: Path,
    files: Iterable[PurePosixPath],
    manifest: bytes,
) -> None:
    with zipfile.ZipFile(
        destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for relative in files:
            _write_zip_member(
                archive, relative.as_posix(), root.joinpath(*relative.parts).read_bytes()
            )
        _write_zip_member(archive, _MANIFEST_NAME, manifest)


def _write_zip_member(archive: zipfile.ZipFile, name: str, content: bytes) -> None:
    info = zipfile.ZipInfo(name, _FIXED_ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = _FIXED_MODE << 16
    info.flag_bits = 0x800
    archive.writestr(info, content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def _parse_checksums(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        digest, separator, name = line.partition("  ")
        if not separator or not _valid_sha256(digest) or name in values:
            raise ReleaseCandidateError("candidate_checksums_invalid")
        _safe_relative(name)
        values[name] = digest
    if set(values) != {
        _MANIFEST_NAME,
        next((name for name in values if name.endswith(".zip")), ""),
    }:
        raise ReleaseCandidateError("candidate_checksums_invalid")
    return values


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


def _tool_versions() -> dict[str, str]:
    return {
        "git": _command_version(("git", "--version")),
        "node": _command_version(("node", "--version")),
        "npm": _command_version(("npm", "--version")),
        "python": sys.version.split()[0],
    }


def _command_version(command: Sequence[str]) -> str:
    executable = shutil.which(command[0])
    if executable is None:
        raise ReleaseCandidateError("release_tool_version_unavailable")
    try:
        completed = subprocess.run(  # noqa: S603 - fixed, non-shell version commands.
            (executable, *command[1:]),
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ReleaseCandidateError("release_tool_version_unavailable") from error
    return completed.stdout.strip()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--repository-root", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--candidate", required=True)
    create.add_argument("--commit", required=True)
    create.add_argument("--source-timestamp-epoch", type=int, required=True)
    create.add_argument("--source-ref", default="detached-commit")
    verify = subparsers.add_parser("verify")
    verify.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the non-publishing release-candidate command."""

    args = _parser().parse_args(argv)
    try:
        if args.command == "create":
            result = create_release_candidate(
                args.repository_root,
                args.output,
                candidate_identifier=args.candidate,
                git_commit=args.commit,
                source_timestamp_epoch=args.source_timestamp_epoch,
                source_ref=args.source_ref,
                validation_summary={"backend": "passed", "frontend": "passed", "ci": "passed"},
            )
        else:
            result = verify_release_candidate(args.output)
    except ReleaseCandidateError as error:
        sys.stderr.write(f"{error}\n")
        return 2
    sys.stdout.write(
        json.dumps(
            {
                "archive": result.archive.name,
                "archive_sha256": result.archive_sha256,
                "manifest": result.manifest.name,
                "manifest_sha256": result.manifest_sha256,
            },
            sort_keys=True,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
