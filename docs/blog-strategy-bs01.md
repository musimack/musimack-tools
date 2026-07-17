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
boundary. Its fixture adapter proves selection and idempotency. Phase 22 adds durable source-link
evidence, but the shared page projection still lacks H1, publication and modified dates, author,
word count, page type/source classification, and an import-ready completeness/provenance contract.
The production adapter therefore remains deferred rather than coupling BS-01 to a concrete audit
repository or creating a competing evidence model.

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

The Phase 22 durable artifact store still requires crawl job/run foreign keys. BS-01 therefore
keeps workbook bytes behind the private service/API response rather than inventing a second artifact
registry or synthetic crawl records. Durable download registration remains deferred until the
shared artifact authority supports project-owned artifacts.

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

Migration `0010_blog_strategy` adds only Blog Strategy projects, pages, topic families, manual overlap
notes, and events. It follows the published Phase 22 head
`0009_broken_link_redirect_analysis`, modifies no earlier migration, and downgrades only its own
tables. The repository has one migration head: `0010_blog_strategy`.

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

## Phase 21 reconciliation

The branch was rebased from BS-01 checkpoint `5667ccae` onto published `origin/main` baseline
`9182e3b9857e3d0d3e2743e0e5b9b8b601906ac3` (`Add existing sitemap audit and comparison`). The
Blog Strategy migration was renamed from `0008_blog_strategy` on `0007_metadata_audit` to
`0009_blog_strategy` on `0008_sitemap_audit`.

Alembic model registration, the persistence head, production application composition, centralized
permission mapping, API error codes, migration/model tests, frontend permission contracts, protected
routes, and navigation preserve both modules. The combined private production composition retains
all 10 Sitemap Audit paths and all 14 Blog Strategy paths. No crawl/sitemap semantics, page-evidence
storage, artifact ownership, dependency manifest, or lockfile changed during reconciliation.

The production evidence adapter remains deferred because Phase 21's concrete comparison repository
does not expose the complete stable metadata/provenance provider contract required by BS-01. The
durable workbook adapter remains deferred because artifacts are still owned by crawl job/run foreign
keys. The fixture provider and bounded private XLSX response remain the accepted safe boundaries.

BS-01 is reconciled for merge review after full validation. BS-02 remains unstarted.

Reconciliation validation passed on 2026-07-17: Ruff formatting/lint, strict mypy across 224 source
files, all 1,523 backend tests (1,520 passed and three Windows symlink-capability skips), clean
dependency checks, fresh migration upgrade/downgrade/re-upgrade, application imports, private-route
coexistence, secret/prohibited-artifact scans, frontend formatting/lint/typecheck, all 117 frontend
tests, production build, and dependency audit. The synthetic BeWell export was regenerated and
reopened with one `Blog Strategy` worksheet, 27 columns, nine included rows, filters, frozen header,
no formulas or hidden sheets, formula-injection protection, and safe HTTP(S) hyperlinks.

Known limitations are the fixture-only evidence adapter, non-durable project export download, manual
classification, manual overlap judgment, and the absence of AI, competitor, GSC, research, scoring,
and opportunity-matrix features. These boundaries are deliberate BS-01 scope, not inferred evidence.

## Phase 22 reconciliation

The branch was rebased from accepted BS-01 HEAD `d8743f65831f1c39f9b6e7b07c3c9a03a14b6401`
onto published `origin/main` baseline `93996b9938f23fb5b8dda3b338123e343e1b0245`
(`Add broken-link and redirect analysis`). Both reviewed BS-01 commits remain separate. The Blog
Strategy migration was renamed from `0009_blog_strategy` on `0008_sitemap_audit` to
`0010_blog_strategy` on `0009_broken_link_redirect_analysis`, leaving one linear Alembic head.

Shared Alembic registration, persistence constants, application composition, centralized permission
mapping, API error codes, frontend permission contracts, protected routes, and navigation preserve
Sitemap Audit, Link Audit, and Blog Strategy together. Focused composition coverage asserts all 10
Sitemap Audit paths, all 12 Link Audit paths (14 operations), and all 14 Blog Strategy paths in one
private production application. Frontend navigation coverage asserts all three workspaces coexist.
No dependency manifest or lockfile changed during reconciliation.

The production evidence adapter remains deferred because Phase 22's durable page/link evidence does
not yet expose the complete Blog Strategy intake projection listed above. The durable workbook
adapter remains deferred because artifact records still require real crawl job/run ownership. The
fixture provider and bounded private XLSX response remain the accepted safe boundaries. BS-02 and
Phase 23 work remain unstarted.

Phase 22 reconciliation validation passed on 2026-07-17: Ruff formatting/lint, strict mypy across
232 source files, all 1,554 collected backend tests (1,551 passed and three Windows
symlink-capability skips), focused migration and three-module composition tests, one Alembic head,
clean Python dependency and application-import checks, frontend formatting/lint/typecheck, all 126
frontend tests, production build, clean `npm ci`, and zero high-severity dependency audit findings.
The synthetic BeWell workflow regenerated and programmatically reopened the workbook with one
`Blog Strategy` worksheet, 27 columns, nine included rows, filters, a frozen header, no formulas or
hidden sheets, formula-injection protection, and safe HTTP(S) hyperlinks. Tests remained isolated
from public HTTP, DNS, and third-party services.
