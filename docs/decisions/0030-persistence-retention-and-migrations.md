# ADR 0030: Persistence retention and migrations

## Status

Accepted for `seo-toolkit-persistence-v1` and `seo-toolkit-database-schema-v1`.

## Decision

Manage schema changes with Alembic. Revision `0001_persistence` (`create persistence foundation`)
contains a frozen initial schema rather than importing mutable ORM metadata. Migration commands
must receive an explicit database URL; `alembic.ini` has no repository-relative fallback. Pending
migrations make persistence not ready unless explicit startup composition is authorized to migrate.

Retention uses validated upper bounds for terminal jobs and per-parent progress, warning, failure,
summary, and artifact metadata. Cleanup is explicit and deterministic, removes dependent rows in a
defined sequence, and may retain bounded metadata for evicted or interrupted jobs. It never deletes
published files or stores their contents.

## Consequences

Schema evolution and cleanup are reviewable operations rather than import-time side effects.
Operators must configure database paths, choose whether startup migration is permitted, and arrange
backups before destructive administration. Scheduled maintenance, backup/restore tooling, database
vacuum policy, retention by age, and PostgreSQL migrations remain deferred.
