# ADR 0015: Job concurrency and FIFO queueing

## Status

Accepted

## Context

Concurrent internal run submissions must not create unbounded work, reorder waiting jobs, or invent
a cancellation mechanism separate from the accepted run service.

## Decision

Separate the exact active-job limit from bounded waiting-queue capacity. Jobs start immediately
while active capacity exists; otherwise accepted jobs enter one FIFO deque. A terminal transition
starts the earliest queued job. Queue positions are derived, one-based, and omitted outside the
queued state. A job can be activated only once.

Duplicate detection uses the complete deterministic run ID. The default rejects an active
duplicate; configuration can allow a distinct attempt or return the existing active attempt.
Terminal attempts never block resubmission. Queue-capacity rejection does not allocate an attempt
or mutate queue state.

The registry creates exactly one cooperative cancellation token per accepted job. Queued
cancellation removes the entry and prevents execution. Starting and running cancellation signal
that token and transition to cancelling; tasks are not forcibly cancelled. The accepted run result
determines the final state.

Progress adapters retain the latest immutable event and, optionally, bounded FIFO history.
Storage failures become safe coordination warnings rather than execution control. Unexpected
run-service failures become typed terminal job evidence and do not stop later queued jobs.

## Consequences

Concurrency and order are deterministic within one event loop and registry instance. Work remains
in-process; fairness across processes and crash recovery are not provided.

## Deferred decisions

Priority queues, scheduling, distributed locks, external workers, and public progress transports
are deferred.

## Supersession

Any replacement must preserve explicit limits, deterministic duplicate semantics, cooperative
cancellation, and immutable evidence, or version the changed contract.
