# Continuous integration

Phase 28 defines two workflows: `.github/workflows/ci.yml` validates pull requests and pushes to `main`; `.github/workflows/release-candidate.yml` is a manual, review-only packaging workflow. Neither workflow deploys, publishes, tags, or creates a GitHub Release.

## CI structure

The CI workflow has a full Linux job followed by a focused Windows filesystem job. Linux runs on explicit `ubuntu-24.04` with Python 3.14.4 and Node 24.15.0. It installs exact backend requirements and the exact npm lock, runs Ruff format/lint, strict MyPy over `backend/src` and `backend/tests`, repository-native lock/import/workflow/migration/secret/artifact audits, the full backend suite, `pip check`, Prettier, ESLint, TypeScript, full Vitest, the Vite build, both offline npm audits, and final Git cleanliness checks.

Windows runs on explicit `windows-2025` after Linux succeeds. It exercises sitemap publication paths, Windows junction handling, capability-dependent symlink defenses, release packaging path safety, and Phase 27 backup/restore behavior. Linux supplies full product coverage and exercises real symlinks; Windows supplies the platform-specific junction and privilege behavior. The Windows symlink tests may use their three documented capability skips when WinError 1314 prevents link creation. Linux may skip only tests that explicitly require Windows junction creation; those tests execute in the Windows job.

There are no path filters: documentation, deployment, workflow, and release-policy changes receive the same required checks. Pull-request concurrency cancels superseded runs. Pushes to `main` are not canceled. Jobs have explicit timeouts.

## Security and network model

Top-level token permission is only `contents: read`. Checkout credentials are not persisted. There is no `pull_request_target`, write permission, repository secret, OIDC permission, external scan, arbitrary script download, or `eval`. Forked pull-request code runs with a read-only token and no repository secrets.

Dependency installation may reach the configured Python and npm registries during setup. Tests remain network-free: the backend autouse fixture blocks DNS and non-loopback sockets. Subsequent npm vulnerability checks use offline mode. No cache is configured; clean correctness is preferred over cache speed and avoids cross-trust cache poisoning.

Repository-native audits reject private keys, common provider-token forms, Phase 27 review credentials, generated databases, certificates, logs, PID files, browser traces, caches, and other prohibited artifacts. The production build is explicitly allowed only while its contents are scanned; it is never uploaded by ordinary CI.

## Required checks and failure interpretation

Recommended required checks for `main` are:

- `Linux full validation`
- `Windows filesystem and symlink validation`

A basic/static failure prevents the Windows job. A migration failure means the graph, head, parent, or empty-database upgrade is unsafe. A network-guard failure means a test attempted DNS or a non-loopback connection. A repository-audit failure must be treated as possible secret or generated-data exposure. A platform skip outside the documented set requires human review.

Expected hosted runtime is approximately 10–20 minutes for Linux plus 5–10 minutes for Windows, subject to hosted-runner and registry availability. Caching is intentionally absent, so correctness does not depend on cache state.

## Local reproduction

With the locked environments already present:

```powershell
.\.venv\Scripts\python.exe -m ruff format --check backend
.\.venv\Scripts\python.exe -m ruff check backend
.\.venv\Scripts\python.exe -m mypy --config-file backend\pyproject.toml backend\src backend\tests
.\.venv\Scripts\python.exe -m musimack_tools.ci all --repository-root .
.\.venv\Scripts\python.exe -m pytest -c backend\pyproject.toml
.\.venv\Scripts\python.exe -m pip check
Push-Location frontend
npm run format:check
npm run lint
npm run typecheck
npm run test
npm run build
npm audit --offline
npm audit --offline --omit=dev
Pop-Location
```

Hosted syntax and runner execution cannot be proven locally. Local tests audit workflow structure, triggers, permissions, immutable pins, timeouts, concurrency, fork safety, and absence of publication behavior; the first reviewed push must confirm hosted execution before checks become required.
