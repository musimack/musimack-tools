# ADR 0057: Page evidence retention and reconciliation

## Status

Accepted.

## Decision

Page evidence retention is independent from in-memory payload eviction. The default retention is
180 days. Holds and releases are explicit. Cleanup is explicitly invoked, dry-run capable, ordered,
bounded to 500 records by default, idempotent, and prohibited for active runs or held evidence.
Summary metadata may remain as `metadata_only` after page deletion.

Reconciliation is disabled as an automatic destructive action. Explicit bounded reconciliation
reports count, warning, version, and retention inconsistencies without re-fetching, reparsing, or
silently repairing data.

## Consequences

Operational cleanup cannot become a scheduler and downstream consumers can distinguish retained,
expired, and metadata-only evidence.
