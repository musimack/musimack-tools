# ADR 0016: Job retention and shutdown

## Status

Accepted

## Context

Completed runs are useful for internal lookup but cannot remain unbounded. Process shutdown must
stop admission and settle accepted work without abandoning tasks or force-cancelling crawlers.

## Decision

Retain at most the configured number of terminal jobs in monotonic completion order and evict the
oldest first. Active and queued jobs are never retention candidates. A zero limit removes terminal
records immediately after already-registered waiters can observe their referenced final view.

Payload policy independently retains a full immutable run result, summary artifacts only, or
metadata only. Final state, counts, run ID, and coordination evidence remain on every retained
record. Progress history has its own independent bound.

Registry lifecycle is created, running, shutting down, and closed. The default shutdown stops
admission, cancels queued jobs, requests cooperative cancellation for active jobs, and awaits every
tracked coordinator task. The alternative stops admission and drains accepted work in FIFO order.
Repeated shutdown is safe and returns immutable evidence. Retained lookups remain available after
close.

## Consequences

Older terminal lookups eventually return `not_found`, and zero retention may make a job unavailable
to callers that begin lookup only after completion. Shutdown duration depends on accepted
cooperative run completion; no task-kill timeout is claimed. Registry state has no restart
durability.

## Deferred decisions

Persistent retention, tombstones, archival, forced process isolation, distributed shutdown, and
operator-facing lifecycle APIs are deferred.

## Supersession

A future ADR must version changed eviction or shutdown semantics and define migration of retained
evidence.
