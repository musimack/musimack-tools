# 0039: Durable history query authority

Status: Accepted for `seo-toolkit-history-service-v1`.

## Decision

SQLite persistence is the sole historical authority. A dedicated read-only repository queries the
accepted job, run, durable execution, stage, warning, failure, summary, and artifact tables using
short-lived sessions and returns immutable DTOs. The process-local registry and caches are never
required for historical correctness.

Revision `0004_history_api` adds nullable wall-clock evidence and exercised query indexes. It does
not add duplicate job/run history tables. Older rows remain queryable with explicit unavailable
timestamps.

## Consequences

History survives API and worker restart, registry reset, payload eviction, retry, cancellation,
recovery, and artifact lifecycle changes. Durable execution and artifact services retain ownership
of their state transitions; history only projects their evidence.
