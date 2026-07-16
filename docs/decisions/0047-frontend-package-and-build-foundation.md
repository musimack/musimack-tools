# 0047: Frontend package and build foundation

Status: Accepted for `seo-toolkit-frontend-foundation-v1`.

## Decision

Build the private frontend as an independently validated static React application under
`frontend/`, using strict TypeScript, Vite, npm, and an exact npm lock. Require Node.js 22 or newer,
bind development and preview servers to loopback, and keep the static build separate from FastAPI.
Use React Router as the only runtime dependency beyond React because nested protected routes,
history navigation, redirects, and not-found handling are core application requirements.

## Consequences

Frontend installation is reproducible with `npm ci`; lint, formatting, type checking, tests, audit,
and production builds are explicit. `node_modules`, `dist`, caches, and TypeScript metadata remain
generated. Production static hosting and routing fallback configuration remain deployment work.
