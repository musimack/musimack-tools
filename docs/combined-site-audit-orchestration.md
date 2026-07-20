# Combined Site Audit Orchestration

CSA-04 turns a ready Combined Site Audit snapshot into a durable, restart-safe execution. It reuses
the accepted crawl job/run system, retained page evidence, specialist authorities, CSA-03 aggregate
storage, and authenticated artifact storage. It does not introduce a second crawler or relax URL,
DNS, redirect, robots, timeout, size, concurrency, or scope protections.

## Submission and stage graph

Submission validates the immutable snapshot identity and eligibility, initializes a durable parent,
and submits exactly one crawl request. The request carries accepted tracking-parameter removals and
discovery exclusions from that snapshot into the existing frontier. Each parsed link is normalized
and stripped before frontier identity, then scope and protected fetch controls remain authoritative.
Excluded links are not enqueued or fetched, but their retained link occurrence is projected as a
real discovery with its source, original form, normalized identity, rule provenance, decision, and
unfetched state. Preview samples never enter this path. Repeating the same submission returns the
existing association. A different snapshot cannot replace an active execution.

The ordered graph is:

1. Crawl inventory.
2. URL ingestion.
3. Immutable rule evaluation.
4. Population classification.
5. Existing sitemap and sitemap recommendation projection.
6. Metadata plus optional image/alt, structured-data, and link-related evidence.
7. Issue aggregation and explainable priority.
8. Summary projection.
9. Artifact generation.

Each stage records dependencies, whether it is required, attempt/checkpoint counts, source and
projected counts, lease evidence, and safe failure details. Required failures affect the parent;
optional failure or unavailable depth stays visible at module level. Partial evidence stays partial.

## Evidence, decisions, and populations

Ingestion preserves original, requested, normalized, and final URLs; stable discovery sequence;
fetch/status/content evidence; directives; metadata; and safe evidence identifiers. Repeated
discoveries are deduplicated as sources. No response body or raw HTML is copied into CSA storage.

Rules come only from the immutable submitted snapshot. Stored matches retain layer, precedence,
specificity, action, reason, contributing/conflict evidence, and both pre/post-normalization URL
forms. The result drives overlapping discovery, metadata-scoring, and sitemap-policy decisions.
Populations deliberately overlap and distinguish fetched HTML, resources, excluded, redirect,
canonicalized, noindex, robots-blocked, unfetched, partial, and indeterminate evidence.

## Specialists, issues, and priority

Base crawl evidence supplies metadata, image/alt, and structured-data projections when available.
Existing-sitemap membership comes only from the Sitemap Audit authority: retained documents,
indexes, parent/child relationships, entries, parse/fetch state, and partial/failure evidence. A
linked child is preferred, otherwise an exact-run eligible prior audit may be reused; a new child is
launched by the worker when the immutable configuration authorizes it. Stale, incompatible, failed,
or missing evidence is explicit and recommendation counts never substitute for membership.
Sitemap-only entries become source-backed inventory discoveries, remain unfetched, and retain
scope/governance decisions.

Metadata, existing sitemap, broken links, internal links, images/alt, and structured data all use
the same durable specialist-association record. Selection records source kind, identity,
eligibility, freshness, lifecycle, partial state, and evidence count without copying specialist
artifacts or deep findings. Restart and retry reuse a valid association instead of launching a
duplicate. Required specialist failure affects the parent; optional failure or unavailability is a
warning/partial condition. Base-evidence fallbacks remain explicit.

Findings are grouped by stable code/category/severity and retain unique memberships and bounded
samples. Priority is a deterministic tuple derived from severity, security protection, affected
population, business importance, confidence, and stable identity. The human-readable explanation
records those inputs; no opaque numeric override is accepted.

## Artifacts

The first release produces deterministic executive Markdown, page inventory CSV, safe evidence
JSON, grouped issues CSV, sitemap comparison CSV, excluded URLs CSV, applied rules CSV, sitemap XML,
action plan CSV, and configuration snapshot JSON. Each association records purpose, schema,
completeness, rows, truncation, and the authenticated artifact identity. Stable filenames plus
existing associations make retry idempotent. Artifacts are bounded and exclude bodies, raw HTML,
credentials, unrestricted headers, and local paths.

## Recovery, cancellation, and retry

Every durable worker polling iteration first runs a stable, bounded parent scan. It renews active
crawl leases, observes crawl and specialist lifecycle changes, recovers expired stages, resumes
ingestion, rebuilds missing summaries, and generates missing artifacts. A web or worker restart
therefore reloads the parent, stages, crawl and specialist associations, and projections without a
manual call. Each iteration handles at most 25 parents; repository scans, evidence ingestion,
specialist associations, and artifacts retain their existing bounds and stable ordering. Repeated
scans are idempotent. A failed scan preserves checkpoints and projections, records a safe
recovery-required error, and stops automatic retry after the accepted bound.

The private reconcile operation remains an administrative diagnostic and repair tool. Ordinary
completion does not depend on it. Summary rebuild aggregates normalized records, and artifact
generation skips already-associated current purposes.

Cancellation is recorded on the parent and propagated to the accepted crawl. Retry is permitted
only for recoverable terminal/recovery states and increments bounded retry evidence; it never
creates another crawl for the same snapshot. Recovery and error messages use stable codes and omit
database, filesystem, and payload internals.

## Security and phase boundary

Routes exist only at `/api/internal/v1/site-audits/{audit_id}/...` in an explicitly injected private
composition. Reads require run-view permission; execution and reconciliation require job-submit;
cancellation requires job-cancel. Queries are bounded to 500 rows, public aliases are absent, and
the default application stays health-only.

CSA-05 owns the complete browser wizard and results interface. CSA-06 owns controlled fixture and
explicitly authorized real-site acceptance. CSA-04 adds no manual sitemap or priority override and
its automated validation uses no public HTTP or DNS.
