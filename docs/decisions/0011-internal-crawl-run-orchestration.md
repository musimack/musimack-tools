# ADR 0011: Internal crawl-run orchestration

## Status

Accepted

## Decision

Add a framework-independent, in-process application service that composes the accepted crawl,
recommendation, XML, publication-planning, and publication-execution boundaries. Stage selection is
explicit and canonically ordered. Each dependent stage requires its predecessors; summary
serialization remains available for partial and cancelled runs. Completed outputs are immutable and
remain present when a later stage fails.

The orchestration contract is versioned centrally. It has no FastAPI route, CLI, database,
background worker, process-global registry, or hidden network behavior.

The service composes the crawler's accepted observer through a backward-compatible per-run override,
so live crawl progress is already framework-independent before any public delivery layer exists.

## Consequences

One internal result can now describe crawl-only through full local-publication workflows. The layer
does not duplicate accepted domain rules. Execution is sequential between stages and exists only for
the current process. Public request admission, durable job state, restart recovery, scheduling, and
distributed execution remain deferred. A later ADR must supersede this record explicitly when those
boundaries are introduced.
