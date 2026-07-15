# ADR 0006: Sitemap Eligibility Recommendations

- Status: Accepted for implementation
- Date: 2026-07-15

## Context

The crawler retains normalized URL, scope, fetch, redirect, HTML, canonical, robots permission,
meta robots, and X-Robots-Tag evidence. XML and CSV consumers need one reusable, explainable
eligibility decision without moving policy into crawling, parsing, serialization, persistence, or
FastAPI.

## Decision

Create a pure framework-independent recommendation engine with four states: `include`, `exclude`,
`review`, and `indeterminate`. Apply state precedence as hard exclusion, indeterminate, review, then
include. Preserve every applied reason and select a primary reason from a stable ordered rule set.

Hard-exclude invalid or out-of-scope URLs, disallowed origins, unavailable or failed fetches,
redirect sources, non-200 responses, confirmed non-HTML content, robots denial, generic noindex,
configured exclusions, and selected canonicals pointing elsewhere. Generic noindex wins over a
conflicting generic index directive. Crawler-specific directives remain evidence and are not
applied generically by default.

Allow missing canonical with a warning. Review conflicting valid canonicals or one or more invalid
canonicals when no valid canonical is selected. Allow invalid canonical evidence when a valid
self-canonical is selected. Keep title and meta-description quality warnings separate from
eligibility.

Project a complete crawl in first-record order with one recommendation per normalized identity.
Exclude redirect sources. Independently evaluate a final target only through its own crawl record;
otherwise create no target recommendation and retain the evidence gap as a warning on the source.
Retain typed policy and aggregate counters. Define `SITEMAP_RULE_SET_VERSION` once as the code
authority for `sitemap-eligibility-v1`.

Use `determinate` when coherent evidence produces include, exclude, or review. Use
`blocked_missing_evidence` or `blocked_conflicting_evidence` when the recommendation state is
indeterminate. Match configured path prefixes on case-sensitive segment boundaries; a prefix such
as `/blog` cannot match `/blogging`.

Keep the engine internal. Do not add an API, XML or CSV serialization, persistence, sitemap
discovery, lastmod inference, priority, changefreq, or manual overrides.

## Consequences

- Future XML, CSV, API, and frontend layers can consume one deterministic evidence contract.
- Metadata quality cannot silently disqualify otherwise eligible pages.
- Robots denial remains distinct from noindex and sitemap eligibility.
- Redirect targets cannot inherit eligibility from source fetch evidence.
- Uncrawled redirect targets cannot become synthetic sitemap candidates.
- Conservative missing or contradictory evidence remains visibly indeterminate.
- Safe keyed logs contain no response body, raw HTML, credentials, or query string.

## Deferred decisions

Manual include/exclude overrides will be a separate auditable layer over automatic evidence. XML
and CSV serializers, persistence, public APIs, background jobs, sitemap ingestion, trustworthy
lastmod sources, authentication, frontend presentation, and deployment remain future decisions.

## Supersession

A future ADR may supersede this record by naming it, preserving stable reason codes where possible,
and documenting changes to precedence, defaults, or persisted recommendation evidence.
