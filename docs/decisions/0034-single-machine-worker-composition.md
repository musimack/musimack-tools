# ADR 0034: Single-machine worker composition

Status: Accepted

## Context

Durable queue records need an execution service without coupling crawling to FastAPI or creating
tasks during import.

## Decision

Use a framework-independent async worker with injected repository, accepted run-service factory,
and sleep boundary. Explicit startup registers the worker, completes stale recovery, marks readiness,
then begins polling. Claims create bounded per-job tasks and heartbeat loops. Durable cancellation is
forwarded to the existing cooperative token. Shutdown stops claims, enters draining, and waits a
bounded grace period, optionally requesting cancellation.

Production composition may host the worker with the authenticated API only when explicitly enabled.
The API may run without a worker, and worker-only composition requires no public route. The default
application remains health-only.

## Consequences

This supports one machine and process-local task supervision. SQLite, clock behavior, abrupt process
termination, and deployment supervision remain limitations. Multi-machine execution, Redis,
PostgreSQL, Celery/RQ, external schedulers, Docker, and public worker controls are deferred.
