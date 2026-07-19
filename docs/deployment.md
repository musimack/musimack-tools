# Private production deployment

Phase 27 supports one small, provider-neutral deployment shape: a trusted private TLS ingress serves the Vite build and forwards same-origin `/api` requests to a loopback FastAPI web process; a separately supervised worker consumes the durable SQLite queue. The SQLite database, artifact roots, backup destination, and operational logs live outside the source checkout. The ingress, web process, and worker may share one host because SQLite is the repository-proven datastore. A clustered or network-filesystem deployment is not supported.

The default application remains the health-only factory and exposes only `/api/health`. Product routes are mounted only by the explicit operations web composition. FastAPI does not serve the frontend and no development server, container runtime, service manager, proxy product, cloud, or operating system is mandated.

## Boundaries and order

The ingress is the public-origin and TLS boundary. It accepts only the configured hostnames, serves static files, falls back to `index.html` for browser routes, and forwards `/api` without changing the prefix. The web process binds only to `127.0.0.1`, does not trust Uvicorn proxy headers, and applies the existing trusted-network, trusted-proxy, host, security-header, authentication, and authorization controls. The worker has no listening socket. Web and worker share the database and artifact roots; only the worker executes queued crawls.

Deploy in this order:

1. Stop worker, then web, and confirm both are stopped.
2. Back up the current database and artifacts.
3. Install source and build the frontend without changing lock files.
4. Load secrets through the process supervisor or secret store, never a committed file.
5. Run `initialize`, then `preflight --allow-pending-migrations`.
6. Run `migration-status`, then the explicit `migrate` command.
7. Run normal `preflight` for both web and worker roles.
8. Start worker, wait for registration, then start web and validate health and private readiness.
9. Enable ingress traffic.

For shutdown, remove ingress traffic, stop web from accepting work, signal the worker, allow its configured grace period, and then stop the web process. Unexpected worker termination is handled by durable lease expiry and startup stale-job recovery.

## Production configuration

Start from `.env.example`, but inject actual secrets outside the repository. At minimum configure:

- `MUSIMACK_ENVIRONMENT=production`, `MUSIMACK_INTERNAL_API_ENABLED=true`, `MUSIMACK_INTERNAL_API_AUTHENTICATION_ENABLED=true`, and an appropriate authentication mode.
- `MUSIMACK_INTERNAL_API_REQUIRE_SECURE_COOKIE=true`; session-only mode also sets shared-bearer compatibility to false. Shared-bearer or hybrid mode requires a non-placeholder bearer secret.
- Explicit CIDRs in `MUSIMACK_INTERNAL_API_TRUSTED_NETWORKS` and `MUSIMACK_INTERNAL_API_TRUSTED_PROXIES`. Empty and all-address trust are rejected.
- `MUSIMACK_PERSISTENCE_ENABLED=true`, an absolute `MUSIMACK_PERSISTENCE_DATABASE_PATH` outside the checkout, `MUSIMACK_PERSISTENCE_AUTO_MIGRATE=false`, and `MUSIMACK_PERSISTENCE_CREATE_PARENT_DIRECTORY=false` after initialization.
- `MUSIMACK_DURABLE_EXECUTION_ENABLED=true`. Worker processes additionally require `MUSIMACK_WORKER_ENABLED=true` and a stable unique `MUSIMACK_WORKER_ID`. Heartbeats must be shorter than leases.
- `MUSIMACK_ARTIFACT_ENABLED=true` and comma-separated `root-id=absolute-path` entries in `MUSIMACK_ARTIFACT_STORAGE_ROOTS`, separate from the database and checkout.
- `MUSIMACK_OPERATIONS_HOST=127.0.0.1`, an available port, the external HTTPS origin, explicit ingress hostnames, the absolute Vite build directory, and a shutdown timeout at least as long as the worker grace period.

`MUSIMACK_OPERATIONS_ALLOW_INSECURE_LOOPBACK_VALIDATION=true` is accepted only with an explicit HTTP loopback origin. It is for temporary local QA where Secure cookies cannot travel over HTTP; it is not a production setting and does not alter the secure-cookie default.

## Frontend and ingress

Run `npm ci --offline` when the package cache is already provisioned, then `npm run build` in `frontend`. Deploy the generated `dist` directory outside the source checkout or copy it to the configured immutable release location. Keep `VITE_API_BASE_URL=/api/internal/v1` for same-origin cookies. Do not place credentials in `VITE_*` values.

The ingress should use a short or no-cache policy for `index.html` and long immutable caching for fingerprinted assets. Unknown non-API browser paths must fall back to `index.html`; unknown `/api` paths must not. Vite source maps remain disabled by the repository build configuration and should not be published unless separately reviewed.

The repository proves compatibility with a private reverse-proxy/static-server role, but does not select Nginx, Caddy, Apache, IIS, a cloud load balancer, Docker, Kubernetes, systemd, or Windows Services. Configure the chosen supervisor to run the exact commands in `docs/operations.md`, preserve environment separation, restart failed processes with bounded backoff, and deliver ordinary termination signals.

## Rollback

Application rollback is an operator-controlled release swap. Disable ingress, stop worker and web, preserve the failed state, and restore the pre-deployment backup into new empty durable locations. Point the prior accepted application version at the restored paths, run its preflight, start worker then web, validate health/readiness/login, and restore ingress. Never downgrade a live database automatically and never overwrite the failed database or artifact roots; retain both until the incident is closed.
