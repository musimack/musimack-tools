# Musimack SEO Toolkit

The Musimack SEO Toolkit is a standalone internal application for reusable SEO analysis
tools. Its first planned module is the **Sitemap Generator and Metadata Crawler**, which will
eventually crawl approved websites, collect response and page metadata, explain sitemap
recommendations, support human overrides, and export XML and CSV results.

## Current foundation scope

This first implementation batch provides:

- A typed Python 3.14 and FastAPI backend foundation
- Typed, non-secret settings through Pydantic Settings
- `GET /api/health`
- Deterministic, network-free URL normalization
- Exact-host, subdomain, and explicit-approved-host scope evaluation
- Stable scope decision evidence
- Pytest, Ruff, and MyPy validation
- Architecture and crawl-policy documentation

It deliberately does **not** provide HTTP fetching, DNS resolution, redirects, `robots.txt`,
HTML parsing, public-site crawling, background jobs, persistence, XML/CSV exports,
authentication, frontend application code, browser automation, or Docker configuration.
There is no live crawling in this repository.

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

The server is a local API process only. It does not crawl or contact websites.

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
Numeric crawl defaults are validated even though no crawler currently consumes them. The
configured user agent is `MusimackSEOToolkit/0.1`; add a legitimate contact reference before
live crawling is authorized.

## Crawl-safety status

URL normalization and scope evaluation are pure, network-free policy primitives. A URL being
in scope is **not** authorization to request it. DNS and connected-address checks, SSRF
protections, redirect validation, robots behavior, response limits, enforced rate limits, and
bounded worker execution remain deferred and must precede any live crawler.

See [docs/crawl-policy.md](docs/crawl-policy.md) for the precise current contract.

## Next recommended development batch

The next batch should design and test the network-safety boundary before adding general HTTP
fetching: address classification, DNS-resolution injection, redirect-target revalidation,
timeouts, response-size limits, an identifiable user-agent contact reference, and bounded
per-host/global controls. It should continue to use mocks and local fixture servers; public
site crawling should remain separately authorized.
