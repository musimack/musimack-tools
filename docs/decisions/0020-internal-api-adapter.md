# ADR 0020: Private internal API adapter and explicit mounting

## Status

Accepted for implementation.

## Context

The framework-independent application facade needs a transport adapter for future internal
operators. Mounting job operations in the default FastAPI app would broaden exposure before a
deployment authentication boundary exists.

## Decision

Add a private FastAPI adapter beneath `/api/internal/v1`. The adapter owns Pydantic schemas,
explicit mapping, HTTP status translation, structured errors, and endpoint handlers. It delegates
all validation, preflight, submission, cancellation, readiness, capabilities, status, progress,
and results to the accepted application facade.

Router construction requires explicit service injection and creates no registry, task, or global
singleton. `mount_internal_api()` mounts only when immutable configuration explicitly enables it.
The production `create_app()` remains unchanged and health-only. Internal paths and schemas are
omitted from its OpenAPI document.

## Consequences

- Future adapters share application behavior instead of reimplementing it.
- Internal progress is request/response only; there is no streaming transport.
- Shutdown and payload-download endpoints are not exposed.
- Public deployment, authentication, persistence, workers, and frontend delivery remain deferred.

## Supersession

Any default mounting or public exposure requires a new ADR that supersedes this decision and
defines the complete deployment security boundary.
