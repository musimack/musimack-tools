# ADR 0073: Supervisor-neutral private production operations

## Status

Accepted for Phase 27 implementation.

## Context

The repository provides a private FastAPI composition, Vite static build, SQLite/WAL persistence, durable queue and worker leases, durable artifact roots, opaque server-side sessions, role authorization, trusted-network/proxy middleware, and an unauthenticated health-only default application. It does not provide or require a container platform, service-manager unit, proxy product, cloud provider, clustered database, or backend static-file server.

Production operation needs explicit validation, separate web and worker lifecycle, migrations outside request handling, private readiness, and recoverable database/artifact backup without weakening those boundaries.

## Decision

Support a single-host, private-ingress deployment with seven distinct concerns: trusted TLS ingress/static serving, loopback web process, separate durable worker process, absolute SQLite database path, one or more absolute artifact roots, separate backup storage, and supervisor-captured operational logs.

The ingress serves the Vite build with client-route fallback and forwards same-origin `/api`. Uvicorn binds only to loopback and does not interpret proxy headers. Existing middleware validates the real private network boundary. Production composition is explicit and retains authenticated product routes; the default application remains `/api/health` only.

Operators explicitly initialize directories, inspect preflight, migrate, start worker and web, and validate private readiness. Ordinary startup never migrates. Backup requires stopped writers, uses SQLite's backup API, copies artifacts with path and mutation defenses, and publishes a hash manifest atomically. Restore always targets a new location and never replaces live state.

## Consequences

The design is deployable with any suitable supervisor and private TLS ingress, but the operator owns their product-specific configuration. SQLite confines this supported design to a topology where web and worker safely share local durable storage. Horizontal web/worker clustering, network filesystem semantics, container manifests, provider automation, public exposure, and automated database downgrade remain unsupported and require later architecture review.
