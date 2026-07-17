# Blog Strategy BS-01

## Purpose and boundaries

Blog Strategy is an internal module of the Musimack SEO Toolkit. The
`musimack-tools-blog-strategy` worktree is temporary; after review, rebase, and merge, the module
lives in the single main application. BS-01 organizes a client's existing blog before competitor
research. It works without AI, external research, Google Search Console, keyword-volume data, or
live network access.

The sitemap and crawl systems remain authoritative for discovery, fetching, redirects, canonical
URLs, metadata, indexability, and other page evidence. Blog Strategy stores only selected inventory
records and their provenance. `PageEvidenceProvider.preview()` is the narrow, read-only integration
boundary. Its fixture adapter proves selection and idempotency now; a production adapter must be
connected to the shared evidence query after the sitemap stream is merged and rebased.

BS-01 does not score or automatically detect cannibalization. Related or complementary articles are
not automatically cannibalization. Manual overlap notes describe concerns, and a human's review
state is authoritative. BS-02 owns deterministic candidate generation. BS-03 owns future AI-assisted
classification. Competitors, ChatGPT/Claude research reconciliation, and the final opportunity
matrix remain BS-04 through BS-06. No GSC evidence is inferred.

## Workflow

The private UI and `/api/internal/v1/blog-strategy` API follow this sequence:

1. Projects: create a client project with website, market, service-area, service, important-page,
   and compliance context.
2. Project overview: inspect progress counts and export warnings.
3. Client Content: add URLs manually or select previewed shared-evidence candidates. Normalized URLs
   are unique per project; repeated imports are skipped and source records remain unchanged.
4. Classifications: record primary/secondary topics, intent, audience question, content role,
   supported page, geographic intent, time sensitivity, claim risk, review state, and notes.
5. Topic Families: create, rename, archive, merge, and assign pages. A page has at most one family in
   BS-01. A merge moves source members and preserves the merged record.
6. Manual Overlap Review: record two or more pages, concern type, severity, evidence, preferred page,
   and open/dismissed/confirmed/resolved/deferred state. A preferred page must belong to the concern.
7. Strategy Decisions: assign action, priority, destination, rationale, and approval. Approval records
   actor/time. Revision values provide optimistic concurrency on mutable records.
8. Export: review warnings, explicitly acknowledge incomplete work when necessary, and create the
   single-sheet strategy artifact.

Project status transitions are validated along the draft → inventory → organization → review →
complete path; archival is terminal. Append-only Blog Strategy events record project, page, family,
overlap, merge, and update activity without storing secrets.

## Inventory and classification rules

Manual, sitemap, crawl, and generic import sources are represented, but source provenance never
becomes authoritative crawl evidence. URL identity lowercases the HTTP(S) scheme/IDNA host, removes
default ports and fragments, collapses repeated path slashes, and removes non-root trailing slashes.
Only HTTP(S) URLs are accepted.

Classification source is manual in BS-01. Supported content roles, search intents, claim risks,
family membership roles, actions, priorities, inclusion states, and overlap states are closed enums
in `domain/blog_strategy.py`. `future_ai` is reserved as a future source label; no AI call, embedding,
semantic search, or automated classification exists here.

Readiness warns about missing classification review, unassigned families, open high-severity
concerns, undecided actions, high-risk content without a claim-review action, and missing approvals.
Warnings block export until the internal user explicitly acknowledges them.

## One-sheet export

The filename is `<client-slug>-blog-strategy.xlsx`; the only worksheet is `Blog Strategy`. Each
included page is one row in the required deterministic 27-column order. The header is frozen,
filters are enabled, text wraps, columns have bounded readable widths, HTTP(S) cells use safe external
hyperlinks, and the reviewed date has a stable ISO representation. There are no formulas, hidden
sheets, hidden business rules, macros, or external workbook links. Text beginning with `=`, `+`, `-`,
or `@` receives a leading apostrophe to prevent formula injection. Generation reopens the ZIP/XML
package and verifies the worksheet count/name, row count, header freeze, filters, formulas, styles,
and hidden-sheet state.

The existing durable artifact store currently requires crawl job/run foreign keys. BS-01 therefore
keeps workbook bytes behind the private service/API response rather than inventing a second artifact
registry or synthetic crawl records. After the sitemap merge, integration should generalize or adapt
the shared artifact authority for project-owned artifacts. Until then, export history metadata and
durable download registration are a known deferred integration point.

## Permissions

All routes are private and are mounted only through authenticated production composition. No route is
added to the health-only application.

| Action | Permission | Default role |
| --- | --- | --- |
| View projects/workflow | `blog_strategy.view` | Viewer, Operator, Administrator |
| Edit projects/inventory | `blog_strategy.edit` | Operator, Administrator |
| Import inventory | `blog_strategy.import` | Operator, Administrator |
| Review classifications/decisions | `blog_strategy.review` | Operator, Administrator |
| Manage topic families | `blog_strategy.families_manage` | Operator, Administrator |
| Manage overlap concerns | `blog_strategy.overlaps_manage` | Operator, Administrator |
| Approve decisions | `blog_strategy.approve` | Administrator |
| Create exports | `blog_strategy.export` | Operator, Administrator |
| Download retained artifacts | `artifacts.download` | Existing artifact policy |

Unknown protected operations continue to fail closed. The shared bearer compatibility identity
retains administrator permissions by existing policy.

## Persistence, fixtures, and validation

Migration `0008_blog_strategy` adds only Blog Strategy projects, pages, topic families, manual overlap
notes, and events. It follows current head `0007_metadata_audit`, modifies no earlier migration, and
downgrades only its own tables. Because sitemap work may add another migration first, the identifier
and down-revision must be reconciled after rebasing.

The synthetic BeWell Chiropractic fixture contains ten invented pages, two substantive topic
families, two primary guides, supporting and complementary articles, an FAQ, a Tigard local article,
a high-risk claim, an excluded announcement, a possible-overlap dismissal, a resolved near-duplicate
pair, and an open service-page conflict. It contains no production dataset, analytics, credentials,
personal information, unpublished content, or proprietary export.

Backend tests block DNS and non-loopback connections. Focused coverage exercises normalization,
duplicate prevention, status/revision conflicts, import preview/idempotency/provenance, family
merge/archive, multi-page overlap review, preferred-page validation, approvals, events, readiness,
formula safety, XLSX generation, and programmatic reopen. Frontend validation covers the private API
boundary plus existing application tests, strict TypeScript, lint, formatting, and production build.

## Parallel-development reconciliation

This branch intentionally changes a small set of shared conflict zones: Alembic model registration,
production application composition, authorization enums/role mapping/path mapping, API error codes,
frontend permission contracts, route registration, and navigation. It does not change crawl/sitemap
contracts, URL fetching, page-evidence storage, dependency manifests, or lockfiles. New Blog Strategy
files contain the domain, repository, service, API, UI, tests, fixture, and this documentation.

Recommended integration order:

1. Finish and merge the current sitemap phase.
2. Update `main` and rebase `feature/blog-strategy-bs01` only with explicit authorization.
3. Rename/reparent `0008_blog_strategy` if the sitemap stream now owns that revision or migration
   head; preserve the Blog-only upgrade/downgrade body.
4. Reconcile the narrowly changed composition, authorization, frontend route, and navigation lines.
5. Connect a production `PageEvidenceProvider` and shared artifact adapter without changing Blog
   Strategy's domain contracts.
6. Run the complete backend/frontend, migration, route, security, and export validation suites before
   merge review.

Known limitations are the fixture-only evidence adapter, non-durable project export download, manual
classification, manual overlap judgment, and the absence of AI, competitor, GSC, research, scoring,
and opportunity-matrix features. These boundaries are deliberate BS-01 scope, not inferred evidence.
