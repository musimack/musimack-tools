# ADR 0001: Foundation Architecture

- Status: Accepted
- Date: 2026-07-15

## Context

Musimack needs reusable SEO tooling whose first module will be a sitemap generator and metadata
crawler. The project starts in an empty, authoritative directory and must remain independent of
all previous Musimack repositories. The first authorized batch is a network-free foundation.

## Decisions

1. **Standalone repository:** `musimack-tools` has its own Git repository and history.
2. **Monorepo:** backend, future frontend, documentation, and eventual deployment configuration
   will share the repository while retaining explicit internal boundaries.
3. **Backend:** Python and FastAPI provide the API delivery layer; Pydantic and Pydantic Settings
   provide typed contracts and configuration.
4. **Frontend direction:** a future frontend will use React, TypeScript, and Vite. It is not
   initialized in this batch.
5. **Persistence direction:** a future initial persistence implementation is expected to use
   SQLite behind clean interfaces and migrations. No persistence is added now.
6. **Reusable crawler core:** normalization, scope, fetching, parsing, policy, and orchestration
   will remain separable from FastAPI and from individual SEO modules.
7. **Network-free batch:** the current application and tests perform no DNS resolution, HTTP
   fetching, redirect handling, browser automation, or public crawling.

## Consequences

- URL normalization and scope policy can mature independently and be tested deterministically.
- FastAPI is a delivery boundary, not the crawler implementation.
- A single repository simplifies coordinated API/frontend changes while the current frontend
  remains documentation-only.
- There is no crawl capability, storage, export, authentication, or production deployment yet.
- Scope approval does not authorize a network request.
- Python is currently constrained to the validated `>=3.14,<3.15` range.

## Deferred decisions

- HTTP transport and DNS-resolver abstractions
- SSRF and egress-defense implementation
- precise robots failure behavior
- job runner and later multi-process queue architecture
- SQLite schema, migration tooling, retention, and PostgreSQL portability details
- OpenAPI client generation and frontend data-fetching library
- authentication provider and authorization roles
- XML/CSV snapshot semantics and trustworthy `lastmod` sources
- Docker images, Compose topology, reverse proxy, and hosting environment

## Supersession

A future decision may refine or replace any item by adding a numbered ADR that identifies this
record, states the changed context, describes migration consequences, and marks the affected
portion of ADR 0001 as superseded. Historical ADRs remain in the repository.
