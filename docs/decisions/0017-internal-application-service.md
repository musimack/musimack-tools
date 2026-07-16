# ADR 0017: Internal application-service facade

## Status

Accepted for implementation.

## Context

The accepted crawl, recommendation, XML, publication, run, and job layers provide
bounded internal behavior, but future adapters need one framework-independent
entry point. Exposing lower-layer objects directly would leak scheduler details
and make API, CLI, or frontend adapters responsible for orchestration policy.

## Decision

Introduce an internal `SeoToolkitApplicationService` identified by
`seo-toolkit-application-service-v1`. The facade composes the accepted job
service and application preparation, preflight, readiness, projection, and
diagnostic services. It does not reimplement crawling, run orchestration,
scheduling, recommendation, XML generation, or publication.

The facade provides validation, preparation, advisory preflight, submission,
status and progress lookup, cancellation, bounded result lookup, registry
status, capabilities, readiness, waiting, diagnostics, and shutdown. It remains
framework-independent and has no process-global singleton.

## Consequences

- Future adapters have one stable internal composition boundary.
- Application projections exclude tasks, locks, cancellation tokens, raw
  exceptions, and machine-specific paths.
- The existing FastAPI surface remains limited to `/api/health`.
- Submission stays authoritative; preflight cannot reserve capacity.
- Public API, CLI, frontend, authentication, persistence, and distributed jobs
  remain deferred.

## Supersession

A later ADR may supersede this decision when an authorized adapter or durable
execution model requires a revised boundary. The replacement must name this ADR
and preserve or explicitly version its contracts.
