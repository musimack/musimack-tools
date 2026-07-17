# ADR 0069: derive the internal-link graph from durable crawl evidence

## Decision

Phase 23 builds a versioned, durable, network-free graph over the accepted page and source-link projections. It preserves raw occurrences and stores deterministic derived edges, metrics, reachability, findings, anchor aggregates, opportunities, lifecycle events, and artifact references. The selected run's captured seed and scope remain authoritative.

Nofollow links remain visible but do not contribute to primary reachability. Redirect and unambiguous same-scope canonical destinations may provide adjusted edges without hiding the original destination. Sitewide evidence is discounted for authority decisions. Opportunity generation uses graph evidence only and requires human review for site changes.

## Consequences

The workflow is reproducible after a crawl, does not contact a site, and does not duplicate crawler, parser, URL, scope, authentication, authorization, or artifact authorities. Results are limited by retained historical evidence and intentionally provide no semantic similarity or PageRank claim.
