# Musimack SEO Toolkit

## Existing sitemap audits

Phase 21 is implemented for human review, but is not yet accepted. The opt-in private workflow discovers an explicit sitemap, ordered `Sitemap:` directives from `robots.txt`, and `/sitemap.xml`, `/sitemap_index.xml`, and `/wp-sitemap.xml`; it then expands nested indexes through the accepted safe-fetch, DNS, SSRF, redirect, response-limit, URL-normalization, and crawl-scope authorities.

Only standard `urlset` and `sitemapindex` XML are interpreted. DTDs and entity declarations are rejected, missing or nonstandard namespaces are retained as warnings, and gzip decompression remains unsupported. Defaults are 5 MB per response, 50,000 URL-set entries, 50,000 index children, 100 documents, depth 3, and 250,000 unique sitemap URLs. Migration `0008_sitemap_audit` stores normalized documents, entries, findings, comparison decisions, exports, and lifecycle events without raw XML bodies.

The comparison union uses durable crawl evidence plus sitemap inventory and reuses the accepted recommendation states. Stable Add, Remove, Review, and Unchanged results are available only below `/api/internal/v1/audits/sitemaps`; readers require `runs.view`, while discovery, creation, and export generation require `jobs.submit`. CSV, JSON, and Markdown outputs use the existing private artifact authority. The authenticated frontend exposes a separate **Sitemap Audits** workspace.

Authenticated loopback browser QA uses the explicit, network-isolated test-fixture procedure in
[`docs/sitemap-audit-browser-qa.md`](docs/sitemap-audit-browser-qa.md); the default application
remains health-only.

## Metadata audits

Phase 20 adds an opt-in, private metadata-audit product over Phase 20A durable page evidence. An authenticated operator with `jobs.submit` explicitly audits a terminal run; readers use `runs.view`, while export creation and downloads remain within existing artifact permissions. The engine never re-fetches pages or reparses HTML.

The taxonomy covers title, meta description, canonical, robots, indexability, HTTP status, and content type. Title length defaults to 20–60 characters and description length to 70–160 characters; these are configurable heuristics, not search-engine rules. Exact duplicate groups use Unicode NFKC normalization, trimmed/collapsed whitespace, Unicode case-folding, preserved punctuation and stop words, and exclusion of empty values.

Audits persist through migration `0007_metadata_audit`. Private `/api/internal/v1/audits/metadata` routes provide bounded cursor queries and CSV, JSON, and Markdown exports. CSV cells starting with `=`, `+`, `-`, or `@` receive a leading apostrophe before standard CSV escaping. Exports are limited to 100,000 issue rows and registered with the existing artifact integrity/download service.

The Musimack SEO Toolkit is a standalone internal application for reusable SEO analysis
tools. Its first planned module is the **Sitemap Generator and Metadata Crawler**, which will
eventually crawl approved websites, collect response and page metadata, explain sitemap
recommendations, support human overrides, and export XML and CSV results.

## Current application scope

This first implementation batch provides:

- A typed Python 3.14 and FastAPI backend foundation
- Typed, non-secret settings through Pydantic Settings
- `GET /api/health`
- Deterministic, network-free URL normalization
- Exact-host, subdomain, and explicit-approved-host scope evaluation
- Stable scope decision evidence
- A reusable asynchronous single-URL safe-fetch boundary
- Injectable DNS resolution, conservative address safety, and manual redirect evidence
- Bounded timeouts, retries, response bytes, headers, redirects, and concurrency
- Deterministic HTML content gating and character decoding
- Typed title, meta-description, canonical, base, meta robots, and navigable-link evidence
- Stable parse warnings that preserve duplicate and conflicting observations
- A deterministic breadth-first, in-memory single-site crawl frontier
- Bounded asynchronous fetch workers with per-origin request pacing
- Typed crawl progress, cancellation, limits, counters, and URL-level evidence
- Per-origin robots.txt retrieval, parsing, permission decisions, and one-crawl caching
- X-Robots-Tag parsing and combined meta/header indexability evidence
- Pure sitemap eligibility recommendations and deterministic crawl-level projections
- Internal crawl-run composition across crawl, recommendation, XML, and local publication stages
- Deterministic run IDs, ordered progress events, cooperative cancellation, and partial results
- Deterministic JSON and Markdown run summaries with optional safe atomic local writing
- An internal process-local job manager with bounded execution, FIFO queueing, cooperative
  cancellation, progress lookup, and terminal-result retention
- An explicit production application factory with environment-backed internal bearer
  authentication, trusted-network and trusted-proxy policies, request correlation, narrow CORS,
  deterministic security headers, and audit-safe access logging
- Pytest, Ruff, and MyPy validation
- A private React, TypeScript, and Vite frontend foundation with cookie authentication,
  permission-aware routing, responsive accessible pages, and deterministic component tests
- A guided crawl submission, live job monitor, sitemap recommendation review, durable history,
  and explicit retained-artifact download workflow
- Architecture and crawl-policy documentation

It deliberately does **not** provide sitemap fetching, final search-engine-specific indexability
verdicts, public APIs, CSV exports, manual recommendation overrides, sitemap submission, OAuth,
JWT, browser automation, deployment automation, or Docker
configuration. The crawl orchestrator is
an internal Python boundary for one bounded site crawl. Tests inject fake fetching and use only
inert HTML evidence; they do not contact public HTTP services or DNS.

The private frontend submits only accepted crawl request fields through validation and preflight.
It polls bounded status and progress projections, reviews retained recommendation evidence, and
downloads artifacts only after an explicit action. Browser state contains no passwords, session
tokens, server paths, raw HTML, or persisted crawl drafts.

## Repository layout

```text
backend/                 FastAPI package, URL/scope core, and tests
docs/                    Architecture, crawl policy, and decision records
frontend/                Private React/TypeScript/Vite application and frontend tests
```

The Python package uses a `src` layout at `backend/src/musimack_tools`.

The frontend requires Node.js 22 or newer. Its reviewed npm graph is locked in
`frontend/package-lock.json`; see `frontend/README.md` for setup and validation.

## Supported Python

The selected range is Python `>=3.14,<3.15`. The current dependency set was resolved and
validated on Python 3.14.4. Do not modify the system Python installation; use the project
virtual environment.

## Windows PowerShell setup

Run every command from the repository root:

```powershell
py -3.14 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.lock
python -m pip install --no-deps -e backend
```

The lock file installs the tested runtime and development dependency graph. The final command
installs the local package in editable mode without re-resolving dependencies. `.venv/` is
excluded from Git.

When a dependency change is approved, update the exact declaration in `backend/pyproject.toml`,
install the reviewed environment, regenerate `backend/requirements.lock` from
`python -m pip freeze --exclude-editable`, and run the complete validation sequence plus
`python -m pip check`. Do not update unrelated dependencies opportunistically.

## Development server

```powershell
python -m uvicorn musimack_tools.main:app --app-dir backend\src --reload
```

Then request `http://127.0.0.1:8000/api/health`. The response is:

```json
{
  "application": "Musimack SEO Toolkit",
  "status": "healthy"
}
```

The server exposes health only. It does not expose the internal fetcher or parser and does not
crawl or contact websites in response to API input.

## Individual quality commands

```powershell
# Tests
python -m pytest -c backend\pyproject.toml backend\tests

# Apply formatting
python -m ruff format backend

# Check formatting
python -m ruff format --check backend

# Lint
python -m ruff check backend

# Type check
python -m mypy --config-file backend\pyproject.toml backend\src backend\tests
```

## Complete validation sequence

```powershell
python -m ruff format --check backend
python -m ruff check backend
python -m mypy --config-file backend\pyproject.toml backend\src backend\tests
python -m pytest -c backend\pyproject.toml backend\tests
python -m pip check
python -c "from musimack_tools.main import app; print(app.title)"
```

The test suite installs an automatic DNS and socket guard. It permits only loopback plumbing
needed by the Windows event loop and fails any external-network attempt immediately.

## Configuration

Settings use the `MUSIMACK_` prefix. Pydantic Settings reads process environment variables and
an optional root `.env`; environment variables take precedence. Copy `.env.example` to `.env`
only when local overrides are needed:

```powershell
Copy-Item .env.example .env
```

`.env` is intentionally ignored. General crawler settings are non-secret. Production internal API
composition additionally reads `MUSIMACK_INTERNAL_API_*` process variables; its bearer token is a
secret and has no default. Do not put a real credential in `.env.example`, source, documentation,
or logs.
Numeric crawl defaults and absolute server hard limits are validated before orchestration. The
configured user agent is `MusimackSEOToolkit/0.1`; add a legitimate contact reference before live
crawling is authorized.

## Explicit secured production application

The normal `musimack_tools.main:app` remains health-only and never loads an authentication secret.
Internal routes are available only through the separate
`musimack_tools.deployment.application.create_production_app()` factory with an explicitly
injected application service. The factory validates configuration immediately and refuses to
start when the internal API is disabled, its bearer credential is missing, a CIDR or CORS origin
is invalid, or required composition is unavailable. Its contracts are identified by
`seo-toolkit-security-v1` and `seo-toolkit-production-app-v1`.

Set production values in the process environment rather than committing them. A PowerShell
example using a placeholder is:

```powershell
$env:MUSIMACK_INTERNAL_API_ENABLED = "true"
$env:MUSIMACK_INTERNAL_API_BEARER_TOKEN = "<provide-through-secure-runtime-configuration>"
$env:MUSIMACK_INTERNAL_API_TOKEN_ID = "internal-operator"
```

Requests use `Authorization: Bearer <credential>`. Verification uses `hmac.compare_digest`; the
credential is excluded from settings representations, reports, responses, OpenAPI, and access
events. This is one shared internal credential, not a user, role, session, OAuth, JWT, or public
authorization system.

Forwarded headers are ignored unless the direct socket peer belongs to an explicitly configured
trusted-proxy CIDR. For a trusted peer, one bounded `X-Forwarded-For` chain is parsed left-to-right
and the first address outside the proxy networks is selected; if every address is a proxy, the
leftmost address is used. Optional trusted-client networks are evaluated only after that step.
This policy supports a deliberately simple proxy topology and does not replace reverse-proxy or
deployment firewall configuration.

`X-Request-ID` accepts at most 64 ASCII letters, digits, periods, underscores, or hyphens. Missing
or invalid values are replaced with `req-` plus 32 lowercase hexadecimal characters. The ID is
returned in the response header and internal API envelopes. Access events include only bounded
method, route template, status, duration, caller identifier, resolved client address, validated
job ID, and version fields; they omit query strings, headers, bodies, credentials, and output
roots.

CORS is disabled by default. When explicitly enabled it requires exact HTTP/HTTPS origins, permits
only `GET`, `POST`, and `OPTIONS`, allows only `Authorization`, `Content-Type`, and the correlation
header, exposes only that correlation header, and never enables browser credentials. Wildcards
are rejected.

Enabled security responses include `X-Content-Type-Options: nosniff`, `Cache-Control: no-store`,
`Pragma: no-cache`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, and a restrictive
Content Security Policy. HSTS is intentionally absent because TLS termination is not owned by this
application. OpenAPI and docs are disabled unless explicitly enabled. Tests use in-process ASGI
clients and inert addresses; no authentication test contacts a network or DNS.

## In-memory crawl orchestration

`SingleSiteCrawlOrchestrator` accepts a normalized seed, an accepted scope policy, and bounded
request settings. It processes one breadth-first depth at a time while fetching URLs within that
depth concurrently. The normalized absolute URL is the sole deduplication key: query order,
repeated query keys, path case, and trailing slashes retain their accepted normalization semantics.

Every parsed navigable link receives explicit admission evidence. Scope, maximum depth, query
policy, configured exclusions, URL count, and pending-queue bounds are applied before admission.
`rel=nofollow` is retained as evidence but does not currently block discovery. Canonical evidence
does not replace a frontier URL. Redirect final URLs are retained and can suppress an already
pending duplicate destination.

The orchestrator enforces total duration and accepted-byte limits, worker concurrency, and a
minimum start delay per origin. Cooperative cancellation stops new work and retains completed and
skipped records. Progress observers receive immutable snapshots and cannot control execution.
Results remain entirely in memory; the internal job service can coordinate multiple runs, but no
public API endpoint, persistence, worker process, or restart recovery exists.

## Robots and indexability evidence

An injected `RobotsTxtService` retrieves `/robots.txt` through the accepted safe fetcher once per
effective origin per crawl. Concurrent lookups share one in-flight retrieval. Successful,
not-found, forbidden, temporary-failure, invalid, and oversized results are all cached for that
crawl. Ordinary pages are fetched only after a typed robots permission decision allows them.
Robots response bytes count toward the aggregate crawl byte limit and are also reported separately.
The orchestrator requires a robots session factory at construction; production composition must
explicitly pass `RobotsTxtService`. Tests that are unrelated to robots explicitly inject a
test-module-only `AllowAllRobotsServiceForTests`. There is no implicit runtime allow-all fallback.

The parser uses the `MusimackSEOToolkit` product token, selects the earliest most-specific matching
group, falls back to `*`, applies longest matching Allow/Disallow rules, and gives Allow the tie.
Rules match the normalized path plus query and support `*` and terminal `$`. Crawl-delay and
Sitemap directives are retained as evidence but are not enforced or fetched.

Repeated `X-Robots-Tag` response headers are parsed in order into generic and crawler-specific
records. Those records are combined with existing meta robots observations only to identify
conflicts. No single `indexable` boolean, sitemap recommendation, or search-engine-specific verdict
is produced. Noindex, meta nofollow, and link nofollow still do not suppress frontier discovery.

The robots-specific 1,000,000-byte policy is enforced after the accepted fetch boundary returns
its already bounded evidence; the fetcher's lower-level stream cap remains authoritative. Also,
page redirects occur inside the accepted safe-fetch contract, so robots permission is evaluated for
the frontier URL's origin before that fetch, not as a callback before every internal redirect hop.
The fetcher still revalidates scope and network safety for each redirect target. Both limitations
are retained explicitly for future transport-boundary work.

## Sitemap eligibility recommendations

The internal `SitemapRecommendationEngine` evaluates immutable crawl records without networking,
framework state, or persistence. Each normalized identity receives one explainable state:

- `include`: complete evidence supports sitemap inclusion.
- `exclude`: at least one hard exclusion applies.
- `review`: no hard exclusion applies, but canonical or evidence quality needs human review.
- `indeterminate`: required evidence is missing or contradictory.

Determinacy is separate from state: `determinate` means sufficient coherent evidence produced an
include, exclude, or review result; `blocked_missing_evidence` and
`blocked_conflicting_evidence` explain why an indeterminate result could not be resolved.
The single authoritative code constant `SITEMAP_RULE_SET_VERSION` identifies this rule set as
`sitemap-eligibility-v1`.

State precedence is hard exclusion, indeterminate, review, then include. The engine retains every
applicable hard exclusion and review reason while selecting one primary reason from the documented
rule order. Hard exclusions cover invalid or out-of-scope URLs, disallowed ports, unavailable or
failed fetches, redirect sources, non-200 responses, non-HTML content, robots denial, generic
noindex, configured URL rules, and canonicals pointing elsewhere.

Missing, empty, short, long, duplicate, or conflicting title and description evidence remains in a
separate metadata-warning collection. Those warnings do not change an otherwise qualifying page
from `include`. Generic noindex excludes conservatively; crawler-specific noindex is retained as a
warning by default. Conflicting canonical candidates and one or more invalid canonicals without a
valid selection require review, while missing canonical is an include-with-warning default.

The crawl projection preserves crawl-record order, emits at most one recommendation per normalized
identity, counts suppressed duplicates, and summarizes states and exclusion categories. A redirect
target without its own crawl record does not receive a recommendation row; the excluded source
retains a warning that the target was not independently evaluated. The engine never invents target
eligibility. Recommendations remain internal. There is no public recommendation API, CSV export,
manual override, approval workflow, or persistence layer.

## In-memory XML sitemap generation

`SitemapXmlGenerator` consumes the immutable recommendation projection and serializes only final
`include` recommendations. It preserves projection order, suppresses exact duplicate normalized
URL strings while retaining the first occurrence, and reports malformed or oversized included
values as typed non-fatal rejections. It does not re-run eligibility rules or mutate their evidence.

Output uses the stable `sitemap-xml-v1` contract: UTF-8 bytes, the standard sitemap namespace, LF
newlines, a final newline, and only `<url><loc>` elements. The generator applies the standard
50,000-entry and 50 MiB uncompressed limits, a 2,048-character location limit, and deterministic
splitting. Multiple documents receive `sitemap-1.xml`, `sitemap-2.xml`, and so on. An index is
generated only when multiple documents exist and an explicit normalized public base URL is
configured; otherwise the documents remain available with a typed blocked-index warning.

Generation is entirely in memory. It does not write, publish, or submit files, and no public API
route exposes it. `lastmod`, `changefreq`, `priority`, compression, sitemap extensions, and manual
overrides are not implemented. Run its focused tests from the repository root with:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_sitemap_xml.py
```

## Internal sitemap export publication

`SitemapPublicationService` composes an accepted recommendation projection, `sitemap-xml-v1`
generation, deterministic `sitemap-publication-manifest-v1` packaging, and optional local
publication under the `sitemap-publication-v1` service contract. It remains an internal Python
boundary; no FastAPI route, download endpoint, CLI, background job, or submission integration is
added.

Publication requires an explicit absolute `pathlib.Path`. The default `fail_if_exists` policy
preflights every target and writes nothing if any package filename already exists. `overwrite`
atomically replaces only planned package files and leaves unrelated directory contents untouched.
Logical names must be safe simple filenames: traversal, separators, absolute paths, Windows drive
paths, UNC paths, reserved device names, case-normalized collisions, target symlinks, and output
roots containing links or `.git` are rejected. Output-directory creation is disabled unless
explicitly enabled.

`fail_if_exists` finalizes each temporary file with a same-filesystem hard link, providing
no-clobber behavior even if another process creates the target after preflight. A competing target
is preserved and reported as `target_exists`. Unsupported hard links, permission denial, and other
no-clobber failures return `no_clobber_finalization_unsupported`,
`no_clobber_finalization_permission_denied`, or `no_clobber_finalization_failed` and never fall
back to replacement. Because the temporary file is created in the target directory, ordinary
finalization stays on one filesystem. Cleanup failure remains separately typed as `cleanup_failed`.

Each XML payload has an exact byte count and lowercase SHA-256 hash. The deterministic UTF-8 JSON
manifest lists URL documents first and the optional sitemap index last; the manifest excludes
itself and contains no timestamp, machine identity, or absolute export path. Its own SHA-256 is
returned separately. Dry run performs the same generation, manifest, path, and conflict planning
without creating directories, temporary files, or final files.

Internal usage with an already-created `projection` is:

```python
from pathlib import Path

from musimack_tools.domain.sitemap_orchestration import SitemapOrchestrationRequest
from musimack_tools.domain.sitemap_publication import (
    PublicationMode,
    SitemapPublicationConfiguration,
)
from musimack_tools.sitemap.limits import SitemapXmlConfiguration
from musimack_tools.sitemap.service import SitemapPublicationService

request = SitemapOrchestrationRequest(
    recommendation_projection=projection,
    xml_configuration=SitemapXmlConfiguration(),
    publication_configuration=SitemapPublicationConfiguration(
        output_root=Path("C:/sitemap-exports"),
        mode=PublicationMode.DRY_RUN,
    ),
)
result = SitemapPublicationService().execute(request)
```

Focused validation commands are:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_sitemap_manifest.py
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_sitemap_publication.py
.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_sitemap_publication_service.py
```

Atomicity is per file after complete package preflight, not a whole-package transaction. A later
filesystem failure retains published-file evidence and cleans temporary files but does not roll
back earlier files. Publication is local-filesystem only. `replace_only_if_changed`, export
history, remote publication, submission, and persistence are deferred. Symlink capability tests
probe only link creation and skip only for recognized unsupported or privilege conditions; Windows
junction root and ancestor tests use local temporary directories and run without symlink privilege.

## Internal crawl-run workflow

`CrawlRunService` is the framework-independent composition boundary for one in-process operation.
It supports the ordered stages `crawl`, `recommend`, `generate_xml`, `plan_publication`, `publish`,
and `write_summary`. Every v1 run starts with crawl; later stages require their explicit
prerequisites. `write_summary` can accompany a successful, cancelled, failed, or partially
completed run. Crawl-only, generation-only, publication dry-run, and full local-publication runs
are supported. An internal process-local registry can coordinate the service, but no FastAPI route,
CLI, database, external worker, or public progress transport exposes it.

The service accepts an injected accepted crawl orchestrator, progress sink, cancellation token,
monotonic clock, and downstream service boundaries. Sequence numbers begin at 1. A failing progress
sink produces one `progress_sink_failed` warning and is then suppressed; core execution continues.
During crawl, a per-run adapter translates every accepted immutable crawler snapshot into a
`crawl_progress` event in callback order. Equal callback snapshots are preserved. If the last live
snapshot trails the final `CrawlResult`, one reconciled event supplies authoritative final counters
before crawl completion. No reconciliation event is added when the last callback already matches.
Cancellation is cooperative: it is checked before each stage and before publication execution.
The accepted synchronous publication executor remains atomic per file and cannot be interrupted
safely inside a file or between package files by this v1 wrapper. Completed upstream outputs are
always retained when a later stage is cancelled, blocked, or fails.

Portable identity uses SHA-256 over a canonical safe request snapshot. The display form is
`run-<12 lowercase hex characters>`; the full digest remains in the result. Output roots, caller
labels, timestamps, machine identity, credentials, and environment values are excluded. The
`crawl-run-summary-v1` JSON and companion Markdown summary are deterministic UTF-8 with LF endings
and a final newline. Their exact byte counts and hashes are returned separately. Optional summary
writing requires a separate explicit absolute root and uses only `run-summary.json` and
`run-summary.md`, with dry-run, `fail_if_exists`, `overwrite`, link rejection, and atomic per-file
writes.

Internal composition with an already configured accepted `crawler` is:

```python
from musimack_tools.domain.run import CrawlRunRequest, RunStage
from musimack_tools.run.service import CrawlRunService

request = CrawlRunRequest(
    crawl_request=crawl_request,
    requested_stages=(
        RunStage.CRAWL,
        RunStage.RECOMMEND,
        RunStage.GENERATE_XML,
        RunStage.WRITE_SUMMARY,
    ),
)
result = await CrawlRunService(crawler).execute(request)
```

All orchestration tests use injected evidence, fake services, and temporary directories. The
automatic socket/DNS guard remains active. Focused validation is:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\unit\test_run_contracts.py backend\tests\unit\test_run_summary_writer.py backend\tests\integration\test_crawl_run_service.py
```

## Internal job management

`InternalJobService` and its injected `InMemoryJobRegistry` coordinate accepted run requests in
one Python process. Submission does not wait for completion. Up to the configured active limit
starts immediately; excess work enters a bounded FIFO queue, and completion starts the next entry.
One-based queue positions always reflect current FIFO order.

The default duplicate policy rejects a non-terminal job with the same deterministic run ID.
Configuration may instead allow another attempt or return the active attempt. Job IDs have the
portable form `job-<12-character-run-prefix>-<four-digit-attempt>` and the exact registry contract
is `crawl-job-registry-v1`.

Internal async methods provide immutable status, latest progress, optional bounded progress
history, retained results, counters, cancellation, waiting, and shutdown evidence. Queued
cancellation prevents execution. Active cancellation signals the exact registry-owned cooperative
token; tasks are not killed. Terminal retention is bounded and oldest-first, with full-result,
summary-only, and metadata-only payload options. Evicted IDs return typed `not_found`.

Default shutdown stops admission, cancels queued jobs, requests active cancellation, and waits for
tracked coordinator tasks to settle. An alternative drains accepted work in FIFO order. All state
is process-local and disappears on restart. There is no public job API, persistent queue,
scheduler, external worker, or distributed coordination.

Focused validation is:

```powershell
.\.venv\Scripts\python.exe -m pytest -q backend\tests\unit\test_job_domain.py backend\tests\integration\test_job_service.py
```

## Internal application service

`SeoToolkitApplicationService` is the framework-independent boundary intended for future API,
CLI, or UI adapters. It accepts an immutable operator-oriented request, applies a named profile,
validates explicit overrides against additional application maxima, and prepares the accepted
`CrawlRunRequest`. Preparation is pure: it performs no DNS, network, job submission, directory
creation, temporary-file creation, or filesystem write.

The four v1 profiles are:

| Profile | URLs | Depth | Duration | Bytes | Concurrency | Queue | Delay | Redirects | Response bytes | Default stages |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `quick_audit` | 100 | 3 | 60s | 25 MB | 2 | 500 | 0.5s | 5 | 2 MB | crawl, recommend |
| `standard_crawl` | 5,000 | 10 | 1,800s | 500 MB | 4 | 10,000 | 0.5s | 10 | 5 MB | crawl, recommend, XML |
| `deep_crawl` | 25,000 | 25 | 3,600s | 2 GB | 8 | 50,000 | 0.5s | 10 | 10 MB | crawl, recommend, XML |
| `sitemap_only` | 10,000 | 15 | 2,400s | 1 GB | 4 | 20,000 | 0.5s | 10 | 5 MB | crawl, recommend, XML, summary |

Absolute application ceilings are 50,000 URLs, depth 50, 7,200 seconds, 5 GB accepted bytes,
16 concurrent fetches, 100,000 queued URLs, at least 0.1 seconds between per-origin starts,
20 redirects, and 50 MB per response. Values are rejected rather than clamped. The fetch-specific
profile values describe required configured dependency bounds; they do not bypass the accepted
fetcher configuration.

Validation returns ordered error, warning, and information evidence plus normalized scope, stages,
limits, and deterministic run ID. Preflight reads registry capacity, duplicate state, and requested
local output roots without allocating an attempt, reserving a queue position, or writing anything.
It is advisory and may be stale immediately; submission remains authoritative.

The facade composes submission, status, progress, cancellation, bounded result projection,
registry status, readiness, capabilities, waiting, and shutdown. Default projections contain only
counts, states, stable codes, logical filenames, and hashes—not crawl records, HTML, response
bodies, XML bytes, summary bytes, tasks, locks, tokens, stack traces, or absolute local paths.
Deterministic diagnostics use `seo-toolkit-diagnostics-v1`, sorted UTF-8 JSON or Markdown, LF
newlines, final newlines, and separately returned SHA-256 hashes. The application contract is
`seo-toolkit-application-service-v1`.

Internal usage begins with:

```python
raw = RawApplicationCrawlRequest("https://example.com", crawl_profile="quick_audit")
report = application.validate_request(raw)
preflight = await application.preflight(raw)
submission = await application.submit(raw)
```

Focused validation is:

```powershell
.\.venv\Scripts\python.exe -m pytest -q backend\tests\unit\test_application_service_domain.py backend\tests\integration\test_application_service.py
```

No public application route, CLI, durable worker, scheduler, or frontend has been added.

## Optional SQLite persistence

The internal toolkit now has an optional durable metadata boundary identified by
`seo-toolkit-persistence-v1` with schema `seo-toolkit-database-schema-v1`. It uses SQLAlchemy 2.x,
SQLite, and Alembic revision `0001_persistence` (`create persistence foundation`). Persistence is
disabled by default, and the accepted in-memory registry remains the execution and scheduling
authority. The default health-only app creates no engine, session, migration check, or database.

When enabled, `MUSIMACK_PERSISTENCE_DATABASE_PATH` must be an explicit absolute path. Parent
creation, automatic migration, and SQL echo are off by default. The path boundary rejects `.git`,
UNC/device paths, directories, regular-file parents, and existing symlink or junction ancestors.
Pure path validation creates nothing. SQLite connections enable foreign keys, apply a bounded busy
timeout, request WAL journaling, and use `NORMAL` synchronous mode; readiness verifies the effective
settings rather than assuming they succeeded.

The database stores bounded job/run lifecycle records, stage states, progress, normalized warning
and failure evidence, canonical safe configuration snapshots, and summary/artifact metadata with
hashes. It does not store credentials, environment values, absolute publication or summary roots,
raw HTML, response bodies, XML/manifest/summary bytes, access logs, tasks, or cancellation tokens.
Seed and warning URLs are persisted without query strings.

Migration is explicit by default. From the repository root, supply a test or operator-managed
absolute URL rather than relying on the current directory:

```powershell
$databaseUrl = "sqlite+pysqlite:///C:/absolute/path/to/musimack-tools.db"
.\.venv\Scripts\python.exe -m alembic -c backend\alembic.ini -x "database_url=$databaseUrl" upgrade head
.\.venv\Scripts\python.exe -m alembic -c backend\alembic.ini -x "database_url=$databaseUrl" current
```

`alembic.ini` deliberately has no fallback database URL. Production startup blocks when enabled
persistence is unmigrated. Explicit startup composition can migrate only when `auto_migrate=true`,
then reconciles non-terminal records before a registry is constructed. Interrupted accepted,
queued, starting, running, or cancelling work is not resumed or requeued; it becomes failed or
partially completed with `process_restart_interrupted`. Attempt maxima and metadata-only terminal
views can then seed a new in-memory registry without recreating tasks, tokens, or full results.

Cleanup is explicit, sequence-ordered, and bounded. It prunes old progress/warning/failure and
artifact/summary metadata and may mark excess terminal records evicted; it never deletes filesystem
artifacts. SQLite remains a local single-process durability layer, not a worker queue.

Focused persistence validation is:

```powershell
.\.venv\Scripts\python.exe -m pytest -q backend\tests\unit\test_persistence_domain.py backend\tests\unit\test_persistence_engine_and_models.py backend\tests\integration\test_persistence_migrations.py backend\tests\integration\test_persistence_repository.py backend\tests\integration\test_job_persistence_integration.py backend\tests\integration\test_persistence_production.py
```

### Durable page-level crawl evidence

Phase 20A adds an opt-in terminal persistence observer for accepted crawl records. Its exact
contracts are `seo-toolkit-page-crawl-evidence-v1`,
`seo-toolkit-page-crawl-evidence-persistence-v1`,
`seo-toolkit-page-crawl-evidence-query-v1`,
`seo-toolkit-page-crawl-evidence-retention-v1`, and
`seo-toolkit-page-crawl-evidence-projection-v1`. It never re-fetches, resolves DNS, or reparses
HTML.

Alembic revision `0006_page_crawl_evidence` (`add durable page crawl evidence`) stores bounded page,
redirect, parse-warning, summary, and event rows. Ordering is exactly
`crawl_discovery_sequence_asc_url_identity_asc-v1`. Repeated writes are idempotent and conflicting
evidence is rejected.

Page evidence is disabled by default. Defaults are 250 records per batch, 50 records per query,
200 maximum records per query, 100,000 pages per run, 20 redirect hops, 50 parse warnings per page,
4,096 metadata characters, 180 retention days, and 500 cleanup records per invocation. Cleanup is
explicit, dry-run capable, hold-aware, bounded, and protects active runs. Reconciliation is
explicit, read-only, bounded, and never re-fetches or reparses.

No raw HTML, response body, full header set, cookie, token, database URL, or filesystem path is
stored. No API or frontend route is added, so route counts remain unchanged. Phase 20 metadata
classification, exports, and UI remain deferred and can consume this evidence after restart or
terminal-payload eviction.

Focused validation is:

```powershell
.\.venv\Scripts\python.exe -m pytest -q backend\tests\unit\test_page_evidence_domain.py backend\tests\integration\test_page_evidence_persistence.py backend\tests\integration\test_persistence_migrations.py
```

## Optional durable execution

Durable execution is an explicit alternative to the accepted process-local scheduler. It is off by
default. In-memory mode continues to use the bounded in-process queue; durable mode uses migrated
SQLite rows as the sole queue authority and never creates a duplicate local scheduling task. The
exact contracts are `seo-toolkit-durable-execution-v1` and
`seo-toolkit-worker-protocol-v1`.

Durable mode requires enabled, ready persistence at the current Alembic head. Phase 16 advances
that head to `0004_history_api`; the Phase 17 revision adds only historical timestamps and query
indexes while retaining accepted durable and artifact tables as the source of truth.
Persistence startup must be called with `durable_queue_authority=True`; this bypasses only the
legacy in-memory interrupted-job reconciler so queued and leased records reach durable stale
recovery. The default remains `False`, preserving accepted in-memory restart behavior.
Enabling the worker additionally requires an explicit safe ID such as `worker-local`; no hostname,
username, random value, or environment-derived fallback is used. One explicitly composed worker
may run in the API process, or a worker may be composed without the API. No worker or polling task
is created at import time, and the default health-only application remains unchanged.

Claims use short SQLite `BEGIN IMMEDIATE` transactions and deterministic durable sequences. Each
claim creates a new secure lease token, increments its lease generation, and creates a distinct
execution-attempt record while retaining the same external job ID. Heartbeats extend only a valid
active lease. Cancellation is persisted for queued, claimed, running, and retry-wait jobs and is
forwarded to the existing cooperative cancellation token. Startup recovery releases expired
leases before polling; it may queue a fresh execution attempt but never resumes a partial crawl
frontier or recreates an old task.

Retry policy defaults to `never`. `retry_transient` and `retry_selected` use only configured stable
failure codes, bounded attempt counts, and fixed or linear delays without jitter. A retry receives a
new availability sequence, so work already queued is not starved. SQLite wall-clock UTC timestamps
control lease expiry and retry eligibility, while integer sequences—not timestamps—control queue,
claim, attempt, and recovery ordering.

Shutdown first stops new claims and enters `draining`. The default policy gives active cooperative
work a bounded grace period; the optional cancellation policy requests cancellation through the
accepted token. This is single-machine execution, not distributed coordination. SQLite lock
contention, clock correctness, process termination, filesystem durability, and deployment
supervision remain operational responsibilities.

The safe disabled values in `.env.example` use the `MUSIMACK_DURABLE_EXECUTION_ENABLED` and
`MUSIMACK_WORKER_*` settings. To migrate an explicitly selected database, use the Alembic commands
above. Focused durable validation is:

```powershell
.\.venv\Scripts\python.exe -m pytest -q backend\tests\unit\test_durable_execution_domain.py backend\tests\integration\test_durable_migration.py backend\tests\integration\test_durable_repository.py backend\tests\integration\test_durable_worker_and_service.py backend\tests\integration\test_durable_production.py
```

## Private internal API adapter

An internal FastAPI adapter now maps the accepted application-service facade to bounded Pydantic
schemas beneath `/api/internal/v1`. The adapter contract is
`seo-toolkit-internal-api-v1`. It provides explicitly composed endpoints for request validation,
advisory preflight, job submission, status, latest or bounded retained progress, bounded results,
cooperative cancellation, registry counts, readiness, and capabilities. When explicitly composed
with enabled artifact storage, it adds private bounded artifact list, detail, and download routes.
It provides no shutdown or public download endpoint.

The normal `create_app()` composition remains health-only: `/api/health` is its sole route and no
internal schemas appear in its OpenAPI document. Internal routes are mounted only by calling
`mount_internal_api()` with `mount_internal_routes=True`, an explicitly injected application
service, and an access verifier. A mounted router without a verifier denies every request. The
gate runs before adapter service invocation, fails closed when verification raises or is
unavailable, and returns structured errors without echoing credential evidence or revealing job
existence.

The explicit production factory now supplies one environment-backed shared bearer credential,
trusted-client/proxy policy, and fail-closed startup validation around this gate. It is still not a
complete authentication or authorization system: there are no users, roles, sessions, OAuth,
JWT, stored credential records, or public deployment trust boundary. TLS/reverse-proxy controls
and network restrictions remain deployment responsibilities.

Success responses use a typed envelope containing the API version, an optional request ID, bounded
data, and bounded warnings. Production correlation supplies the request ID on success and error;
the lower-level adapter remains `null` when used without that middleware. Errors use stable codes,
safe messages, and bounded field details.
Pydantic errors are normalized to HTTP 400 without returning submitted values. Job IDs must match
`job-<12 lowercase hexadecimal characters>-<four digits>`. Request fields, approved hosts, caller
labels, URL strings, job IDs, and optional progress history are bounded. The adapter enforces a
declared `Content-Length` limit; requests without a trustworthy declared length still require a
future deployment-level body limit.

Focused validation is:

```powershell
.\.venv\Scripts\python.exe -m pytest -q backend\tests\unit\test_internal_api_domain.py backend\tests\integration\test_internal_api.py
```

Tests use in-process ASGI clients, injected access verifiers, fake dependencies, and the accepted
in-memory job/run services. They perform no public HTTP, DNS, or external authentication calls.

## Crawl-safety status

URL scope and network safety are separate approvals. The internal fetch boundary rejects local
hostnames, IP literals, unsafe or mixed DNS answers, and unapproved ports; manually revalidates
every redirect; disables environment proxies; and streams responses under hard byte and time
limits. It retains typed evidence but does not parse bodies.

Pre-resolution does not pin the HTTP connection to a validated address because `httpx` does not
expose the connected peer cleanly at this boundary. DNS could change between validation and
connection. Live deployment must therefore add network-level egress restrictions, and the
resolver/transport boundary remains injectable for future address-pinning work. A URL being in
scope is still **not** sufficient authorization to request it.

## HTML metadata extraction

`HtmlMetadataParser` accepts one completed `FetchResult`. It parses only successful,
non-truncated HTML evidence and never fetches links, canonicals, or base URLs. It extracts all
observed titles and descriptions, canonical candidates, crawler-named meta robots records, the
first valid base URL, and document-order `<a>`/`<area>` links. Conflicting observations remain
visible rather than being silently discarded.

Visible text is entity-decoded, whitespace-collapsed, and trimmed. Initial review thresholds
are title under 15 or over 60 characters and description under 70 or over 160 characters.
These warnings are metadata evidence only; they do not decide sitemap eligibility or page
indexability. Encoding selection uses HTTP charset, then BOM, then a declaration in the first
4,096 body bytes, then Windows-1252 fallback. See
[docs/crawl-policy.md](docs/crawl-policy.md) for the complete contract.

See [docs/crawl-policy.md](docs/crawl-policy.md) for the precise current contract.

## Durable artifact storage and retrieval

Phase 16 adds optional local artifact management without storing file bytes in SQLite. It is
disabled by default and uses `seo-toolkit-artifact-storage-v1`,
`seo-toolkit-artifact-retrieval-v1`, and `seo-toolkit-artifact-reconciliation-v1`. Enabled
composition requires explicit `root-id=absolute-path` roots and a configured default root; no
current-directory or repository-relative fallback exists. Paths follow
`jobs/<job-id>/runs/<run-id>/artifacts/<safe-filename>` and are revalidated for containment,
symlinks, and Windows junctions immediately before file operations.

Supported types are sitemap XML, sitemap indexes, publication manifests, run-summary JSON, and
run-summary Markdown. CSV metadata is reserved but creation is disabled. Registration streams
SHA-256 verification, persists expected and observed evidence, and never copies or overwrites a
published file. The optional terminal observer registers successful outputs independently;
publication remains successful when metadata registration fails, and the file is not deleted.

Authenticated production composition can add exactly three routes:
`GET /api/internal/v1/artifacts`, `GET /api/internal/v1/artifacts/{artifact_id}`, and
`GET /api/internal/v1/artifacts/{artifact_id}/download`. Downloads verify by default, stream in
bounded chunks, use safe fixed headers, and expose no root or relative storage path. The default
application remains health-only.

Retention uses persisted expiration rather than file modification time. Holds prevent cleanup.
Explicit cleanup is deterministic, batch-bounded, and metadata-preserving. Reconciliation is
startup-disabled by default, scans only the bounded managed layout, and reports orphans without
registering or deleting them. Database revision `0003_artifact_storage` downgrades cleanly to
`0002_durable_execution`, with data loss limited to Phase 16 tables.

## Durable job and run history

Phase 17 adds an optional, private, restart-safe history layer over SQLite. It is disabled by
default and versioned as `seo-toolkit-history-service-v1`, `seo-toolkit-history-api-v1`, and
`seo-toolkit-history-pagination-v1`. Explicit composition requires current durable persistence;
there is no fallback database, import-time task, process-local history cache, or public route.

Jobs use deterministic `submitted_sequence_desc_job_id_desc-v1` ordering. Runs use
`submitted_sequence_desc_run_id_desc-v1`, based on the latest persisted job submission for the
run. Opaque base64url cursors contain a strictly parsed format/version, query kind, ordering,
filter fingerprint, and last ordering key. Cursors contain no SQL or secrets, are not represented
as cryptographically tamper-proof, and are rejected when malformed or reused with different
filters or ordering. Page sizes and all related attempt, stage, warning, failure, and artifact
collections are bounded.

Authenticated production composition adds ten history paths beneath
`/api/internal/v1/history`: job list/detail/attempts, run list/detail/stages/warnings/failures/
artifacts, and diagnostics. History-only production has 21 total paths; artifacts-only has 14;
artifacts plus history has 24; production without either feature remains 11; the default app
remains `/api/health` only. Existing bearer authentication, trusted-network/proxy enforcement,
correlation IDs, security headers, and safe error envelopes apply unchanged.

Historical projections omit lease tokens, storage paths, hashes, SQL, raw exceptions, request
headers, environment values, and credentials. Result eviction returns retained metadata with an
explicit availability state instead of becoming job-not-found. Artifact references are summaries
of Phase 16 authority and never duplicate artifact lifecycle decisions. Revision
`0004_history_api` adds nullable wall-clock evidence and only indexes exercised by history queries;
it creates no duplicate history tables.

## Internal users, sessions, and authorization

Phase 27 adds opt-in, versioned password authentication consumed by the private frontend. The
accepted modes are `shared_bearer`, `user_session`, and `hybrid`; expansion is disabled and the
existing shared bearer remains authoritative by default. Explicit user-session composition needs
current SQLite persistence plus an injected authentication service. There is no default user,
password, import-time bootstrap, public bootstrap route, or generated secret.

Passwords use PBKDF2-HMAC-SHA256 with a random salt and a 600,000-iteration production floor.
Browser sessions use an opaque `session-<64 lowercase hex>` token in the `musimack_session`
HttpOnly, Secure, SameSite=Strict cookie. Only a SHA-256 token hash is persisted. Role changes,
deactivation, disablement, and password changes invalidate stale sessions. Login attempts and
authentication audit events are durable and bounded; cleanup is an explicit service operation.

Authorization is centralized and deny-by-default for the exact `administrator`, `operator`, and
`viewer` roles. The compatibility bearer maps explicitly to the administrator permission set, so
unchanged deployments retain their accepted behavior. Expanded composition adds 16 private
auth/user operations; the default app remains health-only and ordinary bearer production remains
11 paths.

The one-time administrator setup is the explicit, network-free
`AuthenticationService.bootstrap_administrator(email, display_name, password)` operation. It
refuses once any administrator exists and never returns or prints password material. Migration
`0005_authentication_authorization` creates users, credentials, sessions, audit events, and login
attempts. Downgrading to `0004_history_api` removes only those Phase 27 tables and their data.
Administrator-driven password reset is deferred; users can change their own password only after
presenting the current password, and that change revokes every other session.

## Next recommended development batch

The next frontend batch may connect one bounded, accepted workflow to the protected landing
surfaces. Deterministic CSV serialization, full durable-result reconstruction, public persistence
or worker APIs, PostgreSQL, multi-machine workers, manual overrides, remote publication, and
sitemap submission remain separate future authorizations.
