# Combined Site Audit CSA-06 effective-rule acceptance evidence

## Status

This record covers the bounded effective-rule correction and its deterministic and authorized
real-site evidence. It is ready for David's review. It does not declare CSA-06 accepted and does not
authorize commit, release, deployment, XML publication, or broader crawling.

## Root cause and corrected contract

The initial orchestration path persisted the accepted platform-preset identity and version but did
not invoke the settings resolver before immutable snapshot creation. The snapshot therefore had no
preset rule children, and crawl preparation could pass no preset exclusions to the frontier.

The corrected contract resolves protected security and scope boundaries, the pinned global settings
version, explicitly accepted preset version, pinned eligible site-profile version, disabled
inherited-rule IDs, and per-audit overrides before validation success, preflight success, or snapshot
persistence. Same-layer outcomes use deterministic source, specificity, priority, and stable-ID
precedence while retaining conflict and override evidence. The durable worker uses only the verified
snapshot for crawl preparation, retry, and recovery.

## Deterministic fixture gate

The accepted fixture audit is
`18078c27441a93b3e7b7ea94a807cc0a0bef3fe65e7b53ca62d00ab907402570`, with job
`job-efd331d4e89d-0001` and run `run-efd331d4e89d`. It retained 18 rules: 17 preset and one per-audit
override. Six disabled inherited rules were retained. Twelve rule matches and ten artifacts survived
web and worker restart.

The planted `/cdn-cgi/` URL was discovered once, excluded before enqueue, and never fetched.
`/wp-json/`, pagination, tag, author, date, and category cases followed their configured decision
layers. The UTM variant retained its original URL and normalized identity, while its functional query
parameter remained. The explicit tag override became primary and retained the overridden preset
evidence.

Fixture populations were 141 discovered, 139 enqueued, 139 fetched, 136 parsed HTML, 136 indexable,
130 canonical, 128 metadata-scoring eligible, six excluded, three resources, one failed, one partial,
and eleven indeterminate.

## Authorized bounded Aluma comparison

Pre-correction CSA-06 acceptance audit retained as evidence of unresolved preset-rule snapshot
behavior.

| Evidence                                    |                                                     Pre-correction |                                                          Corrected |
| ------------------------------------------- | -----------------------------------------------------------------: | -----------------------------------------------------------------: |
| Audit                                       | `f0a8da53536aae853ca4e9ef8122efb3b1a2a6c1330d07d574205ede6ef5870b` | `fa99b4ac9331c62ad5cf257c6986ca928c99716e4b0f7456cc9caa93fc10374f` |
| Job                                         |                                            `job-4b0bc1c00863-0001` |                                            `job-a65bcaa6912e-0001` |
| Run                                         |                                                 `run-4b0bc1c00863` |                                                 `run-a65bcaa6912e` |
| Discovered                                  |                                                                121 |                                                                121 |
| Enqueued                                    |                                                                 25 |                                                                 25 |
| Fetched                                     |                                                                  3 |                                                                  2 |
| `/cdn-cgi/` discovered / enqueued / fetched |                                                          3 / 2 / 1 |                                                          3 / 0 / 0 |
| Effective rules                             |                                                                  0 |                                                                 19 |
| Rule sources                                |                                                               None |                                                         Preset: 19 |
| Rule matches                                |                                                                  0 |                                                                  3 |
| Excluded by effective discovery rule        |                                                                  0 |                                                                  3 |
| Metadata-scoring eligible                   |                                                                  2 |                                                                  2 |
| Sitemap eligible                            |                                                                  0 |                                                                  0 |
| Partial URLs                                |                                                                 22 |                                                                 23 |
| Artifacts                                   |                                                                 10 |                                                                 10 |
| Final retained crawl bytes                  |                                                            320,728 |                                                            317,194 |
| Final retained crawl elapsed seconds        |                                                              5.482 |                                                              3.633 |

Both audits used exact-host scope and the authorized bounds: 25 URLs, depth two, 120 seconds,
40,000,000 accepted bytes, concurrency one, queue 100, two-second request delay, five redirects,
and 3,000,000 bytes per response. Publication and summary writing were disabled. The corrected audit
explicitly accepted WordPress `wordpress-1` and eight tracking parameters. Its snapshot retained 19
preset rules, including `/cdn-cgi/`; all three matching URLs retained original and normalized
evidence, were excluded before enqueue, and were not fetched. All ten authenticated artifacts are
available, including three applied-rule rows and the configuration snapshot. No live XML publication
occurred.

Both runs remain `partially_completed` because retained specialist evidence is explicitly partial or
unavailable at the bounded crawl depth. The corrected result has zero crawl failures, no issue
groups, and keeps the same clear primary denominators rather than treating partial evidence as
complete.

## Final deterministic acceptance matrix

The final local runs used only `http://127.0.0.1:13765/` through a process-local, exact-origin
fixture adapter. That adapter cannot be enabled by production configuration and does not change the
production SSRF validator.

| Audit | Preset | Discovered | Fetched | HTML | Metadata eligible | Excluded | Rules / matches | Artifacts |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| WordPress deterministic | WordPress | 141 | 139 | 136 | 128 | 6 | 18 / 12 | 10 |
| Custom | Custom | 141 | 140 | 136 | 129 | 1 | 1 / 1 | 10 |
| No preset | None | 141 | 140 | 136 | 130 | 0 | 0 / 0 | 10 |
| Parameter-heavy | WordPress | 142 | 140 | 137 | 127 | 6 | 19 / 19 | 10 |

All four runs are truthfully `partially_completed`: one URL failed, one retained partial evidence,
and one optional internal-link specialist was unavailable. WordPress, Custom, and parameter-heavy
runs retained four complete, three partial, and one unavailable module. No preset retained three
complete, four partial, and one unavailable module. Unavailable depth is never projected as zero.

The fixture exercised redirects and loops, robots blocking, noindex, missing and duplicate
metadata, canonical mismatch, sitemap index and child URL set, sitemap-only orphan evidence,
broken and nofollow links, image-alt variants, broken and redirecting images, JSON-LD, microdata,
malformed structured data, structured-data duplication, status and content-type variance, and
technical WordPress paths. Combined results retain bounded core facts; specialist-only deep
metadata and internal-link detail remains owned by the specialist modules.

## Parameter-heavy evidence

The retained parameter audit is
`d6415fc13f688b9560bf4b5b2a6edc52553df7291da998cc060bbcabeb810f0e`, with job
`job-ddd354c391eb-0001`. Before acceptance no tracking rules are resolved. After explicit
acceptance, eight tracking rules cover `utm_source`, `utm_medium`, `utm_campaign`, `utm_term`,
`utm_content`, `gclid`, `fbclid`, and `msclkid`.

Ten retained original tracking variants matched all eight rule IDs. Repeated and empty values,
query-order variants, and collisions preserved discovery evidence while collapsing to stable
parameterless or functional normalized identities. Functional `id`, `page`, `sort`, `a`, `b`, and
`variant` parameters remained. The run retained six query-bearing normalized page identities and
made every metadata and sitemap decision traceable to its original and normalized URL.

## Roles, security, and errors

Live administrator, operator, viewer, and anonymous checks agreed with the centralized permission
map. Administrators and operators can submit and cancel; only administrators can manage global
settings and reusable profiles; viewers can filter, paginate, inspect details, and download
artifacts but cannot mutate; anonymous private API and artifact access returns 401. Viewer and
operator direct settings mutation returns 403.

The focused security, authentication, network, orchestration, artifact, recovery, and operations
gate passed 245 tests. It covers valid, invalid, expired, revoked, repeated, distinct, and excessive
session-cookie candidates; logout; direct routes; DNS rebinding and redirect revalidation; unsafe
schemes and addresses; scope, port, response, accepted-byte, queue, URL, duration, pagination,
retry, reconcile, and export bounds; and stable sanitized error envelopes. `/api/site-audits` is
absent. The direct backend and private HTTPS ingress return HTTP 404 for `/docs`, `/redoc`,
`/openapi.json`, `/api/internal/v1/docs`, `/api/internal/v1/redoc`, and
`/api/internal/v1/openapi.json`; none of these reserved paths expose documentation, schema metadata,
or the frontend SPA fallback. The default application composition remains `/api/health` only.

Invalid seed, unsafe scheme, disallowed host, DNS and connection failure, redirect loop, unavailable
or invalid robots/sitemap evidence, size and crawl-limit exhaustion, worker/module/artifact failure,
stale pagination, projection conflict, cancellation, recovery, retry, archive, and authorization
states have direct automated coverage. Errors retain a user explanation and stable code without
tracebacks, local paths, secrets, response bodies, or duplicate mutation.

## Responsive and accessibility review

Browser review covered 40 loaded combinations across 1440, 1024, 768, and 390 CSS pixels: wizard,
lifecycle, Summary, Pages, Issues, Sitemap, Exclusions, Evidence, Settings Snapshot, and Artifacts.
Every view had one visible H1 and one main landmark, no document-level overflow, no duplicate IDs,
and no unbounded table. Mobile page and issue details also passed; long URLs and hashes wrap, result
tabs remain reachable, and external crawl links use a labeled new-tab action with
`rel="noopener noreferrer"`.

Form controls retain programmatic labels, the skip link targets the focusable main landmark,
loading states use textual status, icon decoration is hidden, focus-visible and reduced-motion CSS
are present, and no browser console warning or error occurred. Keyboard, dialog focus, validation
summary, accessible sorting, and role-state behavior are additionally covered by frontend tests.
No dedicated screen-reader product was available in the isolated Windows review environment; that
is an environment limitation, not a claim of assistive-technology certification.

## Restart, recovery, backup, and restore

A draft survived web/worker restart without revision drift. A separate audit was interrupted while
`crawl_inventory` was running; after restart it completed with the same job
`job-a47c7a8273be-0001` and run `run-a47c7a8273be`, zero retries, and all ten artifacts. Repository
constraints and focused tests cover lease expiry and interruption at ingestion, specialist
reconciliation, summary construction, and artifact generation. No duplicate job, run, URL,
discovery, rule match, finding, issue group, membership, module, summary, or artifact was observed.

The offline backup retained 122 files: a 26,091,520-byte database plus 121 artifact files. Restore
into a separate target preserved all 120 database table counts, all 121 artifact relative paths and
SHA-256 values, three users and roles, 12 audits and immutable snapshots, 1,495 URL rows, 4,568
discovery rows, 8,636 population rows, 47 rule matches, 36 findings, 34 issue groups, 88 module
statuses, 11 summaries, and 110 Site Audit artifact associations. Both database revisions are
`0018_combined_site_audit_orchestration`. The restored composition authenticated administrator and
viewer sessions, retained authorization, served the fixture audit and all ten artifacts, and denied
viewer settings mutation.

## Artifact acceptance

All ten fixture artifacts downloaded through a Viewer session. Filename, purpose, MIME type,
nonzero size, schema version, lifecycle, integrity state, row count, and SHA-256 agreed with retained
metadata. Content scans found no raw HTML, response body, local path, token, certificate, or secret.
Files survived process restart and isolated restore. Sitemap XML remained retained and was never
published.

## Performance correction and runtime results

Before correction, the production build emitted one 505,071-byte JavaScript entry chunk (132.29 kB
gzip), 17,602 bytes of CSS (4.43 kB gzip), and a 553-byte entry document. Total uncompressed output
was 523,226 bytes; Site Audit routes were not lazy loaded and Vite emitted its 500 kB warning.

The bounded correction uses React `lazy`/`Suspense` and Vite's existing split-point behavior. The
post-correction main chunk is 436,670 bytes (116.91 kB gzip); Site Audit pages are a separate
69,309-byte chunk (16.77 kB gzip). Total uncompressed output is 524,134 bytes because the same code
is retained with a small split-loader cost, while initial JavaScript drops 68,401 bytes and the Vite
warning is eliminated. No dependency was added.

Live retained-result routes loaded in approximately 0.42-0.45 seconds. Pages rendered exactly 50,
100, 141 for a 500-row page, and 141 for bounded All. Issues, sitemap, exclusions, evidence, and
artifact routes remained responsive, with no overflow, request loop, or browser console error.

## Data-quality conclusion and known limitations

Primary population denominators reconcile with retained inventory. Technical exclusions remain
inspectable and do not inflate metadata rates; original and normalized URLs remain explainable;
rule reasons, source, conflicts, and overrides remain durable; recommendations are evidence-based;
issue groups retain priority rationale; partial evidence is labeled partial; unavailable modules
are labeled unavailable instead of zero; and artifact row counts agree with browser projections.

Safe follow-up: Combined Site Audit intentionally does not duplicate every specialist module's deep
finding taxonomy. For example, duplicate/length metadata and full internal-link topology remain in
their specialist views, while the combined view exposes bounded core facts and explicit provenance.
This is the accepted ownership contract, not missing retained evidence. A future usability review
may add links to more specialist detail without changing combined denominators.

Engineering recommendation: **READY FOR FINAL PRODUCT-OWNER ACCEPTANCE**. This does not declare
David's acceptance and does not authorize staging, commit, publication, migration, release, or
deployment.
