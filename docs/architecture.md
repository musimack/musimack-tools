# Foundation Architecture

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

The future frontend will use React, TypeScript, and Vite under `frontend/`. This batch creates
no frontend package manifest or dependencies. The frontend should consume a typed client based
on the FastAPI OpenAPI contract and use server-state-oriented data fetching.

### Reusable crawler core

The implemented robots evaluation, indexability analysis, and sitemap recommendation layers remain
behind reusable crawler-core interfaces. Fetch, HTML, and in-memory orchestration boundaries supply
bounded response, redirect, metadata, link, and traversal evidence. Persistence and progress delivery
should remain injected so the core stays reusable by broken-link, metadata, canonical, redirect,
inventory, internal-link, image, schema, indexability, and migration-QA modules.

### Persistence

Persistence is absent. A future boundary may use SQLite initially through typed repository
interfaces and migrations, with PostgreSQL portability retained. API and domain objects should
not acquire SQLite-specific behavior.

### Background jobs

The internal process-local job boundary owns bounded admission, FIFO coordination, cooperative
cancellation, lookup, and bounded retention. A future adapter may add authenticated API delivery;
a future durable worker boundary may add persisted progress and interruption recovery. FastAPI
background tasks should not become the crawler's core execution model.

### Exports

In-memory XML sitemap serialization and safe local publication are separate consumers of
recommendation projections. CSV audit serialization remains future work. Publication uses the
immutable XML bundle without moving filesystem behavior into the serializer. Persistence,
download delivery, remote publication, and submission remain separate future boundaries. Optional
`lastmod` remains deferred until trustworthy provenance exists; `priority` and `changefreq` are not
planned defaults. Metadata warnings remain separate from sitemap eligibility.

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
