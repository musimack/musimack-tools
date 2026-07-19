"""Repository-native CI audits with no external service dependency."""

from __future__ import annotations

import argparse
import importlib
import json
import pkgutil
import re
import shutil
import subprocess
import sys
import tempfile
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from alembic.script import ScriptDirectory
from packaging.requirements import Requirement
from sqlalchemy import create_engine

import musimack_tools
from musimack_tools.persistence.migrations import (
    PERSISTENCE_HEAD_REVISION,
    STRUCTURED_DATA_AUDIT_REVISION,
    alembic_configuration,
    current_revision,
    upgrade_to_head,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

_APPROVED_ACTIONS = {
    "actions/checkout": "9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0",
    "actions/setup-python": "ece7cb06caefa5fff74198d8649806c4678c61a1",
    "actions/setup-node": "820762786026740c76f36085b0efc47a31fe5020",
    "actions/upload-artifact": "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
}
_USES_PATTERN = re.compile(r"^\s*-?\s*uses:\s*([^@\s]+)@([^\s#]+)", re.MULTILINE)
_SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"AKIA[0-9A-Z]{16}"),
    re.compile(rb"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(rb"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(rb"Musimack-(?:local|operator|viewer)-review-2026!"),
)
_PROHIBITED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
    "playwright-report",
    "test-results",
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
    ".sqlite",
    ".sqlite3",
    ".trace",
}
_MAXIMUM_SCAN_BYTES = 2 * 1024 * 1024


class CiAuditError(RuntimeError):
    """A bounded CI policy failure."""


def compare_python_lock(requirements_lock: Path) -> tuple[int, tuple[str, ...]]:
    """Compare every exact locked requirement with installed metadata."""

    requirements = tuple(
        Requirement(line.strip())
        for line in requirements_lock.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    differences: list[str] = []
    for requirement in requirements:
        try:
            installed = version(requirement.name)
        except PackageNotFoundError:
            differences.append(f"{requirement.name}:missing")
            continue
        if installed not in requirement.specifier:
            differences.append(f"{requirement.name}:{installed}!{requirement.specifier}")
    return len(requirements), tuple(differences)


def audit_imports() -> tuple[int, tuple[str, ...]]:
    """Import all package modules except executable ``__main__`` modules."""

    names = tuple(
        module.name
        for module in pkgutil.walk_packages(musimack_tools.__path__, musimack_tools.__name__ + ".")
        if not module.name.endswith(".__main__")
    )
    failures: list[str] = []
    for name in names:
        try:
            importlib.import_module(name)
        except Exception as error:  # noqa: BLE001 - audit records arbitrary import failures.
            failures.append(f"{name}:{type(error).__name__}")
    return len(names), tuple(failures)


def audit_migrations(backend_root: Path) -> dict[str, object]:
    """Validate the graph and upgrade an empty temporary database."""

    configuration = alembic_configuration("sqlite+pysqlite:///:memory:", backend_root=backend_root)
    scripts = ScriptDirectory.from_config(configuration)
    heads = tuple(scripts.get_heads())
    if heads != (PERSISTENCE_HEAD_REVISION,):
        raise CiAuditError("migration_heads_invalid")
    head = scripts.get_revision(PERSISTENCE_HEAD_REVISION)
    if head is None or head.down_revision != STRUCTURED_DATA_AUDIT_REVISION:
        raise CiAuditError("migration_parent_invalid")
    with tempfile.TemporaryDirectory(prefix="musimack-migration-audit-") as temporary:
        database = Path(temporary) / "fresh.sqlite3"
        database_url = f"sqlite+pysqlite:///{database.as_posix()}"
        upgrade_to_head(database_url, backend_root=backend_root)
        engine = create_engine(database_url)
        try:
            revision = current_revision(engine)
        finally:
            engine.dispose()
        if revision != PERSISTENCE_HEAD_REVISION:
            raise CiAuditError("migration_upgrade_invalid")
    return {
        "head_count": len(heads),
        "head": heads[0],
        "parent": head.down_revision,
        "empty_database_upgrade": "passed",
    }


def audit_workflows(repository_root: Path) -> dict[str, object]:  # noqa: C901
    """Enforce structural workflow security without a YAML dependency."""

    workflow_root = repository_root / ".github" / "workflows"
    paths = tuple(sorted(workflow_root.glob("*.yml")))
    expected = {"ci.yml", "release-candidate.yml"}
    if {path.name for path in paths} != expected:
        raise CiAuditError("workflow_set_invalid")
    references: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        if "\t" in text or "pull_request_target:" in text:
            raise CiAuditError("workflow_unsafe_trigger")
        if "permissions:\n  contents: read" not in text:
            raise CiAuditError("workflow_permissions_invalid")
        if "timeout-minutes:" not in text or "concurrency:" not in text:
            raise CiAuditError("workflow_bounds_missing")
        if re.search(r"\b(?:write-all|contents:\s*write|id-token:\s*write)\b", text):
            raise CiAuditError("workflow_write_permission")
        if re.search(r"\b(?:curl|wget|Invoke-WebRequest|eval)\b", text):
            raise CiAuditError("workflow_arbitrary_download")
        for owner_and_name, reference in _USES_PATTERN.findall(text):
            expected_sha = _APPROVED_ACTIONS.get(owner_and_name)
            if expected_sha is None or reference != expected_sha:
                raise CiAuditError("workflow_action_reference_invalid")
            references.append(f"{owner_and_name}@{reference}")
    release_text = (workflow_root / "release-candidate.yml").read_text(encoding="utf-8")
    for prohibited in ("git tag", "gh release", "git push", "deployment", "environment:"):
        if prohibited in release_text.casefold():
            raise CiAuditError("release_workflow_publication_behavior")
    if "needs: validate-input" not in release_text or "retention-days:" not in release_text:
        raise CiAuditError("release_workflow_gate_missing")
    return {"workflows": len(paths), "action_references": sorted(references)}


def audit_repository(repository_root: Path, *, allowed: Sequence[str] = ()) -> dict[str, int]:
    """Scan non-ignored repository files for secrets and prohibited artifacts."""

    root = repository_root.resolve(strict=True)
    allowed_paths = tuple(PurePosixPath(value) for value in allowed)
    prohibited: list[str] = []
    secret_hits: list[str] = []
    for path in root.rglob("*"):
        relative = PurePosixPath(path.relative_to(root).as_posix())
        if _ignored(relative, allowed_paths):
            continue
        if path.is_dir():
            continue
        if relative.suffix.casefold() in _PROHIBITED_SUFFIXES:
            prohibited.append(relative.as_posix())
            continue
        try:
            if path.stat().st_size > _MAXIMUM_SCAN_BYTES:
                continue
            content = path.read_bytes()
        except OSError as error:
            raise CiAuditError("repository_scan_failed") from error
        if any(pattern.search(content) for pattern in _SECRET_PATTERNS):
            secret_hits.append(relative.as_posix())
    if prohibited:
        raise CiAuditError("prohibited_artifacts:" + ",".join(sorted(prohibited)))
    if secret_hits:
        raise CiAuditError("secret_matches:" + ",".join(sorted(secret_hits)))
    return {"prohibited_artifacts": 0, "secret_matches": 0}


def _ignored(path: PurePosixPath, allowed: Sequence[PurePosixPath]) -> bool:
    if any(path == item or path.is_relative_to(item) for item in allowed):
        return False
    return bool(_PROHIBITED_PARTS.intersection(path.parts))


def _git_diff_check(repository_root: Path) -> None:
    git = shutil.which("git")
    if git is None:
        raise CiAuditError("git_unavailable")
    completed = subprocess.run(  # noqa: S603 - resolved executable and fixed arguments.
        (git, "diff", "--check"),
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode:
        raise CiAuditError("git_diff_check_failed")


def _require_empty(values: Sequence[str], code: str) -> None:
    if values:
        raise CiAuditError(code)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("all", "imports", "lock", "migrations", "repository", "workflows")
    )
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--allow", action="append", default=[])
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one or all CI audits and emit bounded JSON."""

    args = _parser().parse_args(argv)
    root = args.repository_root.resolve(strict=True)
    results: dict[str, object] = {}
    try:
        if args.command in {"all", "lock"}:
            count, differences = compare_python_lock(root / "backend/requirements.lock")
            _require_empty(differences, "python_lock_mismatch")
            results["lock"] = {"packages": count, "differences": 0}
        if args.command in {"all", "imports"}:
            count, failures = audit_imports()
            _require_empty(failures, "import_audit_failed")
            results["imports"] = {"modules": count, "failures": 0}
        if args.command in {"all", "migrations"}:
            results["migrations"] = audit_migrations(root / "backend")
        if args.command in {"all", "repository"}:
            results["repository"] = audit_repository(root, allowed=args.allow)
        if args.command in {"all", "workflows"}:
            results["workflows"] = audit_workflows(root)
        if args.command == "all":
            _git_diff_check(root)
            results["git_diff_check"] = "passed"
    except CiAuditError as error:
        sys.stderr.write(f"{error}\n")
        return 2
    sys.stdout.write(json.dumps(results, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
