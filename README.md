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
- Pytest, Ruff, and MyPy validation
- Architecture and crawl-policy documentation

It deliberately does **not** provide sitemap eligibility decisions, sitemap fetching, final
search-engine-specific indexability verdicts, public crawl or fetch API endpoints, background jobs,
persistence, XML/CSV exports, authentication,
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
Results remain entirely in memory; no job service, persistence, API endpoint, or restart recovery
exists yet.

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

The next bounded batch should add a pure sitemap recommendation engine over retained status,
canonical, robots-permission, and indexability evidence. It must keep metadata quality warnings
separate from eligibility, preserve decision reasons, and avoid persistence, public crawl APIs,
background jobs, and exports unless separately authorized.
