# Phase 29 human-acceptance review

## Scope and decision

Phase 29 evaluates the internal release candidate: bounded crawling, sitemap generation and
publication, durable jobs/runs/history/artifacts, metadata and sitemap audits, link and internal-link
analysis, image and structured-data audits, website-migration QA, authenticated private operations,
backup/restore, CI, and review-only release-candidate packaging. It adds no product module and does
not include the separate Blog Strategy work.

The release-candidate decision is **ready for human review with documented nonblocking
limitations**, subject to every gate in `release-readiness.md`. This is not authorization to tag,
publish, deploy, migrate a production database, or run a customer crawl.

## Acceptance evidence

- Default composition is now literally health-only: `/docs`, `/redoc`, and `/openapi.json` are not
  mounted. The complete product is available only through explicit
  private composition under `/api/internal/v1`; sign-in is the only anonymous private operation,
  and every protected operation maps to an explicit centralized permission.
- Administrator, operator, viewer, anonymous, invalid-session, revoked-session, expired-session,
  shared-bearer, and hybrid-mode behavior have direct automated coverage. Phase 29 adds durable
  coverage for stale and multiple same-name session cookies.
- The trusted local HTTPS review passed login and role-filtered navigation for administrator,
  operator, and viewer; anonymous protected-route redirection; role denial; refresh-safe durable
  crawl results; restart-safe recommendations and artifact downloads; and direct protected routes.
- Crawl creation, crawl results, recommendations, recommendation detail, Metadata Audit selection,
  and artifacts had no page-level horizontal overflow at 1440, 1024, 768, or 390 CSS pixels. The
  one discovered narrow-screen overflow in a long evidence identifier was corrected and retested.
- Semantic landmarks, headings, form labels, accessible control names, the skip link, mobile menu
  state, and visible focus treatment passed manual smoke review. Detailed boundaries are in
  `accessibility-review.md`.
- The accepted Phase 29 baseline is published with one head,
  `0015_sitemap_recommendation_retention`, with parent `0014_durable_result_projection`; empty and
  existing databases upgrade successfully.
- Offline backup/restore, integrity verification, authenticated restored composition, worker
  lifecycle, reconciliation, retention, and deterministic release-candidate packaging are exercised
  by the operations and release suites and the Phase 29 rehearsal.
- Final local validation passed: Ruff format/lint over 297 files; strict MyPy over 279 source files;
  289 focused Phase 29 backend tests; 2,215 full backend tests with three accepted Windows
  symlink-privilege skips; `pip check`; import/lock/migration/workflow/repository audits; 65 focused
  frontend tests; 22 frontend test files and 253 tests; production build; and both offline npm audits
  with zero vulnerabilities. Phase 29 was later published and its hosted CI passed.

## Role acceptance

| Role          | Read scope                                            | Write scope                   | Administrative scope          | Browser result |
| ------------- | ----------------------------------------------------- | ----------------------------- | ----------------------------- | -------------- |
| Administrator | All accepted resources                                | All accepted workflows        | Users, roles, sessions, audit | Passed         |
| Operator      | Jobs, runs, history, artifacts, diagnostics, settings | Submit and cancel jobs/audits | Denied                        | Passed         |
| Viewer        | Jobs, runs, history, artifacts, diagnostics, settings | Denied                        | Denied                        | Passed         |

## Error, performance, and recovery acceptance

API errors use bounded codes/messages and request identifiers. Authentication failures do not reveal
which credential field failed; unhandled errors are normalized; downloads are revalidated before
streaming. The browser review showed no credential, token, local path, database URL, traceback, or
implementation detail.

Hard limits cover crawl URLs, depth, duration, bytes, redirects, response bodies, concurrency,
queueing, pacing, request bodies, pagination, worker leases/heartbeats, shutdown, and artifact sizes.
SQLite and a single supervised worker are deliberate operating limits, not a clustered deployment
model. Backup is offline with respect to writers and restore is non-destructive into new paths.

## Human decision criteria

Human acceptance requires the green gates in `release-readiness.md`, review of
`security-review.md`, `accessibility-review.md`, and `known-limitations.md`, confirmation that no
blocking item remains, verification of the candidate checksums, and explicit separate authorization
for any later tag, release, migration, or deployment.

The later Combined Site Audit CSA-06 real-site evidence is tracked separately in
`combined-site-audit-csa06-acceptance.md`. Its effective-rule correction is ready for human review,
but this document does not convert that evidence into CSA-06 acceptance or publication authority.

CSA-06 final engineering work now covers deterministic WordPress, Custom, No preset,
parameter-heavy, role, security, responsive, accessibility, recovery, backup/restore, artifact,
performance, error, and data-quality gates. The engineering recommendation is **ready for final
product-owner acceptance**. David's acceptance and any staging, commit, publication, release, or
deployment authorization remain separate and outstanding.
