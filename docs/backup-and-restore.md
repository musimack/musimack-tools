# Backup and restore

Backups are offline with respect to application writers: the operator must stop web and worker and pass `--confirm-services-stopped`. The implementation then uses SQLite's online backup API to create a transactionally consistent database copy and runs `PRAGMA integrity_check`. Artifact files are copied without following symlinks or junctions and are rejected if their identity, size, or content changes during the copy.

Each backup is first written to a private temporary sibling and renamed only after completion. `manifest.json` uses format `musimack-backup-v1` and records UTC time, the available Git revision, migration revision, opaque artifact root IDs, relative file names, byte counts, SHA-256 hashes, and file kinds. It does not store source absolute paths or credentials. The database contains artifact metadata and the backup contains the corresponding artifact files; run reconciliation before taking the backup and resolve any failure or orphan report.

Create a backup only in a new absolute directory outside the checkout, database, and artifact roots:

```powershell
.\.venv\Scripts\python.exe -m musimack_tools.operations --json reconcile
.\.venv\Scripts\python.exe -m musimack_tools.operations --json backup D:\MusimackBackups\2026-07-18 --confirm-services-stopped
```

Keep backup storage inaccessible to the web and worker identities except during the controlled operation. Apply filesystem encryption, access control, retention, and off-host replication according to the operator's environment; the repository does not select a backup vendor.

## Restore and validation

Restore verifies the manifest schema and version, every path, file size and SHA-256, the recorded migration, and the database's actual Alembic revision. It refuses missing/altered files, unsafe source entries, incompatible revisions, destinations inside the checkout, missing or unsafe destination parents, and every existing destination. There is intentionally no force/replace mode.

```powershell
.\.venv\Scripts\python.exe -m musimack_tools.operations --json restore D:\MusimackBackups\2026-07-18 D:\MusimackRestore\validation-2026-07-18
```

The result contains `database.sqlite3` and one directory per artifact root under `artifacts`. Configure a new validation environment to those paths, run `migration-status`, reconciliation, and preflight, then start worker and web and validate health, readiness, login, history, and artifact downloads. The source backup is never modified. Failed restore staging is removed and no partial destination is published.

For disaster recovery or rollback, restore into new paths and switch configuration only while services and ingress are stopped. Preserve the old and failed roots. If the backup migration is not the exact code head, use the application version recorded for the backup or obtain human migration guidance; do not force the manifest, rewrite hashes, manually change Alembic state, or run automatic downgrades.
