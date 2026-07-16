"""Cross-platform safe relative-path and configured-root checks."""

from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath, PureWindowsPath

from musimack_tools.domain.artifacts import ArtifactError, ArtifactFailureCode
from musimack_tools.sitemap.publication import is_unsafe_link_path

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def validate_filename(filename: str) -> str:
    """Return one header-safe filename or raise a typed path error."""
    if (
        not filename
        or filename in {".", ".."}
        or "/" in filename
        or "\\" in filename
        or ":" in filename
        or _CONTROL.search(filename)
        or filename[-1] in {" ", "."}
        or filename.split(".", 1)[0].upper() in _RESERVED
    ):
        raise ArtifactError(ArtifactFailureCode.PATH_INVALID, "Artifact filename is invalid.")
    return filename


def validate_relative_path(value: str) -> str:
    """Normalize a portable relative path without touching the filesystem."""
    if not value or _CONTROL.search(value) or "\\" in value or "//" in value:
        raise ArtifactError(ArtifactFailureCode.PATH_INVALID, "Artifact path is invalid.")
    windows = PureWindowsPath(value)
    if windows.is_absolute() or windows.drive or value.startswith(("//", "\\")):
        raise ArtifactError(ArtifactFailureCode.PATH_INVALID, "Artifact path is invalid.")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ArtifactError(ArtifactFailureCode.PATH_INVALID, "Artifact path is invalid.")
    for part in path.parts:
        validate_filename(part)
    return path.as_posix()


def resolve_artifact_path(root: Path, relative_path: str) -> Path:
    """Resolve beneath a safe root and reject link/junction components."""
    normalized = validate_relative_path(relative_path)
    _reject_unsafe_components(root)
    candidate = root.joinpath(*PurePosixPath(normalized).parts)
    resolved_root = root.resolve(strict=False)
    resolved = candidate.resolve(strict=False)
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ArtifactError(
            ArtifactFailureCode.PATH_OUTSIDE_ROOT, "Artifact path is outside its root."
        )
    _reject_unsafe_components(candidate)
    return candidate


def check_root(root: Path, *, require_writable: bool) -> tuple[bool, bool]:
    _reject_unsafe_components(root)
    if not root.exists() or not root.is_dir():
        raise ArtifactError(ArtifactFailureCode.ROOT_UNAVAILABLE, "Artifact root is unavailable.")
    readable = os.access(root, os.R_OK)
    writable = os.access(root, os.W_OK)
    if not readable:
        raise ArtifactError(ArtifactFailureCode.ROOT_UNAVAILABLE, "Artifact root is unreadable.")
    if require_writable and not writable:
        raise ArtifactError(ArtifactFailureCode.ROOT_NOT_WRITABLE, "Artifact root is not writable.")
    return readable, writable


def _reject_unsafe_components(path: Path) -> None:
    current = path
    existing: list[Path] = []
    while True:
        if current.exists() or current.is_symlink():
            existing.append(current)
        if current.parent == current:
            break
        current = current.parent
    for component in existing:
        if not is_unsafe_link_path(component):
            continue
        if component.is_symlink():
            raise ArtifactError(
                ArtifactFailureCode.SYMLINK_BLOCKED, "Artifact path contains a symbolic link."
            )
        raise ArtifactError(
            ArtifactFailureCode.JUNCTION_BLOCKED, "Artifact path contains a junction."
        )
