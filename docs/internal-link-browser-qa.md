# Phase 23 authenticated browser QA

The accepted loopback QA composition now enables Internal Links over its seeded crawl, page, link, redirect, canonical, and scope evidence. The default app remains health-only. Run from the repository root in PowerShell; keep the temporary password only in the process environment.

```powershell
if (-not (Test-Path .\.venv\Scripts\python.exe)) { py -3.14 -m venv .venv }
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.lock
python -m pip install --no-deps -e backend

$qaRoot = Join-Path (Get-Location) '.qa\phase23'
$artifactRoot = Join-Path $qaRoot 'artifacts'
New-Item -ItemType Directory -Force -Path $artifactRoot | Out-Null
$databasePath = Join-Path $qaRoot 'phase23-browser.db'
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

Browse to `http://localhost:5173`, sign in as the operator, open **Internal Links**, enter the printed run ID, check evidence, create and execute the audit, and observe polling to a terminal state. Review summary, reachable shallow/deep pages, true and sitemap-only orphan states where fixture evidence supports them, redirect-only and nofollow-only support, low-inlink/high-outlink pages, hub/authority candidates, broken and redirecting edges, generic/empty/URL/concentrated anchors, and high/medium/review-only opportunities. Exercise severity/state filters, URL search, cursor pagination, every CSV plus JSON and Markdown, and authenticated artifact downloads. Then verify viewer mutation restrictions, session expiration, keyboard navigation, narrow-width layout, `/api/audits/internal-links` absence, and health-only default composition. This is a human checklist; automated validation does not claim browser acceptance.

After stopping both servers:

```powershell
$repositoryRoot = (Resolve-Path .).Path
$qaRoot = (Resolve-Path .\.qa\phase23).Path
if (-not $qaRoot.StartsWith($repositoryRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Refusing to remove a QA path outside the repository.'
}
Remove-Item -LiteralPath $qaRoot -Recurse -Force
Remove-Item Env:MUSIMACK_QA_ADMIN_PASSWORD -ErrorAction SilentlyContinue
```

The fixture does not create an administrator automatically, embed a credential, contact public HTTP/DNS, or alter production safe-fetch behavior.
