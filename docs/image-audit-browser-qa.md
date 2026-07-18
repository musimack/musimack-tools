# Phase 24 authenticated browser QA

Run from the repository root in PowerShell. This explicit loopback composition uses real migrations, SQLite, session authentication, private APIs, accepted artifact storage, and deterministic retained crawl evidence. The password exists only in the process environment.

```powershell
if (-not (Test-Path .\.venv\Scripts\python.exe)) { py -3.14 -m venv .venv }
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.lock
python -m pip install --no-deps -e backend

$qaRoot = Join-Path (Get-Location) '.qa\phase24'
$artifactRoot = Join-Path $qaRoot 'artifacts'
New-Item -ItemType Directory -Force -Path $artifactRoot | Out-Null
$databasePath = Join-Path $qaRoot 'phase24-browser.db'
$databaseUrl = 'sqlite+pysqlite:///' + ($databasePath -replace '\\','/')

$env:MUSIMACK_QA_BROWSER_ENABLED = 'true'
$env:MUSIMACK_QA_ARTIFACT_ROOT = $artifactRoot
$env:MUSIMACK_PERSISTENCE_DATABASE_PATH = $databasePath
$env:MUSIMACK_INTERNAL_API_ENABLED = 'true'
$env:MUSIMACK_INTERNAL_API_AUTHENTICATION_ENABLED = 'true'
$env:MUSIMACK_INTERNAL_API_AUTHENTICATION_MODE = 'user_session'
$env:MUSIMACK_INTERNAL_API_SHARED_BEARER_COMPATIBILITY_ENABLED = 'false'
$env:MUSIMACK_INTERNAL_API_REQUIRE_SECURE_COOKIE = 'true'
$env:MUSIMACK_INTERNAL_API_INCLUDE_OPENAPI = 'false'
$env:MUSIMACK_QA_ADMIN_EMAIL = 'david@localhost.test'
$env:MUSIMACK_QA_ADMIN_NAME = 'David QA Administrator'
$env:MUSIMACK_QA_ADMIN_PASSWORD = Read-Host 'Choose a temporary QA password'

python -m alembic -c backend\alembic.ini -x "database_url=$databaseUrl" upgrade head
python backend\tests\qa_sitemap_browser.py bootstrap
python backend\tests\qa_sitemap_browser.py seed
python -m uvicorn qa_sitemap_browser:create_qa_app --factory --app-dir backend\tests --host 127.0.0.1 --port 8000
```

In a second PowerShell window:

```powershell
Set-Location frontend
npm ci
$env:VITE_BACKEND_PROXY_TARGET = 'http://127.0.0.1:8000'
npm run dev -- --host 127.0.0.1
```

Browse to `http://localhost:5173`. Sign in as `qa-operator@localhost.test` with the temporary password, open **Images & Alt Text**, and use the completed run ID printed by the seed command.

## Review checklist

1. Confirm page, image, and scope evidence readiness; create and execute the audit; observe the accepted-to-terminal lifecycle and summary.
2. Review the valid image; missing alt; decorative empty alt; linked empty alt; generic, filename-like, URL-like, and overlong alt; duplicate-alt and same-image inconsistent-alt groups.
3. Review the retained 404, 410, 500, redirecting, redirect-to-broken, external, out-of-scope, data, and placeholder resources. External and unsupported targets must not be fetched.
4. Review missing and invalid dimensions, lazy loading, invalid loading, sitewide impact, page summaries, high-confidence recommendations, and review-only recommendations.
5. Filter by severity, alt state, and resource state; search URL and alt text; traverse cursor pagination; verify empty, loading, and safe error states.
6. Generate all six CSV exports plus JSON and Markdown; download them through the authenticated artifact route; verify stable columns, complete evidence, deterministic ordering, and formula-safe cells.
7. Sign in as `qa-viewer@localhost.test`: reads and permitted downloads work, mutation controls are absent or disabled, and direct create/execute/export POSTs are denied.
8. Verify session expiration, keyboard order, focus visibility, labels/status text, non-color states, reduced motion, long-value wrapping, and narrow/mobile layout.
9. Confirm `/api/audits/images` is 404, all image routes are below `/api/internal/v1/audits/images`, and the default application exposes only `/api/health`.

The fixture deliberately includes every Phase 24 browser-review category listed above, uses no public HTTP or DNS, embeds no credential, and does not alter production safe-fetch behavior. Record this workflow as **Automated authenticated browser QA**; it supplies review evidence but does not replace the required human review decision.

After stopping both servers, clean up from the repository root:

```powershell
$repositoryRoot = (Resolve-Path .).Path
$qaRoot = (Resolve-Path .\.qa\phase24).Path
if (-not $qaRoot.StartsWith($repositoryRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Refusing to remove a QA path outside the repository.'
}
Remove-Item -LiteralPath $qaRoot -Recurse -Force
Remove-Item Env:MUSIMACK_QA_ADMIN_PASSWORD -ErrorAction SilentlyContinue
```
