# Combined Site Audit persistence

CSA-03 adds the durable, network-free persistence foundation for the Combined Site Audit. The
single migration `0017_combined_site_audit_persistence` follows `0016_site_audit_settings`. It does
not create crawl jobs, launch workers or specialist audits, evaluate retained evidence, generate
artifacts, or add a user-facing audit workflow.

## Aggregate and lifecycle

`site_audits` stores the durable draft and audit identity before any crawl or run exists. Draft
updates use an integer optimistic revision. Lifecycle transitions are checked by the domain layer;
completed, failed, cancelled, and archived records cannot return to draft. Archival is a readable
terminal state and does not delete retained evidence. Run lifecycle, population completeness, and
module completeness remain independent fields.

Optional parent job and crawl-run references use `SET NULL`; removing an execution record cannot
delete the Site Audit. Profile and preset identities are stable historical references rather than
cascading foreign keys, so later profile archival cannot invalidate a submitted audit.

## Immutable configuration

`site_audit_snapshots` stores one canonical submitted configuration per audit, including approved
hosts, scope, limits, thresholds, modules, tracking decisions, profile/preset versions, definition
versions, artifact schema versions, and application/projection versions. Canonical JSON uses sorted
keys and compact separators; SHA-256 protects deterministic identity. Effective rules and disabled
inherited rule identities are normalized into child tables. Repository mutations reject draft or
snapshot changes after the snapshot exists.

## URL evidence and populations

`site_audit_urls` has one row per `(audit_id, normalized_url_identity)` and a stable per-audit
sequence. It can represent a discovered URL that was never enqueued, fetched, or parsed. Exact
original, requested, normalized, and final URL forms remain separate. Repeated observations add
deduplicated `site_audit_url_discovery_sources` rows instead of new inventory rows.

Population membership is normalized in `site_audit_url_populations`. Memberships intentionally
overlap. The executive denominator is reproducible as the intersection of parsed HTML, indexable,
canonical, and metadata-scoring-eligible memberships under the recorded definition version.

## Rules, issues, modules, and summaries

Rule snapshots retain source/version, layer, match semantics, action, override targets, priority,
specificity, explanation, and stable order. URL matches retain primary/contributing/disabled/
overridden flags, conflict evidence, both URL forms, and stable precedence. Findings may be URL- or
audit-level. Issue groups retain the contract grouping identity and explainable priority key; a
complete paginated membership table prevents duplicate finding membership.

Module status is independent of parent lifecycle and uses non-owning specialist identities. Summary
rows durably retain population, severity, recommendation, image, structured-data, and module-count
projections. Rebuilds aggregate normalized rows in one transaction, accept an expected revision,
are idempotent in values, and survive process restart.

Artifact associations link an existing authenticated `artifact_records` row to an audit, purpose,
schema, completeness, row count, and truncation state. The artifact foreign key uses `RESTRICT`.
CSA-03 never creates artifact bytes.

## Bounds, backup, and deferred work

Inventory is capped at 100,000 normalized identities per audit. List reads accept only page sizes
50, 100, and 500 and stable orderings. Tables contain no response bodies, raw HTML, credentials,
unrestricted headers, or filesystem paths. The accepted SQLite backup mechanism copies all CSA-03
tables at the declared Alembic head and validates revision, manifest hashes, and database integrity
on isolated restore.

CSA-04 owns job/crawl and child-audit orchestration, evidence projection, automatic aggregation,
recovery reconciliation, and artifact generation. CSA-05 owns the wizard and result interface.
CSA-06 owns controlled functional and real-site acceptance. Specialist authorities remain intact.
