# ADR 0058: Page evidence query contract

## Status

Accepted.

## Decision

The internal service uses `seo-toolkit-page-crawl-evidence-query-v1` and opaque
`seo-toolkit-page-crawl-evidence-pagination-v1` cursors. Cursors bind the exact filter fingerprint
to `crawl_discovery_sequence_asc_url_identity_asc-v1`. Query sizes default to 50 and are capped at
200. Filters are typed and no caller-controlled sorting or SQL is accepted.

Phase 20A adds no HTTP or frontend route. Restart-safe service and repository tests prove access,
so the default health-only app and all accepted route counts remain unchanged.

## Consequences

Future Phase 20 APIs can consume stable bounded DTOs without exposing ORM rows, raw HTML, bodies,
headers, paths, or secrets.
