# Website migration QA

Phase 26 adds an opt-in, private workflow for checking website-migration continuity against retained crawl evidence. It accepts bounded CSV or TSV source inventory and optional redirect-map text, normalizes every URL through the existing boundary, and preserves raw, normalized, comparison, planned, observed, final, and canonical values separately.

## Evidence and readiness

Every project names a terminal destination crawl run. A source crawl run is optional; without one, source-to-destination comparisons may remain indeterminate. Readiness is `ready`, `ready_with_warnings`, `incompatible`, `expired`, `missing_evidence`, or `invalid_configuration`. The service never fetches a live page and never interprets an uploaded map as an observation.

## Analysis contract

Mapping precedence is explicit redirect map, explicit inventory proposal, observed redirect, exact normalized URL, configured origin substitution, path match, canonical hint, and bounded content-similarity hint. Competing hints become a manual-review candidate; unmapped, ambiguous, one-to-many, and many-to-one states remain explicit. Path and content hints never claim semantic equivalence. Destination status and redirect observations come only from durable page evidence. Comparisons are emitted only when retained evidence exists; unsupported comparisons are marked indeterminate rather than inferred.

The stable taxonomy covers redirects, destination status, metadata, content, canonical/indexability, internal links, sitemaps, images, structured data, mapping quality, readiness, and sitewide summaries. Recommendations retain supporting finding identifiers, confidence, and human-review flags. They never mutate redirects, server configuration, sitemaps, or live content.

## Persistence and lifecycle

Migration `0013_website_migration_qa` adds projects, source rows, redirect-map rows, URL mappings, redirect observations, page comparisons, findings, recommendations, sitewide summaries, exports, and events. Projects move through `draft`, `ready`, `running`, and one terminal state. Execution claims are atomic, interrupted work reconciles to failed, and cleanup respects retention.

## Private API and exports

All operations are below `/api/internal/v1/migrations/qa`. Reads require `runs.view`; every POST requires `jobs.submit`. The workflow is disabled by default. Its eight authenticated artifact outputs are findings, redirects, mappings, comparisons, recommendations, and sitewide CSV; complete JSON using schema `musimack-website-migration-qa` version `1.0`; and an 18-section Markdown report.

Defaults cap source and redirect-map inputs at 50,000 rows, content at 10 MB, individual fields and export cells at 4,096 characters, pages at 200 rows, and exports at 100,000 rows. CSV schemas are fixed and formula-like text is protected without changing numeric cells. No dependency, external validator, second network client, or public-network capability is introduced.
