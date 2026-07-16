# 0053: Sitemap recommendation review

Status: Accepted for `seo-toolkit-sitemap-review-ui-v1`.

## Decision

Expose a bounded, read-only recommendation page from retained full job results. The endpoint uses
the existing `runs.view` permission and supports offset, limit, state, reason, and URL-text filters.
It returns decision evidence only: URLs, eligibility state, reason, explanation, redirect,
canonical, robots, indexability, and configured exclusion summaries.

## Consequences

The UI can explain per-URL sitemap decisions without exposing raw HTML, response bodies, storage
paths, crawler internals, or mutable override controls. One additional OpenAPI path is intentional.
