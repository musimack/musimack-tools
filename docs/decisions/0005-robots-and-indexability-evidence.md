# ADR 0005: Robots Permission and Indexability Evidence

- Status: Accepted for implementation
- Date: 2026-07-15

## Context

The crawler can safely fetch and parse pages but previously had no robots permission layer or
X-Robots-Tag interpretation. Crawl permission, page indexability evidence, and sitemap eligibility
answer different questions and must not become one boolean.

## Decision

Retrieve robots.txt once per normalized effective origin per crawl through the accepted safe
fetcher. Use an async single-flight cache and retain every terminal origin result, including
missing, forbidden, temporary failure, invalid response, and oversized body. Treat 400/404/204 as
no policy, 401/403 as deny, and 429/5xx/transport failure as conservative temporary denial.

Match the case-insensitive `MusimackSEOToolkit` product token. Consecutive User-agent declarations
form one group; a later declaration after group directives starts another group. Select the
earliest most-specific matching group, then apply case-sensitive path-plus-query rules. Longest
specificity wins and Allow wins ties. Support `*` and terminal `$` deterministically.

Preserve Crawl-delay and Sitemap directives as evidence without enforcement or retrieval. Count
robots bytes both separately and toward the crawl aggregate.

Parse repeated X-Robots-Tag values into ordered generic and crawler-specific records. Preserve meta
robots and header directives separately, recording conflicts without a final indexability or
sitemap decision. Indexability evidence does not change frontier admission.

Keep all services internal. No robots, crawl, fetch, parser, or indexability API is added.

Require every `SingleSiteCrawlOrchestrator` composition to provide a robots session factory.
Production must explicitly provide `RobotsTxtService`. An allow-all policy may exist only as an
explicitly injected test-only implementation and is not exported by production composition code.

## Consequences

- A denied page is never passed to the page fetcher and receives typed URL-level evidence.
- Multiple pages on one origin share one robots retrieval and immutable origin record.
- Temporary robots failure reduces crawl coverage rather than silently violating policy.
- Omitting robots permission wiring is a clear construction error; no implicit runtime allow-all
  fallback can bypass retrieval.
- Crawl-delay cannot weaken or replace configured safety pacing.
- Sitemap directives can support a future discovery feature without changing current scope.
- The accepted page fetcher follows redirects internally, so this layer cannot evaluate robots
  immediately before each page redirect hop without a future fetch-contract extension. The fetcher
  does continue to revalidate crawl scope and network safety for every redirect target.
- The robots-specific body limit rejects already bounded fetch evidence; the fetcher's streaming
  hard limit remains the network-read boundary.

## Deferred decisions

Final generic or search-engine-specific indexability, sitemap eligibility, sitemap retrieval,
robots Crawl-delay enforcement, redirect-policy callbacks, persistence, exports, public APIs, and
frontend presentation remain separate future decisions.

## Supersession

A future ADR may supersede this record by naming it, preserving stable evidence codes where
possible, and describing any migration of cached or persisted robots decisions.
