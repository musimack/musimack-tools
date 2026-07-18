# Foundation Architecture

## Phase 26 migration QA boundary

Website migration QA is an opt-in layer over durable crawl evidence. The domain owns versioned mapping, finding, recommendation, readiness, pagination, and export policies; persistence owns 11 normalized `migration_*` tables under revision `0013_website_migration_qa`; the private API owns `/api/internal/v1/migrations/qa`; and the protected React workspace owns presentation. The layer has no network adapter and cannot mutate a live site. Planned redirect-map values and observed crawl values stay separate in storage, API projections, and exports.

## Phase 25 structured-data evidence and analysis boundary

Phase 25 extends the accepted HTML parser and page-evidence transaction with bounded, inert JSON-LD, Microdata, and RDFa blocks. Migration `0012_structured_data_audit` stores immutable crawl evidence plus derived blocks, entities, properties, references, duplicate groups, page summaries, findings, versioned profile observations, recommendations, exports, and lifecycle events. No second parser, crawler, network client, or markup execution path exists. The private API is mounted solely below `/api/internal/v1/audits/structured-data`. See [structured-data-audit.md](structured-data-audit.md) and [ADR 0071](decisions/0071-durable-structured-data-evidence-and-audit.md).

## Phase 24 image-evidence and analysis boundary

Phase 24 extends the accepted HTML parser and page-evidence transaction with bounded image occurrences; it does not introduce a second parser or crawler. Migration `0011_image_alt_text_audit` stores that immutable occurrence authority plus derived resources, occurrence analyses, duplicate groups, page summaries, findings, recommendations, exports, and lifecycle events. Resource resolution prefers retained evidence and may use only an injected adapter over the accepted safe-fetch boundary. The private API is mounted solely below `/api/internal/v1/audits/images`. See [image-alt-text-audit.md](image-alt-text-audit.md) and [ADR 0070](decisions/0070-durable-image-evidence-and-audit.md).

## Phase 22 link-audit boundary

Phase 22 narrowly extends terminal page-evidence persistence with parser-owned source-link occurrences. Its analysis service reads only persisted links, pages, redirect hops, and the original scope snapshot; it does not own network or HTML parsing. Migration `0009_broken_link_redirect_analysis` stores derived targets, chains, findings, recommendations, exports, and lifecycle events. The private API and protected frontend reuse accepted authentication, authorization, pagination, artifact, and route-composition authorities.

## Phase 23 internal-link graph boundary

Phase 23 consumes the Phase 22 source-link authority and accepted page, redirect, canonical, indexability, scope, seed, depth, and discovery projections. Migration `0010_internal_link_analysis` stores a versioned derived graph and bounded analysis results; source crawl evidence remains immutable. The service owns deterministic metrics and recommendations only, with no network, parser, semantic inference, or live-site write behavior. See [internal-link-analysis.md](internal-link-analysis.md) and [ADR 0069](decisions/0069-durable-internal-link-graph.md).

## Phase 21 existing-sitemap audit boundary

The sitemap-audit service is an opt-in adapter over accepted authorities rather than a second crawler. It resolves a terminal run and durable `crawl_page_evidence`, constructs the run seed's exact-host scope, and sends robots and sitemap requests only through `SafeSingleUrlFetcher`. Its queue is deterministic: explicit, robots directives, common locations, then child references in parent order. Normalized requested URLs prevent repeat fetches; normalized final URLs prevent redirect-alias loops.

The lxml parser has entity resolution, DTD loading, network access, recovery, and huge-tree mode disabled. A byte preflight rejects DOCTYPE and entity declarations. Standard `urlset` and `sitemapindex` roots are supported; imperfect namespaces or XML content types are durable warnings. HTML responses and gzip paths/content are unsupported. Raw response bodies are never persisted.

Migration `0008_sitemap_audit` adds seven normalized tables for audits, documents, entries, findings, comparisons, exports, and events. Comparisons join sitemap URLs to the SHA-256 identity already used by page evidence. The conservative recommendation adapter reuses `include`, `exclude`, `review`, and `indeterminate`; it does not create a competing recommendation authority. Artifact-backed CSV, JSON, and Markdown exports reuse existing integrity, authorization, path-safety, retention, and download behavior.

Twelve operations across ten private paths mount only when an enabled service is supplied to production composition. The default application remains `/api/health` only. Audit reads use `runs.view`; discovery, audit acceptance/execution, and export creation use `jobs.submit`. Retention defaults to 180 days with database cascades and bounded cleanup.

## Phase 20 metadata-audit boundary

`crawl_page_evidence` is the only page authority. The explicit metadata-audit service validates a terminal run, snapshots immutable configuration, evaluates bounded batches, persists pages/issues/groups/summary/events, and then permits bounded exports. Applicability and severity are centralized in the domain; API handlers and the frontend do not recompute them.

The persistence head is `0007_metadata_audit`. Eight audit tables reference jobs, runs, page evidence, and artifacts without storing raw HTML, bodies, complete headers, parser objects, or artifact bytes. Ordering identifiers are `created_at_desc_audit_id_desc-v1`, `highest_severity_desc_url_identity_asc-v1`, `severity_desc_category_asc_code_asc_url_identity_asc-v1`, and `member_count_desc_group_id_asc-v1`.

Ten internal operations mount only when explicitly enabled. The default application remains health-only. No scheduler, background audit worker, public route, WebSocket, SSE, Docker, CI, cloud, Redis, or PostgreSQL boundary is introduced.

## Repository and product boundary

`musimack-tools` is a standalone repository and application. It is not a package, worktree, or
subproject of any previous Musimack repository. The chosen direction is a monorepo so the API,
future frontend, documentation, and later deployment configuration can evolve under one
reviewable version boundary while remaining internally separated.

## Current implementation

The implemented foundation is backend-only. Python 3.14, FastAPI, Pydantic, and Pydantic
Settings provide a typed application boundary. The FastAPI composition root exports both a
testable `create_app` factory and a stable `app` instance. The only public operation is the
minimal `/api/health` endpoint.

The backend uses a `src` package layout:

- `api` owns HTTP delivery contracts.
- `core` owns typed process configuration.
- `domain` owns framework-independent value objects and evidence types.
- `crawl` owns normalization, scope, safe fetching, and pure HTML extraction services.

These dependencies point inward: HTTP delivery can use domain and crawler-core contracts, but
the crawler core does not depend on FastAPI.

## Safe fetch boundary

The second backend batch adds an internal asynchronous GET boundary without exposing a new API:

- `crawl/dns.py` defines an injectable async resolver and a system implementation that
  deduplicates IPv4/IPv6 answers and enforces a bounded answer count.
- `crawl/safety.py` independently evaluates scheme, credentials, hostname class, IP-literal
  policy, effective port, and every resolved address.
- `crawl/redirects.py` recognizes 301, 302, 303, 307, and 308 and normalizes `Location` values
  against the current request URL.
- `crawl/fetcher.py` coordinates scope plus safety approval, explicit HTTPX timeouts, streaming
  byte limits, minimal transport retries, concurrency semaphores, and manual redirect handling.
- `domain/fetching.py` owns immutable request, DNS, safety, response-header, redirect-hop,
  result, outcome, and failure-code evidence.

HTTP transport, DNS resolution, monotonic time, retry sleep, and settings are injected or
replaceable. The fetcher has no dependency on FastAPI requests, databases, frontend schemas, or
global mutable crawler state. A future frontier can schedule this layer but must not bypass it.
The application logging policy keeps HTTPX's query-bearing request logger at WARNING while the
fetcher emits query-redacted, consistently keyed application events.

Redirects are intentionally manual so every target is normalized, checked against crawl scope,
resolved again, evaluated for network safety, bounded by hop count, and recorded before another
GET is sent. Final response bodies are retained only when fully within the configured byte
limit; no HTML interpretation occurs.

The fetcher is not exposed as a public endpoint. Publishing arbitrary URL input at the API
layer before authentication and higher-level crawl controls would create an avoidable SSRF
surface. `/api/health` remains the only product endpoint.

Pre-request DNS validation does not prove which peer address HTTPX ultimately connects to.
The current transport cannot cleanly pin its connection to the validated answer while
preserving host/TLS semantics. Production use therefore requires deployment-level egress
restrictions, and the injected resolver/transport seam is retained for future peer pinning.

## HTML extraction boundary

The third backend batch adds a synchronous, network-free parsing boundary after fetching:

- `domain/html.py` defines immutable parse outcomes, encoding evidence, text and URL
  observations, canonical/base evidence, robots directives, link records, and warnings.
- `crawl/html.py` gates response evidence, selects and records character decoding, invokes
  Beautiful Soup with lxml, extracts metadata, resolves URL references through the accepted
  normalizer, and optionally evaluates links through an existing scope policy.

`HtmlMetadataParser` consumes one completed `FetchResult`; it does not import the fetcher, DNS,
FastAPI, persistence, or frontend state. Failed, truncated, empty, non-success, and clearly
non-HTML responses receive typed skipped outcomes. Successful parsing does not mutate the fetch
evidence or perform another request.

All title, description, canonical, and base observations remain available in document order.
A canonical is selected only when all valid normalized candidates agree. The first valid base
element becomes effective for subsequent canonical and link resolution; invalid earlier bases
remain evidence and do not prevent a later valid base from becoming effective. Link records are
returned in document order without global deduplication or queueing.

Warnings are stable evidence with severity, safe observed context, and an occurrence index when
practical. Metadata quality thresholds are review aids, never indexability or sitemap decisions.
The parser emits query-free summaries only and is intentionally not exposed through FastAPI.
A future crawl frontier may pass each successful bounded fetch into this layer, but must own
scheduling, deduplication, and admission separately.

## In-memory crawl orchestration boundary

The fourth backend batch composes the accepted fetch and parse boundaries without changing them:

- `domain/crawl.py` owns immutable crawl requests, lifecycle states, URL records, discovery
  decisions, counters, progress snapshots, limit events, cancellation evidence, and results.
- `crawl/frontier.py` owns deterministic normalized-URL deduplication and pending ordering.
- `crawl/limits.py` validates caller-selected bounds against immutable server hard maxima.
- `crawl/cancellation.py` supplies a small injectable cooperative-cancellation protocol.
- `crawl/orchestrator.py` coordinates frontier batches, fetch workers, HTML parsing, link
  admission, pacing, progress observation, and terminal evidence.

The frontier is breadth-first by best-known depth and stable discovery order. Only one depth is
active at a time; URLs at that depth may fetch concurrently up to the validated per-crawl worker
limit. Results are processed in frontier order so network completion order cannot change link
admission order. Request starts for the same normalized origin are separated by the configured
minimum delay. Different origins pace independently.

The orchestrator depends on narrow fetcher and parser protocols rather than their concrete
implementations. Tests inject a fake fetcher, clock, sleep function, cancellation token, and
observer. Production composition can use `SafeSingleUrlFetcher` and `HtmlMetadataParser`, so every
actual request still passes the existing scope, DNS, address, redirect, timeout, and byte controls.

Cancellation is cooperative: active awaits are allowed to return, their evidence is retained, no
new fetch is started after cancellation is observed, and remaining pending entries become typed
skips. Observer failures are recorded but isolated from workers. Unexpected worker or parser
exceptions become controlled crawl errors and a failed terminal result rather than escaping with
partial mutable state.

All crawl state is process memory. There is no durable job identity, restart recovery, public crawl
endpoint, progress stream, persistence repository, or export consumer. Those boundaries must be
added separately rather than embedded in the frontier.

## Robots and indexability boundaries

The fifth backend batch adds two independent evidence layers:

- `domain/robots.py` owns robots retrieval, parse, group, rule, warning, origin, and permission
  records.
- `crawl/robots.py` owns bounded parsing, origin URL construction, safe-fetch retrieval,
  user-agent selection, rule matching, and per-crawl caching.
- `domain/indexability.py` owns ordered header records, warnings, and conflicts.
- `crawl/indexability.py` parses repeated X-Robots-Tag values and combines them with existing meta
  robots records without producing a verdict.

`RobotsTxtService` is a session factory. Each orchestrator run creates a fresh session containing
an injected cache and an async-safe in-flight task map. The first lookup owns retrieval; concurrent
lookups for the same origin await that task and report cache-hit evidence. Every terminal result,
including missing, forbidden, temporary failure, invalid response, and oversized content, is cached
for the rest of that crawl. Nothing persists across crawls.

The robots session factory is a required `SingleSiteCrawlOrchestrator` constructor dependency.
Production composition must explicitly inject `RobotsTxtService`; the orchestrator has no implicit
allow-all fallback. Tests unrelated to robots may explicitly inject a named, test-module-only
allow-all implementation that is unavailable from production composition modules.

The robots service depends only on the accepted safe-fetch protocol. It constructs
`scheme://host[:port]/robots.txt`, so non-default ports identify independent origins. Robots
redirects remain under the existing scope, redirect, DNS, address, port, timeout, and response-size
controls. The service rejects a body above its additional robots limit and never interprets HTML.

The orchestrator requests robots permission before each frontier URL. A denied URL becomes a
terminal URL record without a page fetch. Origin evidence is shared through the crawl result rather
than copying the robots body into every record. Robots bytes count in the aggregate limit and in a
separate counter. Allowed page responses receive X-Robots evidence and a combined meta/header view;
neither changes link admission.

Crawl permission, page indexability evidence, and future sitemap eligibility remain separate types.
No public route exposes any of these internal services. `/api/health` remains the only API path.

The accepted page fetcher handles its own redirect sequence. Consequently, the orchestration layer
cannot run a robots callback immediately before each page redirect hop without changing that
contract. It evaluates the frontier URL origin before calling the fetcher, while the accepted
fetcher continues to revalidate network safety and crawl scope for every redirect target. Future
transport work may add a robots redirect-policy callback while preserving existing redirect
evidence. Similarly, the
robots-specific body limit is an evidence-level rejection layered inside the fetcher's existing
streaming hard cap.

## Sitemap recommendation boundary

`domain/sitemap.py` owns immutable recommendation states, determinacy, rule results, bounded
evidence summaries, typed policy, counters, and crawl-level projection records.
`recommendation/rules.py` owns deterministic mappings and accepted exclusion-rule matching.
`recommendation/sitemap.py` owns ordered rule orchestration and projection aggregation. These
modules depend on accepted crawl evidence but do not modify the crawler, fetcher, parser, robots
service, FastAPI composition, or persistence boundaries.

The rule engine is pure apart from safe keyed logs. Its state precedence is hard exclusion,
indeterminate, review, then include. Primary reasons follow URL and scope, robots permission, fetch
outcome, redirect source, status, HTML content, generic indexability, configured exclusions,
canonical target, and evidence-quality order. Every rule result remains attached even when an
earlier reason controls the final state.

The projection consumes a complete `CrawlResult`, preserves first crawl-record order, suppresses
duplicate normalized identities, and aggregates state, reason, metadata warning, redirect,
canonical, noindex, robots, content, and status counts. A redirect final URL is independently
eligible only when it has its own qualifying crawl record. Otherwise no target recommendation is
created; the excluded source retains a warning that independent target evidence is absent.

`SITEMAP_RULE_SET_VERSION` in `domain/sitemap.py` is the single code authority for
`sitemap-eligibility-v1`. Policy defaults and projections reference that constant rather than
repeating an independent implementation literal. Determinacy answers whether evidence was
sufficient and coherent: include, exclude, and review are `determinate`; indeterminate results are
either `blocked_missing_evidence` or `blocked_conflicting_evidence`.

This boundary does not serialize XML or CSV and is not exposed through FastAPI. Future manual
overrides must be a separate layer over automatic recommendations so original rule evidence remains
auditable. Future XML and CSV consumers should read recommendation projections without embedding
eligibility logic in serializers.

Recommendation logs use bounded URL summaries without queries and include state, primary reason,
status, and rule-set version. They never include bodies, raw HTML, credentials, cookies, or request
headers.

## In-memory XML sitemap serialization boundary

`domain/sitemap_xml.py` owns immutable entries, documents, index records, rejections, warnings,
split evidence, counters, and the generated bundle. `sitemap/limits.py` owns validated protocol
limits and logical naming. `sitemap/xml.py` is a pure in-memory consumer of
`SitemapRecommendationProjection`; it has no dependency on FastAPI, networking, crawl services,
persistence, or the file system.

The serializer accepts only final `include` states and preserves projection order. It does not
re-evaluate robots, noindex, canonicals, redirects, scope, metadata, or any other eligibility
evidence. Exact duplicate URL strings are suppressed first-occurrence-first, while impossible
included URL values become ordered typed rejections without changing the recommendation source.
All output records and the full effective configuration snapshot are immutable.

The stable `sitemap-xml-v1` format emits deterministic UTF-8 bytes with the standard namespace,
fixed readable indentation, LF newlines, and a final newline. URL documents contain only `loc`.
The split algorithm measures complete encoded documents, including wrappers and escaped content,
before accepting the next entry. Defaults enforce 50,000 URL entries and 50 MiB per URL document,
50,000 references and 50 MiB per index, and 2,048 characters per location.

One document is logically named `sitemap.xml` and has no index. Multiple documents use stable
one-based names. With an explicit normalized `sitemap_base_url`, their ordered public locations
form one sitemap index. Without that base, documents are still returned and index generation is
blocked with typed evidence. Index-capacity excess is likewise explicit; recursive indexes are not
created. Zero eligible URLs produce one valid empty URL-set document.

A future publication boundary may write or serve the immutable bytes, a future persistence layer
may retain bundle evidence, and a future submission layer may transmit published locations. None
of those responsibilities, nor a public XML route, exists in this layer.

## Sitemap publication and orchestration boundaries

`domain/sitemap_publication.py` owns immutable configuration, manifest, plan, integrity, failure,
file-result, and publication-result contracts. `domain/sitemap_orchestration.py` owns the typed
service request and aggregate result. The centralized versions are
`sitemap-publication-manifest-v1` and `sitemap-publication-v1`.

`sitemap/manifest.py` is a pure consumer of an immutable XML bundle. It hashes exact XML bytes and
produces deterministic UTF-8 JSON with sorted keys, two-space indentation, LF newlines, and a final
newline. It lists URL documents and then the optional index. It does not list or recursively hash
itself; its byte count and SHA-256 remain separate result evidence.

`sitemap/publication.py` separates planning from mutation. The planner validates the explicit
absolute root, link-free containment, safe simple filenames, case-folded collisions, existing
targets, and conflict policy before returning an immutable plan. Dry run stops after this shared
planning path. The executor can create an explicitly permitted directory, writes secure random
temporary files inside the target directory, flushes and `fsync`s content, and commits each file
atomically. Race-safe no-overwrite uses same-filesystem hard-link creation; overwrite uses atomic
replacement. If no-clobber hard-link creation is unsupported, denied, or otherwise fails, the
executor returns a distinct typed failure, removes the temporary file, and never degrades to
replacement. If a target appears after planning, hard-link creation preserves it and returns
`target_exists`. Exact bytes are read back and hash-verified.

Package preflight prevents expected partial writes, but the package is not a filesystem
transaction. If a later atomic write fails, earlier published files remain and the result becomes
`partially_failed`; temporary files are cleaned and no attempt is made to delete pre-existing user
files. Unrelated files are never traversed, cleaned, or replaced. Link components are checked at
planning and again before execution, but application-level path checks cannot eliminate every race
with an adversary who can concurrently replace output-directory ancestors. Production operators
must restrict write access to the configured root and its parents.

The standard-library classifier rejects symbolic links and Windows junctions for roots, ancestors,
and targets. Platform-neutral flag tests cover both classifications. Windows junction root and
ancestor tests create only local temporary junctions and do not require symlink privilege. Symlink
tests use a minimal creation probe and skip only for recognized capability or privilege errors;
production assertions execute outside the skip-catching block. Other Windows reparse-point kinds
not surfaced by `Path.is_symlink()` or `Path.is_junction()` are not claimed as covered.

`sitemap/service.py` composes recommendation projection, accepted XML generation, publication
planning, and optional execution without duplicating their rules. Explicit states distinguish
generated output, publication not requested, dry run, published, blocked, and partially failed.
The service has no FastAPI, crawl, network, persistence, or submission dependency. Future UI, API,
job, and persistence layers may consume these immutable results but must not move their concerns
into this internal boundary.

## Internal crawl-run composition

The `domain/run*.py` records and `run/` package form an application-service layer above the
accepted crawler, recommendation engine, XML generator, publication planner, and publication
executor. This layer delegates every domain decision; it does not normalize again, recalculate
eligibility, rebuild XML, or bypass filesystem planning. Its stable orchestration version is held
once in production source and flows into requests, identity, results, summaries, and tests.

The dependency graph is `crawl -> recommend -> generate_xml -> (plan_publication | publish)`;
`write_summary` is independent after the run has useful or partial evidence. Each requested stage
has its own pending, running, completed, completed-with-warnings, blocked, cancelled, or failed
state. The run reconciles those records into completed, completed-with-warnings, cancelled, failed,
or partially-completed outcomes. Earlier immutable outputs remain attached after every downstream
failure.

Progress is an injected async sink receiving immutable, monotonically numbered events. No-op,
recording, and callback sinks are available. Sink failure is evidence, not control: the first
failure becomes a warning and later delivery is suppressed. Crawl final counts are projected into
run progress. The service also supplies a per-crawl observer override to the accepted crawler and
translates every live snapshot into run-level `crawl_progress` in callback order. The constructor's
default observer is unchanged. A final event is emitted only when the last callback differs from
the authoritative `CrawlResult`. Cancellation uses the accepted shared cooperative token and is
checked at stage boundaries; its event follows previously delivered crawl snapshots. There is no
thread termination, task killing, or process-global registry.

`run/identity.py` hashes canonical JSON containing only portable configuration. `run/summary.py`
serializes deterministic JSON and Markdown in memory, then optionally writes the two fixed files
through the accepted atomic writer and link classifier. Sitemap packages and operational summaries
remain separate artifacts linked only by run ID. Publication stays per-file atomic; the current
synchronous package executor cannot offer a cancellation checkpoint between its files.

The boundary is intentionally not reachable from FastAPI. A future API/job layer will own request
adapter will own public request admission and delivery. Persisted progress and restart recovery
remain future work. A future
persistence layer may store immutable summaries and stage evidence. Neither concern belongs in the
current in-process service.

## Process-local job manager

The job layer sits above, and does not reinterpret, `CrawlRunService`. Immutable contracts in
`domain/job.py` and `domain/job_registry.py` describe submissions, snapshots, progress, retained
results, coordination evidence, policies, counters, and shutdown. `jobs/identity.py` derives an
attempt identity from the accepted deterministic run ID. `jobs/registry.py` owns mutable
process-local state, `jobs/service.py` is the framework-independent facade, and
`jobs/coordinator.py` defines the injected run-service factory boundary.

One `asyncio.Lock` serializes admission, attempt allocation, queue transitions, progress updates,
completion, retention, and snapshot creation. It is never held across run execution or a caller
wait. Active jobs are bounded exactly, queued jobs use a bounded FIFO `deque`, and completion starts
the next entry. Each job owns one cancellation token and completion event. Frozen snapshots expose
tuples and records, never locks, events, tokens, or tasks.

A job-specific progress adapter updates the latest event and optional bounded history. Unexpected
progress-storage failures become safe coordination warnings and do not fail the run. Unexpected
run-service exceptions become typed job failures, and queue processing continues. Final run
lifecycle maps deterministically to distinct terminal job states.

Terminal records use monotonic completion order and oldest-first bounded eviction. Full-result,
summary-only, and metadata-only policies do not mutate accepted results. Shutdown stops admission,
either cancels queued work and requests active cooperative cancellation or drains accepted work,
then awaits every tracked coordinator task. Registry state disappears at process exit and cannot
coordinate multiple processes.

The accepted internal API translates these contracts into HTTP without moving execution rules
into route handlers, and the explicit production factory wraps it in the bounded security layer.
Persistence, restart recovery, external workers, and distributed coordination remain separate
boundaries.

## Internal application-service boundary

The `domain/application.py`, `domain/capabilities.py`, and `domain/diagnostics.py` records define a
portable boundary above the accepted job manager. The `application/` package owns profiles,
preparation, validation, advisory preflight, readiness, capabilities, projections, diagnostic
serialization, and facade composition. It does not own crawling, scheduling, eligibility, XML,
publication execution, or run lifecycle.

The application boundary is versioned as `seo-toolkit-application-service-v1`; deterministic
portable diagnostics use `seo-toolkit-diagnostics-v1`.

Raw requests contain operator-oriented seed, scope, profile, bounded overrides, stage intent, and
optional local-output configuration. `ApplicationRequestPreparer` normalizes through accepted URL
and scope utilities, applies immutable profile defaults, rejects overrides outside configured and
absolute maxima, constructs existing domain configurations, and computes the accepted run ID. Raw
requests never become job submissions before this validation succeeds.

Validation is pure and deterministically ordered by error, warning, then information severity.
Preflight reads immutable registry snapshots and status records, and uses the accepted link-path
classifier for output roots. It creates no directories or files, allocates no attempt, and reserves
no capacity. Queue and duplicate findings are advisory because registry state can change before
authoritative submission.

`SeoToolkitApplicationService` composes `InternalJobService`; it does not add another scheduler.
Status projection consumes the immutable job snapshot and latest bounded progress. Result
projection consumes the retained job result and emits only counts, lifecycle/stage states, stable
codes, logical filenames, hashes, and versions. Detailed crawl records and payload bytes stay
behind the accepted internal job result contract.

Readiness distinguishes ready, degraded, and not-ready checks. Capabilities are declared as stable
typed constants and never inferred by runtime filesystem scanning. Diagnostics serialize bounded
records as deterministic sorted UTF-8 JSON or Markdown and redact any defensive `Path` occurrence.
Neither format contains timestamps, stack traces, or a self-hash.

The facade remains internal. The accepted private API and production-security adapter translate
these contracts without moving validation or projections into transport handlers. A CLI or React
frontend, persistence, durable workers, user identity, and public authorization require separate
future boundaries.

## Private internal API adapter boundary

The `domain/api.py` records define the immutable access outcomes, error codes, adapter
configuration, route prefix, and centralized `seo-toolkit-internal-api-v1` identifier. The `api/`
adapter package owns deny-by-default access composition, bounded Pydantic schemas, explicit domain
mapping, structured HTTP errors, and route handlers. Business validation, preflight, submission,
job coordination, and projections remain owned by the application and job layers.

`create_internal_api_router()` requires an injected application-service port and immutable API
configuration. `mount_internal_api()` is the only production composition helper and returns
without mounting when `mount_internal_routes` is false. The normal `create_app()` does not call it,
so the default process remains health-only and its OpenAPI document contains no internal paths or
schemas. Router construction creates no registry, task, singleton, or background work.

Mounted routes share a router-level access dependency. No verifier means deny all; verifier
exceptions and unavailable decisions fail closed. Access is checked before handler service calls,
so denial cannot allocate attempts, inspect jobs, cancel jobs, reserve capacity, or reveal job
existence. The verifier is deployment-injected and may inspect the framework request, but its
decision contract contains only a safe optional caller identifier. This access gate is explicitly
not full authentication or authorization.

Request schemas expose only accepted operator-facing fields and convert them to
`RawApplicationCrawlRequest`. Mapping back to HTTP is explicit and bounded: registry responses are
counts-only, progress defaults to latest-only, and results contain counts, codes, logical names,
and hashes rather than lower-layer dataclasses or payload bytes. Pydantic request errors, known
adapter outcomes, and unexpected exceptions use one versioned safe envelope. Unexpected errors
remain available to normal server logging while clients receive no raw exception text.

Future public or broader deployment requires user-aware authentication and authorization,
reverse-proxy/TLS, request-body enforcement, network policy, and rate-limit decisions. Persistence,
durable workers, frontend delivery, streaming progress, and download endpoints remain separate
boundaries.

## Internal security and production deployment boundary

`domain/security.py` and `domain/deployment.py` define frozen records for the
`seo-toolkit-security-v1` and `seo-toolkit-production-app-v1` contracts. Environment-backed
`ProductionSettings` is read only when explicit production composition is requested. The bearer
credential uses Pydantic's secret type, has no default, and never enters a domain report.

`BearerAccessVerifier` implements the existing access-verifier protocol without moving
authentication into route handlers. It strictly parses one bearer header, compares with
`hmac.compare_digest`, resolves client evidence through the trusted-proxy boundary, applies an
optional trusted-network allowlist, and returns the accepted bounded caller context. Missing,
malformed, invalid, unavailable, and network-denied cases fail closed with stable safe responses.

`create_production_app()` is separate from the health-only `create_app()`. It requires an injected
application service, validates configuration before building the app, explicitly mounts the
accepted ten-route adapter, and composes correlation, optional CORS, access logging, and security
headers. It creates no registry, service, task, or secret at import time. OpenAPI is disabled by
default and internal schemas appear only when explicitly configured.

The middleware boundary uses request-local context for correlation and request state for safe
authentication evidence. Access events log route templates rather than query-bearing URLs and
never log headers or bodies. Security headers are deterministic; HSTS is deferred to a future
TLS-aware deployment boundary. CORS accepts exact internal origins only and handles preflight
without invoking the application service.

Forwarded headers are untrusted by default. One bounded `X-Forwarded-For` chain is considered only
when the direct peer is in an explicit proxy CIDR. This application-level check cannot establish
TLS, configure a reverse proxy, or prevent direct network access around that proxy; deployment
egress/ingress controls and topology-specific verification remain required. Future work also owns
managed secrets, credential rotation, users, roles, persistent sessions, and public authorization.

## Future boundaries

### Frontend

The private static frontend uses React, strict TypeScript, and Vite under `frontend/`. A narrow
native-fetch adapter owns `/api/internal/v1` request construction, `credentials: include`, response
validation, and safe error normalization. Authentication state is explicit: `initializing`,
`authenticated`, `unauthenticated`, `expired`, or `unavailable`. No token, password, or parsed
cookie enters browser persistence.

Central route metadata maps protected pages to the exact backend permission vocabulary and drives
both route guards and navigation. This improves the experience but does not replace backend
authorization. Vite serves only local development on loopback and proxies `/api` to a separately
running local backend. Production static hosting, TLS, origin policy, CSP, and reverse-proxy
topology are separate deployment boundaries; FastAPI does not serve the built frontend.

The development proxy keeps browser API requests same-origin. Direct CORS is not required for that
topology. If enabled for local diagnostics, the backend must allow only the exact
`http://127.0.0.1:5173` origin with credentials; wildcard credentialed CORS remains invalid. The
session cookie stays HttpOnly and scoped to `/api/internal/v1`; production retains Secure and
SameSite=Strict behavior.

### Reusable crawler core

The implemented robots evaluation, indexability analysis, and sitemap recommendation layers remain
behind reusable crawler-core interfaces. Fetch, HTML, and in-memory orchestration boundaries supply
bounded response, redirect, metadata, link, and traversal evidence. Persistence and progress delivery
should remain injected so the core stays reusable by broken-link, metadata, canonical, redirect,
inventory, internal-link, image, schema, indexability, and migration-QA modules.

### Persistence

Persistence is an optional injected record layer. Immutable contracts in `domain/persistence.py`
and repository protocols in `domain/storage.py` remain independent of SQLAlchemy. Typed ORM models,
engine/session creation, mapping, repositories, reconciliation, diagnostics, and cleanup live under
`persistence/`; ORM rows are storage representations and never replace job, run, crawl,
recommendation, XML, publication, or API domain authorities.

No engine or session exists at import time. Explicit startup validates the absolute SQLite path,
creates a short-lived engine/session factory, verifies the migrated schema and effective SQLite
pragmas, reconciles interrupted records, recovers attempt maxima and metadata-only terminal views,
then constructs the in-memory registry with an observer. Each repository operation owns one short
session and transaction. No transaction crosses crawl execution or an awaited network operation.
Persistence failure adds bounded coordination evidence without erasing the in-memory terminal
result.

Alembic revision `0001_persistence` owns the frozen initial schema, `0002_durable_execution` adds
durable coordination, `0003_artifact_storage` adds file lifecycle metadata and histories, and
`0004_history_api` adds nullable historical timestamps plus indexes used by bounded job/run
queries. It does not create duplicate history tables.

### Durable page crawl evidence

Phase 20A inserts a bounded persistence projection between accepted terminal crawl results and
future SEO modules. Existing crawl, fetch, HTML, robots, indexability, and URL-normalization
domains remain authoritative. A single terminal observer projects immutable evidence through
bounded SQLAlchemy batches. There is no competing crawler sink or new run stage.

Revision `0006_page_crawl_evidence` owns page, redirect-hop, parse-warning, summary, and event
tables. Page identity combines run ID, discovery sequence, and normalized requested-URL identity.
Ordering is `crawl_discovery_sequence_asc_url_identity_asc-v1`; opaque cursors bind that ordering
to an exact filter fingerprint.

Only structured accepted evidence is stored: URLs, fetch/status outcome, bounded MIME evidence,
parsed metadata, structured robots/indexability contributions, redirect hops, and safe warnings.
Raw HTML, bodies, complete headers, credentials, cookies, leases, paths, and parser objects are
excluded. Metadata values are capped at 4,096 characters and expose truncation.

Evidence retention is independent from in-memory payload retention. Holds are explicit, cleanup is
dry-run capable and bounded, active runs are protected, and summaries can remain `metadata_only`.
Reconciliation is explicitly invoked, bounded, diagnostic-only, and never performs destructive
repair. No HTTP route or frontend UI is introduced.

## Durable history query boundary

SQLite is the historical source of truth. `SQLAlchemyHistoryRepository` opens a short-lived
session per query and returns frozen DTOs; ORM objects and lazy relationships never leave the
persistence boundary. It reads accepted `jobs`, `runs`, `durable_jobs`, execution attempts,
recovery events, stages, warnings, failures, summaries, and artifact records. The in-memory job
registry is not consulted for historical truth.

`HistoryService` owns page bounds, filter normalization, cursor validation, not-found semantics,
related-record truncation, safe logging, and diagnostics. Its exact contracts are
`seo-toolkit-history-service-v1`, `seo-toolkit-history-api-v1`, and
`seo-toolkit-history-pagination-v1`. Job order is durable created sequence descending then job ID
descending. Run order is the latest persisted job sequence descending then run ID descending.
Under stable data, the cursor predicate prevents duplicates and omissions across pages. Concurrent
inserts sort ahead of an existing cursor and therefore do not disturb continuation; updates to
filter fields may change membership, which is a documented live-query limitation.

History is explicitly composed and disabled by default. Ten routes mount only beneath the existing
authenticated internal prefix. The default application remains health-only. Production without
optional features has 11 paths, artifacts-only 14, history-only 21, and artifacts plus history 24.
History diagnostics include bounded aggregate evidence, current migration/database readiness, and
the process-local time/reason of the last query outcome; diagnostics are operational evidence, not
an alternate source of historical truth.

Availability is explicit: full, metadata-only, result-unavailable, evicted, interrupted, retained,
or artifact missing/expired/deleted. A durable row survives process restart, registry reset, and
terminal payload eviction. Phase 16 remains authoritative for download eligibility and lifecycle.
No projection exposes a root, relative path, hash, lease token, database URL, SQL, or raw error.
`alembic.ini` has no fallback
URL; callers must inject an explicit database URL. Automatic migration is disabled by default and
pending migrations block persistence readiness. Cleanup is explicit and sequence ordered. It never
deletes published XML or summary files.

The database stores metadata and hashes, not artifact bytes, raw bodies, credentials, access logs,
or unrestricted paths. SQLite is supported only for local process durability. A future PostgreSQL
adapter is possible behind the protocols but is not implemented.

### Background jobs

The internal process-local job boundary remains the authority in in-memory mode. In durable mode,
the durable job-service facade persists submissions and SQLite queue rows become the only scheduler
authority; no process-local registry task is created for the same job. FastAPI background tasks do
not become the crawler's execution model.

### Durable execution

The durable domain owns immutable configuration, worker identity, scheduling states, lease
outcomes, recovery reports, retry evaluations, and diagnostics. The durable repository owns short
SQLite transactions for submission sequences, FIFO claims, lease creation, heartbeats, durable
cancellation, terminal transitions, retry availability, and stale recovery. The worker owns only
polling, bounded task concurrency, cooperative cancellation forwarding, heartbeat scheduling, and
invocation of the accepted run-service factory. It does not reimplement crawl or run semantics.

Queue order is based on transactional integer sequences. UTC timestamps provide cross-restart
lease expiry and retry eligibility, but are not the FIFO authority. A retry receives a new
availability sequence and retains the external job ID while creating a new execution-attempt row.
Each claim receives a cryptographically random token and increasing generation. Token plus worker,
job, generation, active state, and expiry fence heartbeat and terminal writes. Lease tokens never
enter API projections or portable diagnostics.

Startup order is persistence readiness, worker registration, stale-lease recovery, ready state,
then polling. Recovery preserves completed stage and artifact metadata but does not restore a crawl
frontier or reuse a task/token. Shutdown stops claims, enters draining, and waits a bounded grace
period, optionally requesting cooperative cancellation. No task starts at import time.

Persistence preparation receives an explicit `durable_queue_authority` selection. Its default is
false and retains legacy in-memory interrupted-job reconciliation. Durable composition sets it true
so that reconciler does not terminalize queued or leased rows before durable stale recovery. This
selection is part of enforcing one scheduler authority and is covered by restart tests.

Production composition remains explicit. Durable mode requires ready current persistence; worker
composition additionally requires an injected run-service factory. The authenticated API can run
without a worker, and a separately composed worker need not expose an API. The default app remains
health-only. This v1 supports one machine and SQLite coordination only; future PostgreSQL, Redis,
distributed fencing, multi-machine supervision, and deployment-specific failover are not present.

### Exports

In-memory XML sitemap serialization and safe local publication are separate consumers of
recommendation projections. CSV audit serialization remains future work. Publication uses the
immutable XML bundle without moving filesystem behavior into the serializer. Authenticated local
artifact retrieval is separate from remote publication and submission, which remain future
boundaries. Optional
`lastmod` remains deferred until trustworthy provenance exists; `priority` and `changefreq` are not
planned defaults. Metadata warnings remain separate from sitemap eligibility.

## Frontend crawl workflow

The React application is a typed presentation adapter over authenticated internal routes. A crawl
request moves through edit, validation, preflight, confirmation, submission, live monitoring, and
terminal result review. React context retains only a bounded list of job identifiers for the
current page lifetime; durable state stays in the backend. Route permissions remain centralized.

Live job listing is a bounded projection on the existing `/jobs` resource. Detailed sitemap
recommendations add one read-only path because the existing aggregate result contract does not
retain per-URL items. That projection is paged and filtered server-side and omits bodies, raw HTML,
tasks, locks, tokens, and filesystem locations. Artifact transfer remains separate from metadata
and requires an explicit browser action.

Polling is recursive rather than interval-based so requests cannot overlap. Queued and active
cadences are fixed, transient failures back off to a ceiling, hidden documents slow down, unmount
aborts in-flight work, and accepted terminal states stop scheduling. Polling is observation only;
it cannot become scheduler, cancellation, or retry authority.

## Why network access is excluded

URL parsing and hostname matching alone cannot make outbound requests safe. Live fetching
requires DNS and connected-address validation, SSRF protections, per-redirect revalidation,
timeouts, byte limits, scope enforcement, robots policy, and bounded concurrency. Implementing
pure normalization and scope policy first makes those later controls testable without implying
that an in-scope string is safe to request.

## Testing strategy

- Unit tests cover normalization, scope, settings, DNS, address safety, streaming limits,
  retries, redirect chains, content gating, decoding, malformed HTML, metadata conflicts,
  base/canonical resolution, robots tokens, links, frontier ordering, admission, limits,
  cancellation, concurrency, pacing, robots parsing and permission, single-flight caching,
  X-Robots directives, combined conflicts, recommendation precedence, canonical and redirect
  policy, duplicate projection, and stable crawl evidence.
- FastAPI's in-process test client covers health, the private adapter, and explicit secured
  production composition, including authentication, proxy spoofing, CORS, correlation, headers,
  startup failure, and log redaction.
- An automatic test fixture blocks DNS resolution and non-loopback socket connections; Windows
  event-loop loopback plumbing remains available to the in-process test client.
- HTTP behavior uses fake resolvers and `httpx.MockTransport`; future tests may use explicitly
  controlled local fixture servers, never public websites.
- HTML parser tests use inline bytes and strings only. The parser has no network dependency.
- Ruff formatting/linting and strict MyPy run alongside Pytest.

## Development and deployment direction

Windows PowerShell is the primary documented local workflow. Repository files use LF endings,
while Git and editors can manage platform checkout behavior normally. All commands run from the
repository root and use `.venv` rather than changing system Python.

Docker-based local and server deployment remains the eventual direction, but Dockerfiles,
Compose, reverse proxies, public/user authentication, managed secret handling, and production
egress controls are explicitly deferred.

## Durable artifact boundary

Artifact bytes remain files beneath explicitly configured local roots; SQLite stores only identity,
root ID, safe relative path, lifecycle, retention, integrity, and history evidence. Root paths are
runtime-only configuration and never appear in API projections. `artifact_records` is the Phase 16
lifecycle authority; the older `artifact_metadata` table remains compatible run-output evidence.

The deterministic layout is `jobs/<job-id>/runs/<run-id>/artifacts/<filename>`. Validation rejects
absolute, drive, UNC, device, traversal, alternate-stream, control-character, reserved-name, and
separator-ambiguous forms. Resolution and link/junction checks repeat immediately before hashing,
streaming, deletion, and reconciliation. Publication and summary writers retain their atomic-write
authority; an optional observer registers successful outputs afterward.

Lifecycle states are planned, available, missing, corrupt, expired, deleted, and retained. Short
database transactions never span hashing, streaming, or filesystem deletion. Cleanup and
reconciliation are explicit bounded operations, not background daemons. Cloud storage, public URLs,
range downloads, artifact blobs, and orphan mutation are excluded.

## Authentication and authorization boundary

Expanded authentication is an explicit production composition over the same SQLite authority. Its
immutable configuration is disabled by default and supports only `shared_bearer`, `user_session`,
and `hybrid`. Existing shared-bearer deployments keep their exact behavior. User-session and
hybrid composition inject the authentication service; imports create no database, user, password,
token, cleanup task, or bootstrap side effect.

`0005_authentication_authorization` follows `0004_history_api` and owns five tables: users,
credentials, authentication sessions, append-only authentication audit events, and bounded login
attempt evidence. Password material is PBKDF2-HMAC-SHA256 with random per-credential salt. A raw
opaque session token exists only at issuance and in the HttpOnly cookie; SQLite stores its SHA-256
hash. Session validation reloads the current user state, role, and revocation generation rather
than trusting the issue-time role snapshot.

One immutable principal crosses the adapter boundary. Central role mappings define the exact
administrator, operator, and viewer permissions, and unknown roles or permissions deny by default.
The shared bearer is an explicit compatibility administrator principal. Route authorization maps
operations to permissions centrally, without caller-supplied privilege lists or handler-level role
comparisons. The 16 auth/user operations remain private; sign-in is the only credential-accepting
route, while every other operation passes the common access and permission gate.
