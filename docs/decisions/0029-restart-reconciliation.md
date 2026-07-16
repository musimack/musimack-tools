# ADR 0029: Restart reconciliation

## Status

Accepted for `seo-toolkit-persistence-v1`.

## Decision

Before a persistence-enabled production application accepts job submissions, reconcile durable jobs
left in non-terminal states by a previous process. Jobs in accepted, queued, starting, running, or
cancelling states become failed or partially completed with the stable interruption code
`process_restart_interrupted`. Existing terminal records are preserved.

Reconciliation is deterministic, bounded to stored rows, and never automatically resumes work.
The highest recorded attempt per run is recovered so a new submission uses a monotonically greater
attempt number. Terminal metadata may be loaded into the in-memory registry without reconstructing
large results or artifacts.

## Consequences

Restart state is explainable and stale active jobs cannot masquerade as running work. The database
does not become an execution queue, and interrupted work requires an explicit new submission.
Distributed leases, worker heartbeats, process fencing, and automatic retry scheduling remain
deferred.
