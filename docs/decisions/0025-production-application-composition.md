# ADR 0025: Production application composition

## Status

Accepted for `seo-toolkit-production-app-v1`.

## Decision

Keep the existing `create_app()` health-only. A separate `create_production_app()` requires an
injected application service, validates environment-backed security settings immediately, mounts
the accepted internal router explicitly, and adds authentication, correlation, optional CORS,
access logging, and security headers. Invalid or disabled configuration fails rather than silently
falling back to health-only service. OpenAPI is opt-in.

## Consequences

Imports create no services, registries, tasks, or secret reads. Deployment callers must make an
explicit choice. TLS, reverse-proxy installation, workers, persistence, Docker, CI, and public
deployment remain outside this decision.
