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

## Scope

This phase provides Sign In, Overview, Jobs, History, Artifacts, Users, Settings, Unauthorized,
Not Found, and Service Unavailable surfaces. Jobs, History, Artifacts, Users, and Settings are
intentional permission-gated landing pages. Phase 19 workflow behavior, mutations, live polling,
generated API clients, OAuth, JWT, public deployment, and backend static-file serving remain
deferred.

The compatibility target is the current evergreen releases of Chrome, Edge, Firefox, and Safari.
No Internet Explorer support or legacy polyfill bundle is provided.
