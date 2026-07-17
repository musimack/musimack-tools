# Phase 22 authenticated browser QA

This procedure extends the accepted local fixture with durable source-link evidence and link audits. The normal `musimack_tools.main:app` remains health-only. Both servers bind to loopback; all crawl, page, link, redirect, and sitemap fixtures are in memory or local SQLite. No public DNS or HTTP is contacted.

Run from the repository root in PowerShell. Keep the temporary password in the process environment only.

```powershell
if (-not (Test-Path .\.venv\Scripts\python.exe)) { py -3.14 -m venv .venv }
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.lock
python -m pip install --no-deps -e backend

$qaRoot = Join-Path (Get-Location) '.qa\phase22'
$artifactRoot = Join-Path $qaRoot 'artifacts'
New-Item -ItemType Directory -Force -Path $artifactRoot | Out-Null
$databasePath = Join-Path $qaRoot 'phase22-browser.db'
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

Browse to `http://localhost:5173` and sign in as the administrator, or as
`qa-operator@localhost.test`, using the same temporary password. Open **Link
Audits**, create an audit with the printed run ID, and verify readiness;
terminal polling; summary counts; target filters and pagination; occurrence
evidence; redirect chains and loops; working, 404, 410, 5xx, unverified,
non-HTML, external, out-of-scope, mailto, tel, fragment-only, permanent,
temporary, chained, mixed, redirect-to-broken, redirect-to-external, loop, and
repeated sitewide classifications; recommendations; all five artifact exports;
viewer restrictions by signing in as `qa-viewer@localhost.test`; old-route
absence; and no public-host request.

After stopping both servers:

```powershell
$repositoryRoot = (Resolve-Path .).Path
$qaRoot = (Resolve-Path .\.qa\phase22).Path
if (-not $qaRoot.StartsWith($repositoryRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Refusing to remove a QA path outside the repository.'
}
Remove-Item -LiteralPath $qaRoot -Recurse -Force
Remove-Item Env:MUSIMACK_QA_ADMIN_PASSWORD -ErrorAction SilentlyContinue
```

The fixture never creates an administrator automatically, embeds a credential, opens a public network connection, or changes production safe-fetch behavior.
