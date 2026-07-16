# Musimack SEO Toolkit frontend

This directory contains the accepted private frontend foundation for the Musimack SEO Toolkit.
It is a React 19, strict TypeScript, and Vite application with a small native-fetch API boundary,
cookie-based authentication, centralized permission-aware routing, an accessible responsive shell,
and deterministic Vitest coverage.

The foundation versions are:

- `seo-toolkit-frontend-foundation-v1`
- `seo-toolkit-frontend-api-client-v1`
- `seo-toolkit-frontend-auth-v1`
- `seo-toolkit-frontend-design-system-v1`
- `seo-toolkit-crawl-workflow-ui-v1`
- `seo-toolkit-job-monitor-ui-v1`
- `seo-toolkit-sitemap-review-ui-v1`
- `seo-toolkit-artifact-access-ui-v1`
- `seo-toolkit-frontend-polling-v1`

## Requirements and install

Use Node.js 22 or newer. The accepted implementation was validated with Node.js 24.15.0 and npm
11.12.1 on Windows. From this directory, install exactly the reviewed lock graph:

```powershell
npm ci
```

`package-lock.json` is authoritative and must remain committed. `node_modules/`, `dist/`, Vite
caches, and TypeScript build metadata are generated artifacts and must not be committed.

## Local development

Activate the repository Python environment and start the backend process on loopback port 8000
from the repository root. The ordinary command below starts the health-only composition; local
user-session testing requires the separately configured expanded production factory described in
the root documentation.

```powershell
python -m uvicorn musimack_tools.main:app --app-dir backend\src --host 127.0.0.1 --port 8000
Set-Location frontend
```

Then run:

```powershell
npm run dev
```

Vite binds to `127.0.0.1:5173` and proxies `/api` to `http://127.0.0.1:8000`. Copy
`.env.example` to a local ignored environment file only when a different local port is required.
`VITE_API_BASE_URL` accepts a relative path, localhost, or loopback URL; it rejects public remote
hosts. Never place secrets, passwords, tokens, cookies, or credentials in a `VITE_*` variable:
Vite exposes those values to browser code.

The proxy keeps browser requests same-origin and does not weaken the backend network, host, proxy,
or cookie rules. If direct development CORS is explicitly enabled, the only accepted example
origin is `http://127.0.0.1:5173`; never combine credentials with a wildcard origin. Production
requires the existing Secure cookie policy and an explicit internal HTTPS origin.

The browser client calls `/api/internal/v1`, sends `credentials: "include"`, and relies only on the
server-managed HttpOnly session cookie. It does not parse cookies or use local storage, session
storage, bearer tokens, or persisted passwords. The dev proxy is convenience, not a production
security boundary.

## Validation

```powershell
npm run format
npm run lint
npm run typecheck
npm test
npm run build
npm audit --audit-level=high
```

Tests mock `fetch` and never require a backend, DNS, or public network. `npm run build` writes the
temporary static bundle to `dist/`; remove it after validation. Production static hosting and
reverse-proxy policy are deployment responsibilities. The Python backend does not serve this
bundle.

## Crawl, monitoring, and review workflow

Users with `jobs.submit` can configure a backend-supported crawl at `/jobs/new`, run validation
and preflight, and explicitly submit it. Live status and bounded progress events appear under
`/jobs/:jobId`; polling stops at terminal state and slows while the document is hidden. Result and
recommendation pages use `jobs.view` and `runs.view`. Durable history uses `history.view`, while
artifact metadata and explicit downloads use `artifacts.view` and the backend download gate.

The browser keeps only ephemeral workflow state. It does not store crawl drafts in browser
persistence, place them in URLs, accept server filesystem paths, inspect cookies, or automatically
download artifacts. History and recommendation filters use bounded query parameters.

Workflow routes are `/jobs`, `/jobs/new`, `/jobs/:jobId`, `/jobs/:jobId/progress`,
`/jobs/:jobId/results`, `/jobs/:jobId/results/recommendations`, `/history`,
`/history/jobs/:jobId`, `/history/runs/:runId`, `/artifacts`, and
`/artifacts/:artifactId`. Detail pages provide contextual navigation and remain protected on direct
entry. The UI consumes the internal validation, preflight, jobs, progress, result, cancellation,
capabilities, recommendation, history, and artifact routes. Phase 19 adds only one OpenAPI path,
`GET /api/internal/v1/jobs/{job_id}/recommendations`; live job listing uses `GET` on the existing
`/api/internal/v1/jobs` path.

Visible queued jobs poll every 3 seconds; starting, running, and cancelling jobs poll every 2
seconds; other nonterminal and retry-failure states use at least 5 seconds. Failures back off
exponentially to 15 seconds and hidden documents use at least 10 seconds. Requests never overlap,
unmount aborts in-flight work, and cancelled, completed, completed-with-warnings, failed,
partially-completed, and evicted states stop polling. Cancellation is cooperative and requires
`jobs.cancel`; submission uses `jobs.submit`; live reads use `jobs.view`; results and
recommendations use `runs.view`; durable records use `history.view`; artifact metadata and
downloads use `artifacts.view` and `artifacts.download`.

Forms use semantic fieldsets, controlled inputs, client usability checks, backend validation,
effective-value review, and explicit preflight confirmation. Tables scroll on narrow screens,
long evidence wraps, reduced motion is honored, status always includes text, and every data surface
has a loading, empty, or safe error state. This is an accessibility foundation, not a certification.

## Scope

This phase provides Sign In, Overview, crawl submission, job monitoring and cancellation, result
and recommendation review, durable history, artifact browsing and download, Users, Settings,
Unauthorized, Not Found, and Service Unavailable surfaces. Manual recommendation overrides,
sitemap submission, deployment automation, generated API clients, OAuth, JWT, public deployment,
and backend static-file serving remain deferred.

The compatibility target is the current evergreen releases of Chrome, Edge, Firefox, and Safari.
No Internet Explorer support or legacy polyfill bundle is provided.
