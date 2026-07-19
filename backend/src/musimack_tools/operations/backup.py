"""Consistent offline backup and non-destructive restore for durable production state."""

# ruff: noqa: C901, PLR1714, PLR2004, TRY003

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import uuid
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from musimack_tools.artifacts.path_safety import check_root
from musimack_tools.persistence.migrations import PERSISTENCE_HEAD_REVISION
from musimack_tools.persistence.path_safety import validate_database_path
from musimack_tools.sitemap.publication import is_unsafe_link_path

if TYPE_CHECKING:
    from collections.abc import Iterable

    from musimack_tools.domain.artifacts import ArtifactStorageRootConfiguration

BACKUP_FORMAT_VERSION = "musimack-backup-v1"
MANIFEST_NAME = "manifest.json"
DATABASE_NAME = "database.sqlite3"
_SAFE_ROOT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class BackupError(RuntimeError):
    """Safe operator-facing backup or restore failure."""


@dataclass(frozen=True, slots=True)
class BackupFile:
    path: str
    byte_count: int
    sha256: str
    kind: str
    root_id: str | None = None


@dataclass(frozen=True, slots=True)
class BackupManifest:
    format_version: str
    created_at: str
    application_revision: str | None
    migration_revision: str
    database_file: str
    artifact_root_ids: tuple[str, ...]
    files: tuple[BackupFile, ...]


@dataclass(frozen=True, slots=True)
class BackupResult:
    destination: Path
    database_bytes: int
    artifact_files: int
    total_files: int
    migration_revision: str


@dataclass(frozen=True, slots=True)
class RestoreResult:
    destination: Path
    database_path: Path
    artifact_roots: tuple[tuple[str, Path], ...]
    restored_files: int
    migration_revision: str


def create_backup(  # noqa: PLR0913
    database_path: Path,
    artifact_roots: Iterable[ArtifactStorageRootConfiguration],
    destination: Path,
    *,
    repository_root: Path,
    services_stopped: bool,
    application_revision: str | None = None,
) -> BackupResult:
    """Create a complete backup after explicit confirmation that writers are stopped."""
    if not services_stopped:
        raise BackupError(
            "Backup requires explicit confirmation that web and worker writers are stopped."
        )
    validate_database_path(database_path, repository_root=repository_root)
    if not database_path.is_file() or is_unsafe_link_path(database_path):
        raise BackupError("The source database is missing or unsafe.")
    _validate_new_destination(destination, repository_root=repository_root)
    roots = tuple(artifact_roots)
    for root in roots:
        check_root(root.path, require_writable=False)
        if (
            destination == root.path
            or root.path.resolve(strict=False) in destination.resolve(strict=False).parents
        ):
            raise BackupError("The backup destination cannot be inside an artifact root.")
    database_resolved = database_path.resolve(strict=True)
    destination_resolved = destination.resolve(strict=False)
    if (
        destination_resolved == database_resolved
        or database_resolved.parent == destination_resolved
    ):
        raise BackupError("The backup destination collides with the source database.")

    migration = _database_revision(database_path)
    if migration != PERSISTENCE_HEAD_REVISION:
        raise BackupError("The source database is not at the expected migration head.")
    temporary = destination.with_name(f".{destination.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.mkdir(parents=False, exist_ok=False)
        database_target = temporary / DATABASE_NAME
        _sqlite_backup(database_path, database_target)
        files: list[BackupFile] = [_manifest_file(database_target, DATABASE_NAME, "database")]
        artifact_count = 0
        for root in roots:
            target_root = temporary / "artifacts" / root.root_id
            for source in _safe_files(root.path):
                relative = source.relative_to(root.path)
                portable = PurePosixPath(*relative.parts).as_posix()
                target = target_root.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                _copy_regular_file(source, target)
                manifest_path = f"artifacts/{root.root_id}/{portable}"
                files.append(_manifest_file(target, manifest_path, "artifact", root.root_id))
                artifact_count += 1
        manifest = BackupManifest(
            BACKUP_FORMAT_VERSION,
            datetime.now(UTC).isoformat(),
            application_revision or _git_revision(repository_root),
            migration,
            DATABASE_NAME,
            tuple(root.root_id for root in roots),
            tuple(files),
        )
        (temporary / MANIFEST_NAME).write_text(
            json.dumps(asdict(manifest), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        temporary.replace(destination)
        return BackupResult(
            destination,
            next(item.byte_count for item in files if item.kind == "database"),
            artifact_count,
            len(files),
            migration,
        )
    except Exception as error:
        if temporary.exists():
            shutil.rmtree(temporary)
        if isinstance(error, BackupError):
            raise
        raise BackupError("Backup failed; incomplete output was removed.") from error


def restore_backup(
    source: Path,
    destination: Path,
    *,
    repository_root: Path,
) -> RestoreResult:
    """Verify and atomically restore a backup into one new isolated destination root."""
    _validate_backup_source(source)
    _validate_new_destination(destination, repository_root=repository_root)
    manifest = read_manifest(source)
    _verify_manifest_files(source, manifest)
    if manifest.migration_revision != PERSISTENCE_HEAD_REVISION:
        raise BackupError("The backup migration revision is incompatible with this application.")
    database_source = source / manifest.database_file
    if _database_revision(database_source) != manifest.migration_revision:
        raise BackupError("The backup database revision does not match its manifest.")

    temporary = destination.with_name(f".{destination.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.mkdir(parents=False, exist_ok=False)
        for item in manifest.files:
            relative = _safe_manifest_path(item.path)
            source_file = source.joinpath(*relative.parts)
            target = temporary.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            _copy_regular_file(source_file, target)
        for root_id in manifest.artifact_root_ids:
            temporary.joinpath("artifacts", root_id).mkdir(parents=True, exist_ok=True)
        _verify_manifest_files(temporary, manifest)
        temporary.replace(destination)
    except Exception as error:
        if temporary.exists():
            shutil.rmtree(temporary)
        if isinstance(error, BackupError):
            raise
        raise BackupError("Restore failed; incomplete output was removed.") from error
    artifact_roots = tuple(
        (root_id, destination / "artifacts" / root_id) for root_id in manifest.artifact_root_ids
    )
    return RestoreResult(
        destination,
        destination / manifest.database_file,
        artifact_roots,
        len(manifest.files),
        manifest.migration_revision,
    )


def read_manifest(source: Path) -> BackupManifest:
    try:
        raw: Any = json.loads((source / MANIFEST_NAME).read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("format_version") != BACKUP_FORMAT_VERSION:
            raise BackupError("The backup manifest version is unsupported.")
        raw_files = raw.get("files")
        raw_roots = raw.get("artifact_root_ids")
        if not isinstance(raw_files, list) or not isinstance(raw_roots, list):
            raise BackupError("The backup manifest is invalid.")
        files = tuple(
            BackupFile(
                path=_required_string(item, "path"),
                byte_count=_required_int(item, "byte_count"),
                sha256=_required_string(item, "sha256"),
                kind=_required_string(item, "kind"),
                root_id=item.get("root_id") if isinstance(item, dict) else None,
            )
            for item in raw_files
        )
        roots = tuple(
            value
            for value in raw_roots
            if isinstance(value, str) and _SAFE_ROOT_ID.fullmatch(value) is not None
        )
        if len(roots) != len(raw_roots) or len(set(roots)) != len(roots):
            raise BackupError("The backup artifact root list is invalid.")
        manifest = BackupManifest(
            _required_string(raw, "format_version"),
            _required_string(raw, "created_at"),
            raw.get("application_revision")
            if isinstance(raw.get("application_revision"), str)
            else None,
            _required_string(raw, "migration_revision"),
            _required_string(raw, "database_file"),
            roots,
            files,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        if isinstance(error, BackupError):
            raise
        raise BackupError("The backup manifest is invalid.") from error
    database_entries = tuple(item for item in manifest.files if item.kind == "database")
    if (
        manifest.database_file != DATABASE_NAME
        or len(database_entries) != 1
        or database_entries[0].path != manifest.database_file
        or database_entries[0].root_id is not None
    ):
        raise BackupError("The backup manifest database entry is invalid.")
    for item in manifest.files:
        _safe_manifest_path(item.path)
        if item.byte_count < 0 or not _valid_sha256(item.sha256):
            raise BackupError("The backup manifest contains invalid file evidence.")
        if item.kind not in {"database", "artifact"}:
            raise BackupError("The backup manifest contains an unsupported file kind.")
        if item.kind == "artifact":
            relative = _safe_manifest_path(item.path)
            if (
                item.root_id not in manifest.artifact_root_ids
                or len(relative.parts) < 3
                or relative.parts[:2] != ("artifacts", item.root_id)
            ):
                raise BackupError("The backup manifest contains an invalid artifact location.")
    if len({item.path for item in manifest.files}) != len(manifest.files):
        raise BackupError("The backup manifest contains duplicate paths.")
    return manifest


def _verify_manifest_files(source: Path, manifest: BackupManifest) -> None:
    for item in manifest.files:
        relative = _safe_manifest_path(item.path)
        candidate = source.joinpath(*relative.parts)
        if not candidate.is_file() or is_unsafe_link_path(candidate):
            raise BackupError("A required backup file is missing or unsafe.")
        byte_count, sha256 = _hash_file(candidate)
        if byte_count != item.byte_count or sha256 != item.sha256:
            raise BackupError("Backup file integrity verification failed.")


def _sqlite_backup(source: Path, destination: Path) -> None:
    source_uri = f"file:{source.as_posix()}?mode=ro"
    with (
        closing(sqlite3.connect(source_uri, uri=True)) as source_connection,
        closing(sqlite3.connect(destination)) as destination_connection,
    ):
        source_connection.backup(destination_connection)
        result = destination_connection.execute("PRAGMA integrity_check").fetchone()
        if result is None or result[0] != "ok":
            raise BackupError("The SQLite backup failed its integrity check.")


def _database_revision(database: Path) -> str | None:
    try:
        with closing(
            sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
        ) as connection:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='alembic_version'"
            ).fetchone()
            if table is None:
                return None
            row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
            return str(row[0]) if row is not None else None
    except sqlite3.Error as error:
        raise BackupError("The SQLite database cannot be inspected.") from error


def _safe_files(root: Path) -> tuple[Path, ...]:
    files: list[Path] = []
    for entry in root.rglob("*"):
        if is_unsafe_link_path(entry):
            raise BackupError("Artifact storage contains a symlink or junction.")
        if entry.is_file():
            files.append(entry)
        elif not entry.is_dir():
            raise BackupError("Artifact storage contains an unsupported filesystem entry.")
    return tuple(sorted(files, key=lambda item: item.relative_to(root).as_posix()))


def _copy_regular_file(source: Path, destination: Path) -> None:
    before = source.stat()
    if not source.is_file() or is_unsafe_link_path(source):
        raise BackupError("A source file is missing or unsafe.")
    with source.open("rb") as reader, destination.open("xb") as writer:
        shutil.copyfileobj(reader, writer, length=1024 * 1024)
        writer.flush()
        os.fsync(writer.fileno())
    after = source.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise BackupError("A source file changed during backup.")


def _manifest_file(
    path: Path, manifest_path: str, kind: str, root_id: str | None = None
) -> BackupFile:
    byte_count, sha256 = _hash_file(path)
    return BackupFile(manifest_path, byte_count, sha256, kind, root_id)


def _hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    count = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            count += len(chunk)
            digest.update(chunk)
    return count, digest.hexdigest()


def _validate_new_destination(path: Path, *, repository_root: Path) -> None:
    if not path.is_absolute():
        raise BackupError("The destination path must be absolute.")
    resolved = path.resolve(strict=False)
    repository = repository_root.resolve(strict=False)
    if resolved == repository or repository in resolved.parents:
        raise BackupError("Backup and restore destinations cannot be inside the source repository.")
    if path.exists() or path.is_symlink():
        raise BackupError("The destination already exists; restore into a new location.")
    parent = path.parent
    if not parent.is_dir() or is_unsafe_link_path(parent):
        raise BackupError("The destination parent is missing or unsafe.")


def _validate_backup_source(source: Path) -> None:
    if not source.is_absolute() or not source.is_dir() or is_unsafe_link_path(source):
        raise BackupError("The backup source is missing or unsafe.")


def _safe_manifest_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise BackupError("The backup manifest contains an unsafe path.")
    return path


def _valid_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _required_string(value: object, key: str) -> str:
    if not isinstance(value, dict) or not isinstance(value.get(key), str) or not value[key]:
        raise BackupError("The backup manifest is invalid.")
    return str(value[key])


def _required_int(value: object, key: str) -> int:
    if not isinstance(value, dict) or not isinstance(value.get(key), int):
        raise BackupError("The backup manifest is invalid.")
    return int(value[key])


def _git_revision(repository_root: Path) -> str | None:
    executable = shutil.which("git")
    if executable is None:
        return None
    try:
        result = subprocess.run(  # noqa: S603 - resolved executable and fixed arguments.
            [executable, "rev-parse", "HEAD"],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except OSError, subprocess.SubprocessError:
        return None
    revision = result.stdout.strip()
    return revision if len(revision) == 40 else None
