# ADR 0007: In-Memory XML Sitemap Generation

## Status

Accepted for implementation review.

## Context

The accepted recommendation engine produces immutable, ordered sitemap eligibility decisions. A
separate boundary is required to turn final include decisions into protocol-compliant XML without
embedding recommendation logic in an exporter or prematurely adding publication infrastructure.

## Decision

Implement a pure in-memory serializer with stable format identifier `sitemap-xml-v1`.

- It consumes `SitemapRecommendationProjection` and serializes only final `include` states.
- It preserves projection order and never re-evaluates eligibility evidence.
- Domain inputs and outputs remain immutable.
- Exact duplicate normalized URL strings are suppressed; the first occurrence wins.
- Invalid, non-normalized, XML-illegal, over-2,048-character, or individually oversized included
  values become ordered typed rejections without mutating recommendations or aborting valid output.
- Standard-library XML escaping is used for element text.
- Output is UTF-8 with the exact XML declaration, sitemap 0.9 namespace, two-space indentation, LF
  newlines, and a final newline.
- URL documents contain only `<url><loc>` entries.
- A valid empty URL document is returned when no entries qualify.

URL documents enforce 50,000 entries and 52,428,800 uncompressed encoded bytes. Sitemap indexes
enforce 50,000 references and the same byte limit. Lower limits may be injected for deterministic
tests, but configuration cannot exceed protocol maxima. The split algorithm measures the complete
candidate UTF-8 document and starts a new deterministically named document before a limit would be
crossed.

One URL document is named `sitemap.xml` and receives no index. Multiple documents are named
`sitemap-1.xml`, `sitemap-2.xml`, and so on. An index is built only when an explicit normalized
HTTP(S) `sitemap_base_url` provides public locations. Missing base or exceeded index capacity
returns typed blocked-index evidence while preserving every generated URL document. Recursive
indexes are not generated.

The serializer has no FastAPI, network, DNS, crawler, persistence, or file-system dependency. A
future publication layer will decide whether and where immutable bytes are written or served.

## Alternatives considered

- Re-evaluating eligibility in the serializer was rejected because it would create two competing
  policy authorities.
- Sorting URLs was rejected because crawl/recommendation order is already authoritative.
- Guessing index locations from crawled hosts was rejected because publication origin is a separate
  deployment decision.
- Failing the whole bundle for one malformed include was rejected in favor of complete typed
  rejection evidence and usable valid output.
- Writing XML files directly was rejected to preserve a reusable, side-effect-free boundary.
- Recursive sitemap indexes were rejected as unnecessary scope expansion for the v1 bundle.

## Consequences

Equal inputs and configuration produce byte-for-byte equal output, stable names, counters,
warnings, and rejections. Complete document bytes are retained in memory, so callers must respect
the configured bounds and future large-scale publication may require a deliberately designed
streaming boundary. Multi-document bundles need an explicit public base to receive an index.

## Deferred work

File-system writing, public download APIs, persistence, crawl history, background jobs, compression,
sitemap submission, Google Search Console integration, `lastmod`, `changefreq`, `priority`, image,
video, and news extensions, alternate-language annotations, manual overrides, approval workflows,
frontend work, authentication, Docker, and CI remain deferred. A future ADR may supersede this
decision by naming it, explaining the compatibility and migration impact, and preserving this
record as historical context.
