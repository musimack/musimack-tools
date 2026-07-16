# ADR 0018: Request profiles, maxima, preparation, and validation

## Status

Accepted for implementation.

## Context

Operator-friendly requests need safe defaults without weakening the accepted
crawl and run contracts. Raw inputs must be validated before constructing a
`CrawlRunRequest`, and profile overrides must remain bounded.

## Decision

Define immutable `quick_audit`, `standard_crawl`, `deep_crawl`, and
`sitemap_only` profiles. Application-level maxima form an additional safety gate
above accepted lower-layer validation. Invalid values and values above maxima
are rejected with ordered typed issues; they are never silently clamped.
These contracts belong to `seo-toolkit-application-service-v1`.

Preparation is pure. It normalizes the seed URL through accepted utilities,
validates scope and approved hosts, applies profile defaults and explicit
overrides, checks stage dependencies, builds publication and summary
configuration when requested, constructs the accepted run request, and computes
the accepted deterministic run ID. It performs no network, DNS, filesystem,
queue, or global-setting mutation.

Validation orders errors before warnings before informational findings while
preserving validator order within each severity. It reports normalized evidence
when safely available and does not submit a job.

## Consequences

- Profiles improve usability but do not alter crawl semantics.
- Deep and cross-host choices remain explicit and visible as warnings.
- Output roots are structurally validated during preparation and inspected
  without mutation during preflight.
- Lower-layer validation remains authoritative for its own contracts.
- Persistent or database-backed profiles remain deferred.

## Supersession

Changes to profile defaults, hard maxima, or validation meaning require a new
ADR that explicitly supersedes this record and versions incompatible behavior.
