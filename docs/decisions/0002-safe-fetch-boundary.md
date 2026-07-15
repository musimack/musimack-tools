# ADR 0002: Safe Single-URL Fetch Boundary

- Status: Proposed
- Date: 2026-07-15

## Context

Future SEO modules need one reusable HTTP evidence source before any crawl frontier exists.
Automatic redirects, implicit environment proxies, unvalidated DNS answers, or unbounded bodies
would create SSRF and resource-exhaustion risks. The boundary must remain deterministic in tests
and must not become a public arbitrary-fetch API.

## Decisions

1. Requests use asynchronous HTTPX GET with automatic redirects disabled.
2. DNS is resolved through an injectable async interface immediately before each request target;
   answers are deduplicated and bounded.
3. IP-literal URLs are rejected by production policy.
4. Any unsafe DNS answer rejects the hostname; mixed safe/unsafe sets receive a distinct typed
   failure.
5. Only configured production effective ports are allowed, initially 80 and 443.
6. Environment proxy inheritance is disabled by default.
7. Redirect statuses 301, 302, 303, 307, and 308 are processed manually. Every target is
   normalized and revalidated for scope, DNS, address safety, port, loop, and hop limit.
8. Response bodies are streamed under a hard byte limit. Oversized bodies are not retained.
9. Outcomes, selected headers, DNS summaries, redirect hops, durations, and failures use typed,
   stable evidence records.
10. Only minimal transport failures are retried under a bounded count and injectable sleep.
11. No arbitrary-fetch FastAPI endpoint is added. The boundary is internal Python infrastructure.
12. Structured application events use query-free URL summaries, and HTTPX request logging is
    held above INFO to avoid retaining full query values.

## Consequences

- Sitemap, broken-link, redirect, metadata, schema, and migration-QA modules can reuse one
  evidence contract.
- Crawl scope and network safety remain separate mandatory approvals.
- Tests use fake DNS, mocked transports, synthetic streams, and injected timing without public
  DNS or HTTP.
- Redirect bodies are not retained; the final bounded response body is retained without parsing.
- HTTP status responses are evidence, not transport failures, and are not retried automatically.

## Known limitation

Pre-request DNS validation does not pin HTTPX to the validated address or expose the connected
peer cleanly. A DNS answer could change before the connection. The design keeps resolver and
transport seams injectable for future address pinning, but production deployment must also
enforce egress restrictions that block local, private, link-local, metadata, and other prohibited
networks independently of application code.

## Deferred decisions

- Pinned-address transport with correct Host and TLS certificate behavior
- Crawl frontier, per-origin scheduling, and crawl-wide cancellation
- robots policy and HTML metadata extraction
- Persistence, exports, authentication, and public API design

## Supersession

Any change to mixed-answer rejection, IP-literal policy, redirect handling, proxy behavior,
approved ports, or peer-verification guarantees requires a later ADR that identifies and
supersedes the affected decision here.
