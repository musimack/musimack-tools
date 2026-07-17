# Phase 23 internal-link analysis

Phase 23 is an opt-in, private workflow awaiting human review. It derives a deterministic graph from one terminal crawl's durable page, source-link, redirect, canonical, indexability, content-type, scope, crawl-depth, discovery-sequence, and seed evidence. It introduces no fetch, DNS, parser, crawler, semantic model, or live-site mutation.

## Graph and metric policy

Nodes use the accepted normalized page identity. Same-scope successful HTML pages are eligible; redirects, canonical duplicates, noindex pages, non-HTML resources, failures, and unverified pages remain durable with explicit exclusion states. Raw link occurrences remain authoritative. Unique edges group source-target pairs while preserving raw occurrence, anchor, fragment, nofollow, redirect, and sitewide evidence. Explicit out-of-scope decisions are excluded; historical same-host evidence with a null `in_scope` projection uses the parser-owned `internal` decision. Nofollow occurrences count in inventory but not primary reachability or hub/authority flow.

The service calculates inbound/outbound occurrences and unique pages, direct and redirect-adjusted inlinks, nofollow counts, broken/external/redirecting outlinks, crawl and graph depth, reachability, bounded predecessor paths, sitewide/non-sitewide support, and bounded anchor aggregates. It uses deterministic ordering and configured thresholds. It does not claim PageRank.

Seeds come only from the selected run. Orphan states distinguish true candidates, sitemap-only evidence where present, seed pages, redirect-only inlinks, nofollow-only inlinks, excluded pages, and historically unverified evidence. Hub and authority candidates use graph counts with sitewide discounting and small-crawl safeguards.

Anchor text is whitespace/case normalized and capped at 512 characters. Empty, generic, URL-shaped, concentrated, inconsistent, redirecting, and broken-target anchors are conservative findings. Opportunities are limited to defensible graph evidence: orphan linking from an existing hub, low-inlink strengthening, redirect/broken destination updates, excessive-outlink review, anchor improvement, hub promotion, and graph-isolation review. They never invent topical similarity or a source page.

## Persistence, API, and exports

Migration `0010_internal_link_analysis` (down revision `0009_broken_link_redirect_analysis`) adds durable audits, page metrics, edges, reachability, findings, anchor aggregates, opportunities, exports, and lifecycle events. Atomic claim, terminal failure/cancellation, startup reconciliation, audit-only cleanup, cascades, and retained source evidence follow accepted patterns.

The opt-in API is available only under `/api/internal/v1/audits/internal-links`. Reads require `runs.view`; creation, execution, and export creation require `jobs.submit`. The default application remains health-only and `/api/audits/internal-links` is absent. Cursor tokens bind resource, ordering, filters, and offset.

Exports include page metrics, orphan candidates, hubs/authorities, anchors, and opportunities CSV plus complete JSON and Markdown. CSV formula prefixes are neutralized. Outputs have stable columns/order and use the authenticated artifact authority for storage, hashing, integrity checks, download authorization, and retention.

The protected frontend provides list, evidence check, creation/execution, lifecycle summary, pages, edges, orphans, hubs, authorities, reachability, findings, anchors, opportunities, and exports. Tables preserve long-URL wrapping, semantic captions/headings, keyboard navigation, responsive design-system behavior, and explicit empty/error states.

Known limitations are deliberate: no semantic similarity, embeddings, AI topic matching, traffic/ranking weighting, external-link checking, fragment validation, link insertion, navigation editing, or live-site changes. Historical runs with incomplete scope or seed evidence are rejected or classified conservatively. Phase 24 image audit remains untouched. Human browser acceptance is pending.

The parallel Blog Strategy worktree remains untouched. Its `0009` migration collision must be reconciled after Phase 23 review and any authorized commit, preferably by rebasing it onto updated `main` and renumbering its migration.
