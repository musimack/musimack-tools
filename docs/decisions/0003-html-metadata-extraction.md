# ADR 0003: HTML Metadata and Link Extraction

- Status: Proposed
- Date: 2026-07-15

## Context

Future sitemap, metadata, canonical, broken-link, schema, and migration-QA modules need stable
evidence from one bounded response. Parsing must not become part of HTTP transport, silently
discard conflicting observations, or introduce crawl scheduling or a public arbitrary-input API.
Malformed real-world HTML and legacy encodings require a tolerant but deterministic strategy.

## Decisions

1. Beautiful Soup 4 with lxml is the HTML parsing strategy. Both are explicit runtime
   dependencies validated on Python 3.14.
2. `HtmlMetadataParser` consumes an immutable completed `FetchResult`. It performs no DNS or HTTP
   operations and does not mutate fetch evidence.
3. Failed, truncated, missing, empty, non-success, and clearly non-HTML evidence receives stable
   skipped outcomes rather than page metadata.
4. Encoding selection follows HTTP charset, BOM, bounded meta charset, bounded meta http-equiv,
   then Windows-1252 fallback. Replacement decoding remains explicit warning evidence.
5. All title, description, canonical, base, robots, and link observations remain available in
   document order. Duplicate and conflicting metadata is not silently collapsed.
6. The first valid base URL becomes effective. Invalid preceding values remain evidence, and
   later base elements are retained but cannot replace an already selected valid base.
7. Canonical and link references use the accepted deterministic URL normalizer. They are never
   fetched by the parser.
8. Navigable `<a>` and `<area>` links remain in document order without global deduplication or
   queueing. Resource references are outside this boundary.
9. Metadata-quality warnings remain separate from future indexability and sitemap eligibility.
10. No parser or fetch endpoint is added. `/api/health` remains the only public API operation.

## Consequences

- Fetching, decoding, extraction, scope evidence, and future decision engines remain separable.
- Callers can audit raw and normalized observations, conflicts, warning thresholds, and encoding
  provenance without reparsing HTML.
- The parser tolerates malformed HTML while recording observable recovery.
- Link scope evidence is optional and does not imply network authorization.
- Inline deterministic tests require no public DNS, websites, browser, or fixture service.

## Deferred decisions

- robots.txt and X-Robots-Tag interpretation
- user-agent directive precedence and final page indexability
- schema, Open Graph, hreflang, asset, and general link-element extraction
- crawl frontier, cross-page deduplication, queueing, scheduling, and cancellation
- persistence, sitemap recommendations, exports, authentication, and public APIs

## Supersession

A later ADR must identify and supersede the affected decision before changing encoding
precedence, first-valid-base behavior, canonical selection, document-order link preservation,
parser/network separation, or the prohibition on parser-driven sitemap decisions.
