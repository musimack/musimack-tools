# Combined Site Audit conceptual private API

Status: CSA-01 contract. CSA-02 implements the private settings, preset, profile, rule-validation,
sample-test, effective-settings, and explicitly deferred retained-preview subset. CSA-03 implements
the durable aggregate repositories and projections but deliberately adds no route. Draft, execution,
results, and artifact operations remain conceptual for their owning phases.

Resource family: `/api/internal/v1/site-audits`

This contract follows accepted private API authentication, request correlation, safe error
envelopes, artifact authorization, and durable repository patterns. JSON uses snake_case. IDs are
opaque. Submitted snapshots are immutable.

## Shared behavior

- Read operations require `runs.view`; draft creation/change, validation, preflight, submission,
  cancellation, rule testing, and export creation require `jobs.submit` (and cancellation also
  follows `jobs.cancel`). Profile/global mutation requires `settings.manage`, which is administrator
  only. Artifact reads/downloads use accepted artifact permissions.
- Viewers, operators, and administrators may read audits they are authorized to see. Administrators
  and operators may create/run audits. Only administrators manage profiles and global defaults.
- List endpoints default to 50 rows and accept 50, 100, or 500; 500 is the hard page maximum.
  Opaque cursors bind ordering and filter fingerprints. Responses include `items`, `page_size`,
  `next_cursor`, `total`, `ordering`, and `filters`.
- Mutation requests accept an `Idempotency-Key` (1–128 safe characters). Repeating the key with the
  same principal and canonical payload returns the original result; a different payload returns
  `idempotency_conflict`. Updates also require draft `revision` to prevent lost writes.
- Errors use the accepted envelope and correlation ID. Stable CSA codes include
  `site_audit_not_found`, `site_audit_forbidden`, `site_audit_state_conflict`,
  `site_audit_revision_conflict`, `site_audit_validation_failed`, `site_audit_preflight_failed`,
  `site_audit_not_ready`, `site_audit_recovery_required`, `site_audit_evidence_unavailable`,
  `site_audit_projection_unavailable`, `site_audit_rule_invalid`, `site_audit_rule_conflict`,
  `site_audit_rule_preview_bounded`, `site_profile_not_found`, `site_profile_disabled`,
  `specialist_audit_ineligible`, `pagination_cursor_invalid`, and accepted artifact errors.
- Validation is side-effect-free. Preflight may perform only accepted safe bounded checks and does
  not create a crawl. Submit is the only operation that creates an immutable audit run/job link.

## Resources and operations

| Method and route                                                                   | Permission           | Request/response concept                                                                                | Pagination and idempotency                                |
| ---------------------------------------------------------------------------------- | -------------------- | ------------------------------------------------------------------------------------------------------- | --------------------------------------------------------- |
| `GET /site-audits`                                                                 | `runs.view`          | Filtered audit/history summaries with site, latest state, dates, completeness                           | Cursor; read-only                                         |
| `POST /site-audits`                                                                | `jobs.submit`        | Create draft from seed, optional profile, or explicit blank configuration; returns audit/draft/revision | Idempotent                                                |
| `GET /site-audits/{audit_id}`                                                      | `runs.view`          | Audit identity, current draft if allowed, and immutable run summaries                                   | Read-only                                                 |
| `PATCH /site-audits/{audit_id}/draft`                                              | `jobs.submit`        | Partial wizard fields plus revision; returns normalized draft and new revision                          | Idempotent/revisioned; draft-like states only             |
| `POST /site-audits/{audit_id}/validate`                                            | `jobs.submit`        | Draft revision; returns field/rule errors and effective-settings preview                                | Idempotent; no network                                    |
| `POST /site-audits/{audit_id}/preflight`                                           | `jobs.submit`        | Validated revision; returns safe host/robots/seed reachability and warnings                             | Idempotent; bounded network through accepted fetch safety |
| `POST /site-audits/{audit_id}/submit`                                              | `jobs.submit`        | Ready revision and confirmation; returns audit run and job IDs                                          | Idempotent; immutable snapshot                            |
| `GET /site-audits/{audit_id}/runs/{audit_run_id}/status`                           | `runs.view`          | Lifecycle, run/population/module completeness, job/run references                                       | Read-only                                                 |
| `GET /site-audits/{audit_id}/runs/{audit_run_id}/progress`                         | `runs.view`          | Latest plus bounded progress history and truncation                                                     | Cursor if history is listed                               |
| `POST /site-audits/{audit_id}/runs/{audit_run_id}/cancel`                          | `jobs.cancel`        | Cancellation request/result                                                                             | Idempotent                                                |
| `GET /site-audits/{audit_id}/runs/{audit_run_id}/summary`                          | `runs.view`          | Explicit denominators, priority groups, module summaries, provenance                                    | Read-only                                                 |
| `GET /site-audits/{audit_id}/runs/{audit_run_id}/pages`                            | `runs.view`          | Unified safe page projections; URL/status/population/rule filters                                       | Cursor, max 500                                           |
| `GET /site-audits/{audit_id}/runs/{audit_run_id}/pages/{page_id}`                  | `runs.view`          | Evidence references, decisions, findings, specialist links; no bodies                                   | Read-only                                                 |
| `GET /site-audits/{audit_id}/runs/{audit_run_id}/issues`                           | `runs.view`          | Issue groups, priority inputs, counts and bounded samples                                               | Cursor, max 500                                           |
| `GET /site-audits/{audit_id}/runs/{audit_run_id}/issues/{group_id}`                | `runs.view`          | Group details and paginated membership reference                                                        | Membership uses cursor                                    |
| `GET /site-audits/{audit_id}/runs/{audit_run_id}/sitemap-comparisons`              | `runs.view`          | Existing versus generated state, policy and evidence                                                    | Cursor, max 500                                           |
| `GET /site-audits/{audit_id}/runs/{audit_run_id}/exclusions`                       | `runs.view`          | Layered exclusion decisions and discovery evidence                                                      | Cursor, max 500                                           |
| `GET /site-audits/{audit_id}/runs/{audit_run_id}/applied-rules`                    | `runs.view`          | Primary/contributing matches, conflicts, source/version                                                 | Cursor, max 500                                           |
| `GET /site-audits/{audit_id}/runs/{audit_run_id}/artifacts`                        | `artifacts.view`     | Artifact records, integrity, completeness, expiry                                                       | Cursor, max 500                                           |
| `POST /site-audits/{audit_id}/runs/{audit_run_id}/artifacts`                       | `jobs.submit`        | Requested supported formats; returns accepted artifact records                                          | Idempotent; terminal retained data only                   |
| `GET /site-audits/{audit_id}/runs/{audit_run_id}/artifacts/{artifact_id}/download` | `artifacts.download` | Accepted authenticated download behavior                                                                | Read-only                                                 |
| `GET /site-audits/{audit_id}/effective-settings`                                   | `runs.view`          | Draft preview by revision or immutable run snapshot                                                     | Read-only                                                 |
| `POST /site-audits/{audit_id}/rules/test`                                          | `jobs.submit`        | One rule and up to 100 supplied sample URLs; exact decisions                                            | Idempotent; no discoveries created                        |
| `POST /site-audits/{audit_id}/rules/preview`                                       | `jobs.submit`        | Draft rules against retained eligible evidence                                                          | Idempotent; max 500 matches plus bounded estimate         |
| `GET /site-audits/{audit_id}/eligible-specialist-audits`                           | `runs.view`          | Module/filter-specific identity-compatible audit candidates                                             | Cursor, max 500                                           |
| `GET /site-audit-profiles`                                                         | `settings.view`      | Approved profiles visible for selection                                                                 | Cursor, max 500                                           |
| `POST /site-audit-profiles`                                                        | `settings.manage`    | Create administrator-owned versioned profile                                                            | Idempotent                                                |
| `GET /site-audit-profiles/{profile_id}`                                            | `settings.view`      | Profile, current version, preset pin, enabled state                                                     | Read-only                                                 |
| `PATCH /site-audit-profiles/{profile_id}`                                          | `settings.manage`    | New profile version; never rewrites references                                                          | Idempotent/revisioned                                     |
| `POST /site-audit-profiles/{profile_id}/disable`                                   | `settings.manage`    | Archive/disable profile                                                                                 | Idempotent                                                |

Profile routes share the internal API namespace but are not implemented until CSA-02. An operator
cannot invoke profile mutations even if the UI is bypassed.

## Conceptual payload boundaries

### Draft

The draft contains website seed/approved hosts; optional preset suggestion and explicit acceptance;
optional profile/version; URL governance rules and parameter exceptions; bounded crawl profile and
overrides; modules and specialist links; thresholds; business-importance assignments; and draft
revision. It never accepts a flag that disables protected security.

### Effective settings

The response presents each effective value with `value`, `source`, `source_id`, `source_version`,
`overridden_value` when applicable, and `protected`. Rules include effective and explicitly disabled
inherited entries. Validation/preflight/submission use the same canonical serializer and revision.

### Status and completeness

Status has distinct `lifecycle`, `run_completion`, `population_completeness`, and `modules[]` fields.
Counts include every population named in the product contract. Skips expose safe codes and counts;
they are never inferred solely from lifecycle.

### Safe page and issue projections

Responses may contain bounded metadata, directives, URL/fetch evidence, decision provenance, and
stable evidence references. They never contain response bodies, raw HTML, credentials, tokens,
filesystem paths, unrestricted headers, parser objects, or artifact bytes.

## Draft and legacy behavior

Submitted audit runs reject draft mutation with `site_audit_state_conflict`; a rerun forks their
snapshot into a new draft. Missing/expired projections return an explicit unavailable state rather
than empty success. Older crawl/specialist jobs without CSA snapshots are not silently promoted to
CSA runs, but may be offered as eligible prior evidence when all identity checks pass.

## Conceptual route composition

All routes remain private and mount only when explicitly enabled composition supplies the relevant
CSA service. The default application remains health-only. CSA-02 contributes only its bounded
settings and governance operations; it does not add an audit or execution route.

CSA-03 contributes no route. Its repositories are an injected persistence boundary for later
private services. It adds no public alias and cannot create a crawl, specialist audit, or artifact
through HTTP.

## CSA-04 private execution surface

An explicitly composed orchestration service contributes authenticated operations under
`/api/internal/v1/site-audits/{audit_id}` for submit, cancel, retry, reconcile, status, summary,
modules, pages, issues, rules, artifacts, and summary rebuild. There is no `/api/site-audits`
alias. GET operations require `runs.view`; cancellation requires `jobs.cancel`; other mutations
require `jobs.submit`.

The durable worker advances ordinary parent execution automatically. `reconcile` is retained only
as an authenticated administrative diagnostic/recovery action; clients do not need to call it
after crawl or specialist completion.

Page, issue, and rule queries use non-negative offsets and page sizes 50, 100, or 500. Invalid
bounds use the normal structured validation envelope. Responses contain safe projections and
stable CSA error codes, never database exceptions, response bodies, local artifact paths, tokens,
or arbitrary headers. Submission is idempotent for the audit's immutable snapshot and returns the
existing crawl association when repeated.
