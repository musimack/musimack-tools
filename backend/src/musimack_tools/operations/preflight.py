"""Read-only production deployment preflight with stable machine-readable evidence."""

# ruff: noqa: E501

from __future__ import annotations

import os
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from alembic.script import ScriptDirectory

from musimack_tools.artifacts.path_safety import check_root
from musimack_tools.operations.configuration import (
    ApplicationRole,
    ConfigurationIssue,
    validate_production_configuration,
)
from musimack_tools.persistence.migrations import (
    PERSISTENCE_HEAD_REVISION,
    alembic_configuration,
)
from musimack_tools.persistence.path_safety import validate_database_path
from musimack_tools.sitemap.publication import is_unsafe_link_path

if TYPE_CHECKING:
    from musimack_tools.core.config import Settings
    from musimack_tools.deployment.artifacts import ArtifactStorageSettings
    from musimack_tools.deployment.durable import DurableExecutionSettings
    from musimack_tools.deployment.persistence import PersistenceSettings
    from musimack_tools.deployment.settings import ProductionSettings
    from musimack_tools.operations.configuration import OperationsSettings


class PreflightStatus(StrEnum):
    PASS = "pass"  # noqa: S105 - status label, not a credential.
    FAIL = "fail"
    WARNING = "warning"


class PreflightCode(StrEnum):
    CONFIGURATION = "production_configuration"
    DATABASE_PATH = "database_path"
    DATABASE_PARENT = "database_parent"
    DATABASE_WRITABLE = "database_parent_writable"
    DATABASE_CONNECTIVITY = "database_connectivity"
    MIGRATION_HEAD = "migration_head"
    MIGRATION_CURRENT = "migration_current"
    ARTIFACT_ROOT = "artifact_root"
    ARTIFACT_WRITABLE = "artifact_root_writable"
    FRONTEND_BUILD = "frontend_build"
    GENERATED_ARTIFACTS = "production_path_artifacts"


@dataclass(frozen=True, slots=True)
class PreflightCheck:
    code: str
    status: PreflightStatus
    description: str
    remediation: str | None = None
    context: tuple[tuple[str, str | int | bool], ...] = ()


@dataclass(frozen=True, slots=True)
class PreflightReport:
    ready: bool
    checks: tuple[PreflightCheck, ...]
    operations_version: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def run_preflight(  # noqa: C901, PLR0913
    application: Settings,
    production: ProductionSettings,
    persistence: PersistenceSettings,
    durable: DurableExecutionSettings,
    artifacts: ArtifactStorageSettings,
    operations: OperationsSettings,
    *,
    repository_root: Path,
    backend_root: Path,
    role: ApplicationRole | None = None,
    allow_pending_migrations: bool = False,
) -> PreflightReport:
    """Inspect production readiness without DNS, public network, or persistent writes."""
    checks: list[PreflightCheck] = []
    configuration_issues = validate_production_configuration(
        application,
        production,
        persistence,
        durable,
        artifacts,
        operations,
        repository_root=repository_root,
        role=role,
    )
    if configuration_issues:
        checks.extend(_configuration_check(issue) for issue in configuration_issues)
    else:
        checks.append(
            PreflightCheck(
                PreflightCode.CONFIGURATION,
                PreflightStatus.PASS,
                "Production settings satisfy the operations contract.",
            )
        )

    database = persistence.database_path
    if database is not None:
        try:
            validate_database_path(database, repository_root=repository_root)
            checks.append(
                PreflightCheck(
                    PreflightCode.DATABASE_PATH,
                    PreflightStatus.PASS,
                    "The configured database path passes structural safety checks.",
                )
            )
        except OSError, ValueError:
            checks.append(
                PreflightCheck(
                    PreflightCode.DATABASE_PATH,
                    PreflightStatus.FAIL,
                    "The configured database path is unsafe.",
                    "Use a local absolute path without symlink, junction, device, or repository components.",
                )
            )
        parent = database.parent
        if not parent.exists():
            checks.append(
                PreflightCheck(
                    PreflightCode.DATABASE_PARENT,
                    PreflightStatus.FAIL,
                    "The database parent directory does not exist.",
                    "Create it explicitly with the operations initialize command and set restrictive permissions.",
                )
            )
        elif not parent.is_dir():
            checks.append(
                PreflightCheck(
                    PreflightCode.DATABASE_PARENT,
                    PreflightStatus.FAIL,
                    "The database parent path is not a directory.",
                    "Choose a valid durable database directory.",
                )
            )
        else:
            checks.append(_writable_probe(parent, PreflightCode.DATABASE_WRITABLE))
        checks.append(_database_connectivity(database, allow_missing=allow_pending_migrations))

    checks.append(_migration_head_check(backend_root))
    if database is not None:
        checks.append(_migration_current_check(database, allow_pending=allow_pending_migrations))

    try:
        artifact_configuration = artifacts.to_configuration()
    except ValueError:
        artifact_configuration = None
    if artifact_configuration is not None:
        for root in artifact_configuration.roots:
            try:
                check_root(root.path, require_writable=False)
                checks.append(
                    PreflightCheck(
                        PreflightCode.ARTIFACT_ROOT,
                        PreflightStatus.PASS,
                        "An artifact root passes structural safety checks.",
                        context=(("root_id", root.root_id),),
                    )
                )
                checks.append(
                    _writable_probe(
                        root.path,
                        PreflightCode.ARTIFACT_WRITABLE,
                        context=(("root_id", root.root_id),),
                    )
                )
                generated = _generated_entries(root.path)
                checks.append(
                    PreflightCheck(
                        PreflightCode.GENERATED_ARTIFACTS,
                        PreflightStatus.FAIL if generated else PreflightStatus.PASS,
                        (
                            "Development or test artifacts are present in a production artifact root."
                            if generated
                            else "No development or test artifacts were found in the artifact root."
                        ),
                        (
                            "Remove the listed generated entries after confirming they are not production state."
                            if generated
                            else None
                        ),
                        (("root_id", root.root_id), ("matches", len(generated))),
                    )
                )
            except OSError, ValueError, RuntimeError:
                checks.append(
                    PreflightCheck(
                        PreflightCode.ARTIFACT_ROOT,
                        PreflightStatus.FAIL,
                        "An artifact root is unavailable or unsafe.",
                        "Create a local durable directory without symlink or junction components.",
                        (("root_id", root.root_id),),
                    )
                )

    frontend = operations.frontend_build_path
    frontend_ready = (
        frontend is not None
        and frontend.is_dir()
        and (frontend / "index.html").is_file()
        and not is_unsafe_link_path(frontend)
        and not is_unsafe_link_path(frontend / "index.html")
    )
    checks.append(
        PreflightCheck(
            PreflightCode.FRONTEND_BUILD,
            PreflightStatus.PASS if frontend_ready else PreflightStatus.FAIL,
            (
                "The frontend production build is present."
                if frontend_ready
                else "The frontend production build is missing or unsafe."
            ),
            None if frontend_ready else "Run npm run build and configure its absolute dist path.",
        )
    )
    ready = not any(check.status is PreflightStatus.FAIL for check in checks)
    return PreflightReport(ready, tuple(checks), operations.operations_version)


def initialize_directories(
    persistence: PersistenceSettings,
    artifacts: ArtifactStorageSettings,
    *,
    repository_root: Path,
) -> tuple[Path, ...]:
    """Explicitly create only configured database-parent and artifact-root directories."""
    created: list[Path] = []
    if persistence.database_path is not None:
        validate_database_path(persistence.database_path, repository_root=repository_root)
        parent = persistence.database_path.parent
        if not parent.exists():
            parent.mkdir(parents=True, exist_ok=False)
            created.append(parent)
    configuration = artifacts.to_configuration()
    for root in configuration.roots:
        if root.path.exists():
            check_root(root.path, require_writable=True)
            continue
        root.path.mkdir(parents=True, exist_ok=False)
        check_root(root.path, require_writable=True)
        created.append(root.path)
    return tuple(created)


def _configuration_check(issue: ConfigurationIssue) -> PreflightCheck:
    return PreflightCheck(
        f"{PreflightCode.CONFIGURATION}.{issue.code}",
        PreflightStatus.FAIL,
        issue.description,
        issue.remediation,
        (("setting", issue.setting),),
    )


def _writable_probe(
    directory: Path,
    code: PreflightCode,
    *,
    context: tuple[tuple[str, str | int | bool], ...] = (),
) -> PreflightCheck:
    try:
        descriptor, raw_path = tempfile.mkstemp(prefix=".musimack-write-probe-", dir=directory)
        os.close(descriptor)
        Path(raw_path).unlink()
    except OSError:
        return PreflightCheck(
            code,
            PreflightStatus.FAIL,
            "The configured directory is not writable by the current process.",
            "Grant the service identity read/write access to this directory.",
            context,
        )
    return PreflightCheck(
        code,
        PreflightStatus.PASS,
        "A temporary write-and-remove probe succeeded.",
        context=context,
    )


def _database_connectivity(database: Path, *, allow_missing: bool) -> PreflightCheck:
    if not database.exists():
        return PreflightCheck(
            PreflightCode.DATABASE_CONNECTIVITY,
            PreflightStatus.WARNING if allow_missing else PreflightStatus.FAIL,
            "The database does not exist yet.",
            "Apply migrations explicitly before starting web or worker processes.",
        )
    try:
        with closing(
            sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
        ) as connection:
            connection.execute("SELECT 1").fetchone()
    except sqlite3.Error:
        return PreflightCheck(
            PreflightCode.DATABASE_CONNECTIVITY,
            PreflightStatus.FAIL,
            "The database cannot be opened read-only.",
            "Check file permissions, integrity, and whether another process holds an incompatible lock.",
        )
    return PreflightCheck(
        PreflightCode.DATABASE_CONNECTIVITY,
        PreflightStatus.PASS,
        "The database is reachable in read-only mode.",
    )


def _migration_head_check(backend_root: Path) -> PreflightCheck:
    try:
        script = ScriptDirectory.from_config(
            alembic_configuration("sqlite+pysqlite:///:memory:", backend_root=backend_root)
        )
        heads = tuple(script.get_heads())
    except Exception:  # noqa: BLE001 - report a bounded preflight failure.
        heads = ()
    ready = heads == (PERSISTENCE_HEAD_REVISION,)
    return PreflightCheck(
        PreflightCode.MIGRATION_HEAD,
        PreflightStatus.PASS if ready else PreflightStatus.FAIL,
        "The migration graph has exactly one expected head."
        if ready
        else "The migration graph is divergent or incompatible.",
        None if ready else "Resolve the migration graph before deployment.",
        (("head_count", len(heads)), ("expected_head", PERSISTENCE_HEAD_REVISION)),
    )


def _migration_current_check(database: Path, *, allow_pending: bool) -> PreflightCheck:
    revision: str | None = None
    if database.exists():
        try:
            with closing(
                sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
            ) as connection:
                table = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='alembic_version'"
                ).fetchone()
                if table is not None:
                    row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
                    revision = str(row[0]) if row is not None else None
        except sqlite3.Error:
            pass
    ready = revision == PERSISTENCE_HEAD_REVISION
    pending = revision is None or _known_earlier_revision(revision)
    status = (
        PreflightStatus.PASS
        if ready
        else PreflightStatus.WARNING
        if allow_pending and pending
        else PreflightStatus.FAIL
    )
    return PreflightCheck(
        PreflightCode.MIGRATION_CURRENT,
        status,
        (
            "The database is at the expected migration head."
            if ready
            else "The database has pending migrations."
            if pending
            else "The database revision is ahead of or incompatible with this code."
        ),
        None if ready else "Apply migrations explicitly after taking a verified backup.",
        (("expected_head", PERSISTENCE_HEAD_REVISION), ("current_revision", revision or "none")),
    )


def _known_earlier_revision(revision: str) -> bool:
    prefix = revision.split("_", 1)[0]
    expected = PERSISTENCE_HEAD_REVISION.split("_", 1)[0]
    return prefix.isdigit() and expected.isdigit() and int(prefix) < int(expected)


def _generated_entries(root: Path) -> tuple[Path, ...]:
    maximum_matches = 100
    blocked = {".pytest_cache", ".mypy_cache", ".ruff_cache", "__pycache__", "node_modules", "dist"}
    found: list[Path] = []
    for entry in root.rglob("*"):
        if entry.name in blocked or entry.suffix in {".pyc", ".pyo", ".tsbuildinfo"}:
            found.append(entry)
            if len(found) >= maximum_matches:
                break
    return tuple(found)
