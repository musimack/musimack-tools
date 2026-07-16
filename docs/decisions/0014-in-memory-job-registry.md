# ADR 0014: In-memory job registry

## Status

Accepted

## Context

The accepted crawl-run service executes one immutable run request. Internal callers now need to
submit and inspect multiple attempts without introducing persistence, a public API, or a worker
system.

## Decision

Use one explicitly injected, process-local `InMemoryJobRegistry`. It owns job records, FIFO order,
active membership, attempt counters, cooperative cancellation tokens, completion signals, progress,
results, and terminal-retention order. One async lock protects state transitions; no global registry
exists.

The contract version is `crawl-job-registry-v1`. The accepted deterministic run ID remains the
request identity. Each execution attempt receives
`job-<12-character-run-prefix>-<four-digit-attempt>`, allocated under the registry lock. Identity
contains no timestamps, randomness, paths, users, or machine data.

Public contracts are frozen slotted dataclasses, enums, and tuples. They do not expose tasks,
events, locks, or mutable cancellation tokens. Lookup after bounded eviction returns `not_found`;
no tombstones are retained.

## Consequences

Submission, lookup, waiting, and cancellation are deterministic within one registry lifetime. All
state and attempt counters disappear on process exit. The design neither persists nor coordinates
across processes.

## Deferred decisions

Authenticated API adapters, persistent job history, restart recovery, durable queues, external
workers, and distributed coordination require separate decisions.

## Supersession

A future ADR may supersede this record only by describing migration of identity, state, cancellation,
and retained evidence without silently changing accepted run semantics.
