# ADR 0038: Explicit artifact retention, cleanup, and reconciliation

## Decision

Expiration is persisted policy evidence, not file modification time. Retention holds prevent
expiration and deletion. Cleanup uses deterministic bounded batches, rechecks safety outside short
transactions, preserves metadata, and is idempotent for missing files.

Reconciliation is startup-disabled by default and scans only the bounded managed layout. It verifies
registered records and reports unregistered files as orphans without automatically registering or
deleting them. Both operations persist safe result evidence.

## Consequences

No scheduler or cleanup daemon is introduced. Operators invoke lifecycle operations explicitly or
opt into startup reconciliation.
