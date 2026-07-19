"""Command-line interface for explicit production operations."""

# ruff: noqa: ANN401, PLR0911, TRY003

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import sqlite3
import sys
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

import uvicorn
from alembic.script import ScriptDirectory
from sqlalchemy import URL

from musimack_tools.artifacts.repository import SQLAlchemyArtifactRepository
from musimack_tools.artifacts.service import ArtifactService
from musimack_tools.authentication.service import AuthenticationService
from musimack_tools.deployment.settings import authentication_configuration
from musimack_tools.operations.backup import (
    BackupError,
    BackupResult,
    RestoreResult,
    create_backup,
    restore_backup,
)
from musimack_tools.operations.configuration import ApplicationRole
from musimack_tools.operations.preflight import initialize_directories, run_preflight
from musimack_tools.operations.runtime import (
    BACKEND_ROOT,
    REPOSITORY_ROOT,
    create_web_app,
    load_runtime_settings,
    run_worker,
)
from musimack_tools.persistence.engine import create_persistence_runtime
from musimack_tools.persistence.migrations import (
    PERSISTENCE_HEAD_REVISION,
    alembic_configuration,
    upgrade_to_head,
)

if TYPE_CHECKING:
    from musimack_tools.operations.runtime import RuntimeSettings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Musimack production operations")
    parser.add_argument("--json", action="store_true", dest="json_output")
    commands = parser.add_subparsers(dest="command", required=True)
    preflight = commands.add_parser("preflight", help="inspect deployment readiness")
    preflight.add_argument("--allow-pending-migrations", action="store_true")
    preflight.add_argument("--role", choices=tuple(ApplicationRole), default=ApplicationRole.WEB)
    commands.add_parser("initialize", help="create configured durable directories")
    commands.add_parser("migration-status", help="inspect code and database revisions")
    commands.add_parser("migrate", help="explicitly upgrade the configured database to head")
    backup = commands.add_parser("backup", help="back up database and artifact state")
    backup.add_argument("destination", type=Path)
    backup.add_argument("--confirm-services-stopped", action="store_true")
    restore = commands.add_parser("restore", help="restore into a new isolated root")
    restore.add_argument("source", type=Path)
    restore.add_argument("destination", type=Path)
    cleanup = commands.add_parser("retention", help="run artifact retention cleanup")
    cleanup.add_argument("--apply", action="store_true")
    commands.add_parser("reconcile", help="inspect artifact metadata and files")
    bootstrap = commands.add_parser("bootstrap-admin", help="create the first administrator")
    bootstrap.add_argument("--email", required=True)
    bootstrap.add_argument("--display-name", required=True)
    commands.add_parser("web", help="run the loopback private web process")
    commands.add_parser("worker", help="run the durable worker process")
    return parser


def main(argv: list[str] | None = None) -> int:  # noqa: C901, PLR0912, PLR0915
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        settings = load_runtime_settings()
        if args.command == "preflight":
            report = run_preflight(
                settings.application,
                settings.production,
                settings.persistence,
                settings.durable,
                settings.artifacts,
                settings.operations,
                repository_root=REPOSITORY_ROOT,
                backend_root=BACKEND_ROOT,
                role=ApplicationRole(args.role),
                allow_pending_migrations=args.allow_pending_migrations,
            )
            _emit(asdict(report), json_output=args.json_output)
            return 0 if report.ready else 2
        if args.command == "initialize":
            created = initialize_directories(
                settings.persistence,
                settings.artifacts,
                repository_root=REPOSITORY_ROOT,
            )
            _emit(
                {"initialized": True, "created_count": len(created)},
                json_output=args.json_output,
            )
            return 0
        if args.command == "migration-status":
            status = migration_status(settings)
            _emit(status, json_output=args.json_output)
            return 0 if status["current"] else 2
        if args.command == "migrate":
            database = _database_path(settings)
            upgrade_to_head(
                str(URL.create("sqlite+pysqlite", database=str(database))),
                backend_root=BACKEND_ROOT,
            )
            status = migration_status(settings)
            _emit(status, json_output=args.json_output)
            return 0 if status["current"] else 2
        if args.command == "backup":
            database = _database_path(settings)
            runtime, artifacts = _artifact_service(settings)
            try:
                reconciliation = artifacts.reconcile()
                if reconciliation.failures or reconciliation.orphans or reconciliation.bounded:
                    raise BackupError(
                        "Artifact reconciliation must be clean and complete before backup."
                    )
                backup_result = create_backup(
                    database,
                    settings.artifacts.to_configuration().roots,
                    args.destination.resolve(strict=False),
                    repository_root=REPOSITORY_ROOT,
                    services_stopped=args.confirm_services_stopped,
                )
            finally:
                runtime.dispose()
            _emit(_safe_result(backup_result), json_output=args.json_output)
            return 0
        if args.command == "restore":
            restore_result = restore_backup(
                args.source.resolve(strict=False),
                args.destination.resolve(strict=False),
                repository_root=REPOSITORY_ROOT,
            )
            _emit(_safe_result(restore_result), json_output=args.json_output)
            return 0
        if args.command in {"retention", "reconcile"}:
            runtime, artifacts = _artifact_service(settings)
            try:
                lifecycle_result = (
                    artifacts.cleanup(dry_run=not args.apply)
                    if args.command == "retention"
                    else artifacts.reconcile()
                )
                _emit(asdict(lifecycle_result), json_output=args.json_output)
            finally:
                runtime.dispose()
            return 0
        if args.command == "bootstrap-admin":
            runtime = create_persistence_runtime(
                settings.persistence.to_configuration(), repository_root=REPOSITORY_ROOT
            )
            try:
                password = getpass.getpass("Administrator password: ")
                confirmation = getpass.getpass("Confirm administrator password: ")
                if password != confirmation:
                    raise RuntimeError("Administrator password confirmation did not match.")
                authentication = AuthenticationService(
                    runtime.session_factory,
                    authentication_configuration(settings.production),
                )
                user = authentication.bootstrap_administrator(
                    args.email, args.display_name, password
                )
                _emit(
                    {"bootstrapped": True, "user_id": user.user_id, "email": user.email},
                    json_output=args.json_output,
                )
            finally:
                runtime.dispose()
            return 0
        if args.command == "web":
            app = create_web_app()
            uvicorn.run(
                app,
                host=settings.operations.host,
                port=settings.operations.port,
                reload=False,
                proxy_headers=False,
                access_log=False,
                log_level=settings.application.log_level.value.casefold(),
            )
            return 0
        if args.command == "worker":
            asyncio.run(run_worker(settings))
            return 0
    except (BackupError, RuntimeError, ValueError, OSError, sqlite3.Error) as error:
        _emit(
            {"ready": False, "error": _safe_error(error)},
            json_output=args.json_output,
            error=True,
        )
        return 2
    return 2


def migration_status(settings: RuntimeSettings) -> dict[str, object]:
    database = _database_path(settings)
    script = ScriptDirectory.from_config(
        alembic_configuration("sqlite+pysqlite:///:memory:", backend_root=BACKEND_ROOT)
    )
    heads = tuple(script.get_heads())
    revision: str | None = None
    if database.exists():
        with closing(
            sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
        ) as connection:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='alembic_version'"
            ).fetchone()
            if table is not None:
                row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
                revision = str(row[0]) if row is not None else None
    return {
        "database_exists": database.exists(),
        "current_revision": revision,
        "expected_head": PERSISTENCE_HEAD_REVISION,
        "head_count": len(heads),
        "heads": heads,
        "current": revision == PERSISTENCE_HEAD_REVISION and heads == (PERSISTENCE_HEAD_REVISION,),
        "pending": revision != PERSISTENCE_HEAD_REVISION,
    }


def _artifact_service(settings: RuntimeSettings) -> tuple[Any, ArtifactService]:
    runtime = create_persistence_runtime(
        settings.persistence.to_configuration(), repository_root=REPOSITORY_ROOT
    )
    return runtime, ArtifactService(
        settings.artifacts.to_configuration(), SQLAlchemyArtifactRepository(runtime)
    )


def _database_path(settings: RuntimeSettings) -> Path:
    database = settings.persistence.database_path
    if database is None:
        raise RuntimeError("The production database path is not configured.")
    return database


def _safe_result(result: BackupResult | RestoreResult) -> dict[str, object]:
    values = asdict(result)
    safe = _json_safe(values)
    if not isinstance(safe, dict):
        raise TypeError("operation result must serialize as an object")
    return {str(key): value for key, value in safe.items()}


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    return value


def _safe_error(error: Exception) -> str:
    if isinstance(error, BackupError):
        return str(error)
    if isinstance(error, RuntimeError) and str(error).startswith(("Production", "Administrator")):
        return str(error)
    return "Production operation failed; review configuration and service logs."


def _emit(
    payload: dict[str, object],
    *,
    json_output: bool,
    error: bool = False,
) -> None:
    stream = sys.stderr if error else sys.stdout
    if json_output:
        print(json.dumps(_json_safe(payload), sort_keys=True), file=stream)
        return
    for key, value in _json_safe(payload).items():
        print(f"{key}: {value}", file=stream)


if __name__ == "__main__":
    raise SystemExit(main())
