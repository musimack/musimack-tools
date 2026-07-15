# Foundation Architecture

## Repository and product boundary

`musimack-tools` is a standalone repository and application. It is not a package, worktree, or
subproject of any previous Musimack repository. The chosen direction is a monorepo so the API,
future frontend, documentation, and later deployment configuration can evolve under one
reviewable version boundary while remaining internally separated.

## Current implementation

The implemented foundation is backend-only. Python 3.14, FastAPI, Pydantic, and Pydantic
Settings provide a typed application boundary. The FastAPI composition root exports both a
testable `create_app` factory and a stable `app` instance. The only public operation is the
minimal `/api/health` endpoint.

The backend uses a `src` package layout:

- `api` owns HTTP delivery contracts.
- `core` owns typed process configuration.
- `domain` owns framework-independent value objects and evidence types.
- `crawl` owns network-free normalization and scope policy.

These dependencies point inward: HTTP delivery can use domain and crawler-core contracts, but
the crawler core does not depend on FastAPI.

## Future boundaries

### Frontend

The future frontend will use React, TypeScript, and Vite under `frontend/`. This batch creates
no frontend package manifest or dependencies. The frontend should consume a typed client based
on the FastAPI OpenAPI contract and use server-state-oriented data fetching.

### Reusable crawler core

Future fetching, redirects, HTML extraction, robots evaluation, indexability analysis, and the
crawl frontier belong behind reusable crawler-core interfaces. HTTP transport, DNS resolution,
time, persistence, cancellation, and progress reporting should be injected so the core remains
deterministic in tests and reusable by broken-link, metadata, canonical, redirect, inventory,
internal-link, image, schema, indexability, and migration-QA modules.

### Persistence

Persistence is absent. A future boundary may use SQLite initially through typed repository
interfaces and migrations, with PostgreSQL portability retained. API and domain objects should
not acquire SQLite-specific behavior.

### Background jobs

Long-running crawl jobs are absent. A future job boundary should own bounded job admission,
bounded per-job workers, cooperative cancellation, persisted progress, interruption recovery,
and server-sent progress events. FastAPI background tasks should not become the crawler's core
execution model.

### Exports

XML sitemap and CSV audit serialization will be separate consumers of stable stored crawl
results. XML will omit `priority` and `changefreq`, and will include `lastmod` only with recorded
trustworthy provenance. Metadata warnings will remain separate from sitemap eligibility.

## Why network access is excluded

URL parsing and hostname matching alone cannot make outbound requests safe. Live fetching
requires DNS and connected-address validation, SSRF protections, per-redirect revalidation,
timeouts, byte limits, scope enforcement, robots policy, and bounded concurrency. Implementing
pure normalization and scope policy first makes those later controls testable without implying
that an in-scope string is safe to request.

## Testing strategy

- Unit tests cover normalization, scope decisions, settings validation, and stable evidence.
- FastAPI's in-process test client covers the health API.
- An automatic test fixture blocks DNS resolution and non-loopback socket connections; Windows
  event-loop loopback plumbing remains available to the in-process test client.
- Future HTTP behavior must use injected mock transports or explicitly controlled local fixture
  servers, never public websites.
- Ruff formatting/linting and strict MyPy run alongside Pytest.

## Development and deployment direction

Windows PowerShell is the primary documented local workflow. Repository files use LF endings,
while Git and editors can manage platform checkout behavior normally. All commands run from the
repository root and use `.venv` rather than changing system Python.

Docker-based local and server deployment remains the eventual direction, but Dockerfiles,
Compose, reverse proxies, authentication, secret handling, and production egress controls are
explicitly deferred.
