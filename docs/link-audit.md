# Broken-link and redirect analysis reference

Phase 22 is an opt-in, private, selected-run analysis for human review. It consumes only terminal durable crawl evidence: parser-owned source-link occurrences, page fetch and parse evidence, the captured scope snapshot, and ordered redirect hops. It performs no DNS lookup, HTTP fetch, HTML reparse, sitemap recomputation, or live-site mutation.

## Evidence and identity

Migration `0009_broken_link_redirect_analysis` adds `crawl_link_evidence` in the same terminal page-evidence transaction. Every occurrence retains source and target identity, discovery and link sequence, raw and resolved href, element, bounded anchor text, rel/nofollow, fragment, scheme classification, internal/scope decisions, reason code, and evidence version. Duplicate links remain distinct occurrences; targets aggregate by normalized URL identity.

Fragments are retained for inspection but are not fetched or validated. `mailto`, `tel`, `javascript`, `data`, invalid, unsupported, external, and out-of-scope links remain explicit non-audited classifications. An absent target page is unverified, never presumed broken.

## Classification and recommendations

The stable lifecycle is accepted, claiming, graph building, link classification, redirect expansion, loop detection, recommendation building, and one terminal state. Target results distinguish working, broken 404/410/other 4xx/5xx, fetch failure subtypes, non-HTML, source unavailable, unverified, out-of-scope, and external evidence.

Redirect precedence is loop, out-of-scope or external destination, non-HTML destination, broken destination, unverified destination, then working single or multi-hop redirect. Ordered nodes and edges determine stable chain identity. Impact records include unique source pages, total occurrences, anchors, depth range, and a configurable sitewide candidate threshold. Recommendations are evidence-backed suggestions only; low-confidence and redirect-creation/replacement decisions require human review.

## Private API and exports

All routes are below `/api/internal/v1/audits/links`. `runs.view` permits evidence/status and retained-result reads. `jobs.submit` permits create, execute, and export creation. The default application remains `GET /api/health` only. Target, occurrence, chain, finding, and recommendation inventories use bounded, deterministic, versioned, filter-bound cursors.

Exports are stored through the existing private artifact service: broken-links CSV, redirect-chains CSV, redirect-map CSV, complete JSON, and Markdown. CSV formula prefixes are escaped. Export row limits and truncation are explicit; artifact integrity and download authorization remain authoritative.

## Retention and limitations

Audit cleanup is bounded and cascades normalized audit records. Source-link evidence follows its source crawl/page evidence lifecycle. Restart reconciliation marks an interrupted running audit failed; completed evidence remains inspectable. External destinations and fragments are not validated, and the engine does not propose a destination without retained supporting evidence.

## Integration and roadmap status

Shared integration edits are intentionally limited to Alembic model registration and head tests, page-evidence persistence, API errors and permissions, optional application composition, frontend routes/navigation, the existing browser-QA composition, root architecture/policy documentation, and `.env.example`. These are expected reconciliation points with the parallel Blog Strategy worktree, especially its uncommitted `0009_blog_strategy_add_bs01_foundation` migration. Phase 22 does not alter that worktree or its roadmap labels. This implementation is ready for human review but is not marked accepted; only a later explicit acceptance and commit authorization can do that.

See [link-audit-browser-qa.md](link-audit-browser-qa.md) for loopback-only QA and [phase22-test-traceability.md](phase22-test-traceability.md) for automated coverage.
