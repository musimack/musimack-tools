# Musimack SEO Toolkit

The Musimack SEO Toolkit is a standalone internal application for reusable SEO analysis
tools. Its first planned module is the **Sitemap Generator and Metadata Crawler**, which will
eventually crawl approved websites, collect response and page metadata, explain sitemap
recommendations, support human overrides, and export XML and CSV results.

## Current backend scope

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
- Pytest, Ruff, and MyPy validation
- Architecture and crawl-policy documentation

It deliberately does **not** provide sitemap fetching, final search-engine-specific indexability
verdicts, public crawl, recommendation, or job API endpoints, persistent background workers,
persistence, CSV
exports, manual overrides, authentication,
frontend application code, browser automation, or Docker configuration. The crawl orchestrator is
an internal Python boundary for one bounded site crawl. Tests inject fake fetching and use only
inert HTML evidence; they do not contact public HTTP services or DNS.

## Repository layout

```text
backend/                 FastAPI package, URL/scope core, and tests
docs/                    Architecture, crawl policy, and decision records
frontend/README.md       Future frontend direction only
```

The Python package uses a `src` layout at `backend/src/musimack_tools`.

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

`.env` is intentionally ignored. No setting in this batch is secret or requires a credential.
Numeric crawl defaults and absolute server hard limits are validated before orchestration. The
configured user agent is `MusimackSEOToolkit/0.1`; add a legitimate contact reference before live
crawling is authorized.

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
scheduler, external worker, authentication, or distributed coordination.

Focused validation is:

```powershell
.\.venv\Scripts\python.exe -m pytest -q backend\tests\unit\test_job_domain.py backend\tests\integration\test_job_service.py
```

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

## Next recommended development batch

The next bounded batch should add deterministic CSV crawl and metadata audit serialization as a
separate pure consumer of accepted run evidence. Public APIs, persistent run history, external
workers, manual overrides, remote publication, and sitemap submission remain separate future
authorizations.
