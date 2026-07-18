# Automated Authenticated Browser QA — Structured Data

The Phase 25 browser gate uses a migrated temporary SQLite database, real password-session authentication, an operator, a viewer, seeded crawl evidence, the production FastAPI application, and a loopback Vite frontend. It is automated browser QA, not human acceptance.

The script verifies operator sign-in, list and create navigation, evidence readiness, execution, summary totals, each of the nine inventory views, all eight export actions and artifact-history links, viewer read/download access, viewer mutation denial, unauthorized redirect behavior, absence of `/api/audits/structured-data`, and absence of unexpected non-loopback requests. It also records console errors and failed responses. The corrected fixture includes all seven Phase 25 diagnostic corrections, all seven corrected recommendation actions, profile states beyond present/missing/empty, non-HTML retained evidence, formula-like values, and versioned export metadata.

Browser-visible download navigation verifies authentication and artifact routing. Payload-byte schema, hash, formula-protection, corruption, and unsafe-path behavior are paired with direct artifact and export-integrity tests because the browser controller does not expose downloaded file bytes portably.

Use the local-only fixture documented in `docs/image-audit-browser-qa.md`, substituting a temporary `phase25` QA directory. Migrate, bootstrap, and seed with:

```powershell
.\.venv\Scripts\alembic.exe -c backend\alembic.ini -x "database_url=$databaseUrl" upgrade head
.\.venv\Scripts\python.exe backend\tests\qa_sitemap_browser.py bootstrap
.\.venv\Scripts\python.exe backend\tests\qa_sitemap_browser.py seed
```

Start `qa_sitemap_browser:create_qa_app` on loopback port 8000 and Vite on loopback port 5173, with the environment variables listed in that guide. The seed command prints the completed run ID used by the structured-data workflow.

The output directory is temporary evidence and must be removed after review. The repository must not retain databases, WAL/SHM files, screenshots, logs, populated `.env` files, credentials, tokens, or build output.
