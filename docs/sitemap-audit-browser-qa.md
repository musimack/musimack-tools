# Phase 21 authenticated browser QA

This procedure runs an explicit test-fixture composition. The normal
`musimack_tools.main:app` remains health-only. The fixture binds both servers to loopback, uses a
local SQLite database and artifact directory, mounts the authenticated private application,
history, artifacts, metadata audits, and sitemap audits, and serves sitemap responses from an
in-memory transport that cannot contact DNS or HTTP.

Run these commands from the repository root in PowerShell. Choose the administrator password in
the current shell; do not write it to `.env` or source control.

```powershell
if (-not (Test-Path .\.venv\Scripts\python.exe)) { py -3.14 -m venv .venv }
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.lock
python -m pip install --no-deps -e backend

$qaRoot = Join-Path (Get-Location) '.qa\phase21'
$artifactRoot = Join-Path $qaRoot 'artifacts'
New-Item -ItemType Directory -Force -Path $artifactRoot | Out-Null
$databasePath = Join-Path $qaRoot 'phase21-browser.db'
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
```

The seed command prints the completed crawl run ID. It persists three durable page-evidence rows
and the corresponding sitemap-recommendation projection. The sitemap fixture is always
`https://example.com/sitemap.xml`; it is an in-memory key, not a network destination.

Start the backend in this PowerShell window:

```powershell
python -m uvicorn qa_sitemap_browser:create_qa_app --factory --app-dir backend\tests --host 127.0.0.1 --port 8000
```

Open a second PowerShell window at the repository root, install the locked frontend if necessary,
and start Vite. Vite's repository configuration proxies `/api` to the loopback backend, so the
browser uses one origin and no public CORS allowance is needed.

```powershell
Set-Location frontend
npm ci
$env:VITE_BACKEND_PROXY_TARGET = 'http://127.0.0.1:8000'
npm run dev -- --host 127.0.0.1
```

Browse to `http://localhost:5173`, sign in with the email and temporary password supplied above,
open **Sitemap Audits**, choose **New sitemap audit**, paste the printed run ID, enter
`https://example.com/sitemap.xml`, clear both discovery checkboxes for the shortest deterministic
run, preview discovery, and start the audit. Review lifecycle, summary counts, action filters,
documents, entries, findings, and CSV/JSON/Markdown exports. No public DNS or HTTP is used.

After stopping both servers, clean up from the repository root:

```powershell
$repositoryRoot = (Resolve-Path .).Path
$qaRoot = (Resolve-Path .\.qa\phase21).Path
if (-not $qaRoot.StartsWith($repositoryRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Refusing to remove a QA path outside the repository.'
}
Remove-Item -LiteralPath $qaRoot -Recurse -Force
Remove-Item Env:MUSIMACK_QA_ADMIN_PASSWORD -ErrorAction SilentlyContinue
```

The fixture never creates an administrator automatically, never embeds a credential, never
changes the production safe-fetch authority, and cannot be enabled without its explicit QA flag.
