# ADR 0033: Stale recovery, durable cancellation, and retries

Status: Accepted

## Context

Worker or process loss can leave active leases and durable cancellation requests unresolved.

## Decision

Startup and explicit recovery inspect expired leases and workers whose heartbeat exceeds the stale
threshold while they own claims. Recovery releases each stale lease and records an immutable event.
Cancellation always wins. Otherwise the configured deterministic retry classifier either places the
same job ID in retry wait with a new availability sequence or records failed/partially-completed
state. A new claim creates a separate execution-attempt row and lease generation.

Retry defaults to `never`. Authorized policies use selected stable failure codes, bounded maximum
attempts, and fixed or linear delays without jitter. Recovery never resumes crawl frontier state.

## Consequences

Completed stage and artifact metadata remains evidence, but a retried execution starts through the
accepted run boundary. Wall-clock UTC controls eligibility and expiry. Cancellation survives worker
loss and is never converted into a retry. Automatic crawl resume and public retry controls remain
deferred.
