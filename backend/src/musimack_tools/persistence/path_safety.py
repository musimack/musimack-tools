"""Filesystem validation for explicitly configured SQLite databases."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

_RELATIVE_PATH = "database path must be absolute"
_UNSUPPORTED_PATH = "UNC and device database paths are not supported"
_PATH_IS_DIRECTORY = "database path cannot be a directory"
_PARENT_IS_FILE = "database parent must be a directory"
_GIT_PATH = "database path cannot be inside .git"
_MISSING_PARENT = "database parent does not exist"
_LINKED_PATH = "database path contains a symlink or junction"


def validate_database_path(path: Path, *, repository_root: Path | None = None) -> None:
    """Validate without creating a directory or database file."""
    if not path.is_absolute():
        raise ValueError(_RELATIVE_PATH)
    raw = str(path)
    if raw.startswith(("\\\\", "//", "\\\\?\\", "\\\\.\\")):
        raise ValueError(_UNSUPPORTED_PATH)
    if path.is_symlink() or (os.name == "nt" and path.is_junction()):
        raise ValueError(_LINKED_PATH)
    if path.exists() and path.is_dir():
        raise ValueError(_PATH_IS_DIRECTORY)
    parent = path.parent
    if parent.exists() and not parent.is_dir():
        raise ValueError(_PARENT_IS_FILE)
    if repository_root is not None:
        git_root = (repository_root / ".git").resolve(strict=False)
        resolved = path.resolve(strict=False)
        if resolved == git_root or git_root in resolved.parents:
            raise ValueError(_GIT_PATH)
    _reject_linked_ancestors(parent)


def prepare_database_parent(
    path: Path,
    *,
    create_parent: bool,
    repository_root: Path | None = None,
) -> None:
    """Validate and optionally create the explicit parent directory."""
    validate_database_path(path, repository_root=repository_root)
    parent = path.parent
    if parent.exists():
        return
    if not create_parent:
        raise ValueError(_MISSING_PARENT)
    parent.mkdir(parents=True, exist_ok=False)
    _reject_linked_ancestors(parent)


def _reject_linked_ancestors(path: Path) -> None:
    current = path
    existing: list[Path] = []
    while True:
        if current.exists():
            existing.append(current)
        if current.parent == current:
            break
        current = current.parent
    for item in existing:
        if item.is_symlink() or (os.name == "nt" and item.is_junction()):
            raise ValueError(_LINKED_PATH)
