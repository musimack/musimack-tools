# Production operations runbook

All commands run from the repository root with the production environment loaded. The examples use the repository virtual environment and are supervisor-neutral.

```powershell
# Create only configured database/artifact parent directories.
.\.venv\Scripts\python.exe -m musimack_tools.operations initialize

# Read-only deployment checks; JSON is suitable for automation.
.\.venv\Scripts\python.exe -m musimack_tools.operations --json preflight --role web
.\.venv\Scripts\python.exe -m musimack_tools.operations --json preflight --role worker

# A new database may be inspected before the explicit migration step.
.\.venv\Scripts\python.exe -m musimack_tools.operations --json preflight --allow-pending-migrations --role web
.\.venv\Scripts\python.exe -m musimack_tools.operations --json migration-status
.\.venv\Scripts\python.exe -m musimack_tools.operations --json migrate

# Seed the first administrator interactively; passwords are not command arguments.
.\.venv\Scripts\python.exe -m musimack_tools.operations bootstrap-admin --email admin@example.invalid --display-name "Initial administrator"

# Run as separate supervised processes.
.\.venv\Scripts\python.exe -m musimack_tools.operations web
.\.venv\Scripts\python.exe -m musimack_tools.operations worker
```

Health is the minimal unauthenticated `GET http://127.0.0.1:8000/api/health`. Readiness is the existing authenticated `GET /api/internal/v1/readiness`; it requires an authorized session or compatible bearer mode and reports only typed states and non-sensitive descriptions. A non-ready dependency returns 503. The default application gains no readiness or product route.

The web command disables reload, Uvicorn proxy-header interpretation, and Uvicorn access logs; the existing request middleware supplies bounded correlation IDs and secret-free access logging. The worker registers durably, recovers stale work at startup when enabled, heartbeats its leases, cooperatively cancels on termination, and uses bounded shutdown. A supervisor should allow at least `MUSIMACK_OPERATIONS_SHUTDOWN_TIMEOUT_SECONDS` before forcing termination. Forced termination is recoverable after lease expiry but may delay the job.

## Maintenance commands

```powershell
# Stop web and worker first; backup refuses missing confirmation.
.\.venv\Scripts\python.exe -m musimack_tools.operations --json backup D:\MusimackBackups\2026-07-18 --confirm-services-stopped

# Restore always targets a new, empty path outside the checkout.
.\.venv\Scripts\python.exe -m musimack_tools.operations --json restore D:\MusimackBackups\2026-07-18 D:\MusimackRestore\validation-2026-07-18

# Reconciliation is non-destructive. Retention defaults to dry-run.
.\.venv\Scripts\python.exe -m musimack_tools.operations --json reconcile
.\.venv\Scripts\python.exe -m musimack_tools.operations --json retention
.\.venv\Scripts\python.exe -m musimack_tools.operations --json retention --apply
```

Before backup, run reconciliation and resolve missing, corrupt, unsafe, bounded, or orphaned evidence. Applied retention uses the existing lifecycle protections and never performs unrelated filesystem deletion.

## Troubleshooting

- `configuration_invalid`: correct every named environment setting; values and credentials are intentionally redacted.
- `database_parent` or `artifact_parent`: run `initialize` only after confirming the configured absolute locations.
- `database_connectivity`: confirm the file exists after migration, service identity permissions, and that no restore or offline maintenance holds it.
- `migration_head` or `migration_current`: stop services, inspect `migration-status`, confirm one code head (`0013_website_migration_qa`), back up, and run the explicit migration. An unknown/ahead revision requires the matching application version or human recovery; do not edit `alembic_version`.
- `artifact_safety` or `artifact_writable`: remove symlinks/junctions from the managed path and correct ownership/permissions. Do not relax path checks.
- `frontend_build`: produce a fresh Vite build and point to the directory containing `index.html`.
- Readiness database/migration/artifact failure: keep ingress disabled and repair the failing dependency. Worker failure requires the configured worker identity to register and heartbeat as ready.
- Authentication failures: verify mode, secure HTTPS origin, cookie flags, user status/role, and proxy/network allowlists. Never log or echo bearer credentials or passwords.

Preflight performs no DNS or public-network lookup. It probes only configured local files, SQLite, migration scripts, and the frontend build. Its failure exit code is 2. Operational failures are intentionally generic when the underlying exception could contain sensitive context.
