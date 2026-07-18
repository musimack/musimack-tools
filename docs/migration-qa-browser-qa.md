# Migration QA authenticated browser QA

Use only loopback fixture origins and a disposable temporary directory. Do not use production credentials, a populated `.env`, or a public host.

1. Create a temporary SQLite database and artifact root outside the repository.
2. Upgrade to `0013_website_migration_qa` and seed a completed destination crawl with broad retained evidence.
3. Seed an operator and viewer through the existing authentication service; keep credentials in process memory.
4. Start the private FastAPI fixture and Vite on separate `127.0.0.1` ports.
5. As operator, create a project, ingest the fixture inventory and redirect map, check readiness, execute, and inspect the summary and eight resource views.
6. Generate all eight exports. Verify authenticated downloads, JSON schema/version, and 18 Markdown headings.
7. As viewer, confirm reads work and mutation controls are absent or forbidden.
8. Confirm unauthenticated and expired sessions fail closed and malformed identifiers trigger no request.
9. Stop servers and delete the temporary database, WAL/SHM files, artifacts, logs, and fixture credentials.

Pass criteria: no request leaves loopback, no secret appears in UI or logs, no repository file changes during QA, and planned-versus-observed labels and indeterminate states remain visible.

## Phase 26 completion evidence

The final corrected browser pass used a disposable SQLite database and artifact root under the system temporary directory. The fixture produced 7 source rows, 7 mappings, 6 redirect rows, 6 comparisons, 183 findings, 99 recommendations, and all 13 sitewide pattern categories. Readiness was `ready_with_warnings`, and the terminal state was `completed_with_warnings`.

Operator QA covered all eight resource views, source filtering, cursor pagination, all eight export formats, export history, and an authenticated download. Viewer QA confirmed that all eight export mutation controls were disabled while all eight authenticated download controls remained available. The narrow 390 x 844 viewport exposed the mobile navigation. The browser console reported zero warnings or errors.

The final corrected backend pass recorded 94 requests, including 12 migration-QA POST requests and 2 authenticated downloads. It recorded zero 5xx responses, zero tracebacks, and only the loopback client host `127.0.0.1`. Eight export-history rows and eight artifact records were persisted. The export row counts were: comparisons 6, findings 183, JSON 327, mappings 7, Markdown 18 headings, recommendations 99, redirects 6, and sitewide 13.

An initial pass exposed a SQLite timestamp-normalization defect in evidence-expiry evaluation. The repository comparison now treats SQLite's naive persisted timestamp as UTC; a direct regression test covers the boundary. The evidence above is from the complete corrected rerun after that fix. Both temporary servers were stopped and the disposable database, artifacts, logs, and credentials were removed after verification.
