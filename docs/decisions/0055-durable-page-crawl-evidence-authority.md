# ADR 0055: Durable page crawl evidence authority

## Status

Accepted.

## Decision

Phase 20A persists a bounded projection of accepted terminal `UrlCrawlRecord` values. Crawl,
fetching, URL normalization, HTML parsing, robots permission, and indexability domains remain the
only evidence authorities. Persistence does not fetch, resolve DNS, parse, or reinterpret evidence.

The exact evidence contract is `seo-toolkit-page-crawl-evidence-v1`. Raw HTML, response bodies,
full headers, binaries, credentials, cookies, worker tokens, database URLs, and filesystem paths are
excluded.

## Consequences

Future metadata audits can query page evidence after restart or terminal-payload eviction. Phase 20
issue classification and UI remain deferred.
