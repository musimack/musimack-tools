# ADR 0012: Run progress and cooperative cancellation

## Status

Accepted

## Decision

Represent run lifecycle, per-stage lifecycle, progress snapshots, and progress events as immutable
typed records. Event sequence numbers start at 1. Sinks are injected and may be no-op, recording, or
async callback implementations. The first sink exception becomes a stable warning; later delivery is
suppressed and core execution continues.

Adapt the accepted crawler observer per run. Preserve callback order and duplicate callbacks. Emit
one final reconciliation only when the last callback does not match authoritative final crawl
counters. Observer-to-sink failures are contained by the run adapter and cannot become crawler
errors.

Reuse the crawler's cooperative cancellation token. Check it before stages and before publication
execution. Never terminate threads or processes. Preserve partial crawl and all completed downstream
evidence.

## Consequences

The service provides live in-process progress without depending on a web framework. A future adapter
may deliver those events publicly; there is no public status endpoint or durable progress store.
Cancellation observation follows live snapshots already delivered, and a completed crawl is not
retroactively cancelled. The synchronous accepted publication
executor does not expose a checkpoint between package files, so this version cannot promise
mid-package cancellation; each atomic file operation and the package call are allowed to finish.
