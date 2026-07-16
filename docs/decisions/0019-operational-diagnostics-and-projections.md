# ADR 0019: Operational diagnostics, readiness, and bounded projections

## Status

Accepted for implementation.

## Context

Operators and future adapters need useful internal evidence without receiving
unbounded crawl records, machine paths, runtime objects, or unstable exception
text. They also need explicit readiness and capability information instead of a
single Boolean.

## Decision

Define immutable readiness, capability, job-status, result, validation, and
preflight projections. Readiness uses `ready`, `degraded`, and `not_ready` with
ordered typed checks. Capabilities are centralized typed declarations rather
than inferred from runtime filesystem scanning.

Default result projections are bounded to identities, lifecycle and stage
states, counts, stable codes, logical filenames, hashes, retention state, and
version identifiers. Detailed crawl records and retained lower-layer results
stay behind their existing internal contracts.

Diagnostics use the centralized `seo-toolkit-diagnostics-v1` schema. JSON is
UTF-8, sorted by key, indented by two spaces, uses LF newlines, and ends in a
final newline. Markdown is deterministic, bounded, UTF-8, LF-terminated, and
embeds the same safe normalized evidence. SHA-256 hashes are returned separately
and are not self-embedded. These projections are part of
`seo-toolkit-application-service-v1`.

## Consequences

- Diagnostics omit timestamps, absolute machine paths, secrets, stack traces,
  bodies, tasks, locks, tokens, and raw exceptions.
- Readiness can distinguish blocking failures from optional degradation.
- Capability ordering and supported/unsupported identifiers are deterministic.
- Projections are suitable for future adapters but are not public API schemas.
- Detailed result export, durable diagnostics, and public readiness endpoints
  remain deferred.

## Supersession

A future ADR may add versioned schemas or detailed authorized export boundaries.
It must explicitly supersede this record for incompatible diagnostic or
projection changes.
