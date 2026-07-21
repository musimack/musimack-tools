# Controlled real-site operations

CSA-07 supports outbound crawling of explicitly reviewed public websites while the Musimack SEO
Toolkit remains private, authenticated, and bound to localhost or another approved internal
interface. Outbound access is fail-closed and is suspended by default.

## Network and authorization path

The browser submits a private Site Audit request to the authenticated internal API. The Site Audit
service resolves the versioned global settings, writes an immutable snapshot, and submits the
bounded request to the durable job registry. A separate worker claims the job and passes robots,
sitemap, and page requests through the same `DestinationSafetyValidator` and
`SafeSingleUrlFetcher` boundary.

The destination boundary accepts only HTTP and HTTPS on configured ports, rejects credentials and
IP-literal URLs, rejects local/internal/metadata hostnames, bounds DNS answers and DNS time, and
requires every answer to be globally routable. IPv4 private, loopback, link-local, carrier-grade
NAT, benchmark, documentation, multicast, reserved, and unspecified ranges are blocked. IPv6
loopback, link-local, unique-local, documentation, discard-only, NAT64 translation, multicast,
reserved, unspecified, and blocked IPv4-mapped forms are blocked.

After validation, the HTTP connection is made to the selected validated address rather than
resolving the hostname again. The original hostname remains the HTTP Host header and TLS server
name, so normal certificate verification continues. Connections are not reused. Each retry and
each redirect performs a fresh complete policy evaluation; a mixture of public and prohibited DNS
answers fails closed. This closes the validation-to-connection DNS rebinding gap without a proxy or
new dependency.

## Administrative control

An administrator uses **Site Audit Settings > Controlled real-site operations** to create a new
immutable global settings version that enables or suspends outbound real-site work and controls the
conservative defaults. Operators can validate, preflight, submit, cancel, and retry only through
their existing permissions. Viewers remain read-only. Suspension prevents new real-site
validation, preflight, and submission. Jobs that are already running retain their immutable policy
and bounds, continue to completion, and remain cancellable by an administrator or operator.

The default limits are 100 URLs, depth 3, 300 seconds, 50 MB accepted bytes, concurrency 1, queue
500, one-second minimum delay, five redirects, and 3 MB per response. Existing server hard maxima
remain authoritative. DNS has a five-second bound; connection, read, write, pool, total-request,
retry, accepted-byte, response, queue, duration, and cancellation controls remain unchanged.

Every real-site snapshot retains the settings version and hash, authorization identity,
submission identity, operation mode, `seo-toolkit-outbound-destination-policy-v1`, effective
limits, and `Musimack SEO Toolkit/1.0`. Durable run projections retain bounded counts, timestamps,
redirect and rejection counts, robots outcomes, and at most 256 SHA-256 fingerprints of resolved
addresses. Raw response bodies are not added to operational evidence.

## Execution identity and retained-evidence ownership

CSA-07 uses unique execution identity (Option B). Audit identity and the immutable settings
snapshot remain stable according to their existing contracts, and the configuration hash remains
content-addressed. A newly submitted audit supplies its audit identity as an execution
discriminator to crawl preparation. The run digest therefore combines the portable configuration
with that discriminator. Two separate audits with identical settings receive different run and
job identities; the system does not reuse a completed crawl implicitly.

Validation, preflight, and submission for one audit reproduce the same execution identity. A
projection retry or lease recovery retains that audit's run and job identity and is idempotent;
it does not create a second evidence or artifact set. Page evidence is accepted only when its
summary and every record match both the attached run and job. Specialist associations, findings,
operational counters, and final artifacts are checked against that same owner. Missing evidence,
a terminal persistence failure, a stale result, or any owner mismatch fails the audit closed and
prevents final artifact generation. Historical evidence is never selected by configuration or
snapshot hash.

Required population invariants are checked before export: fetched cannot exceed admitted, parsed
HTML cannot exceed fetched, and metadata-scoring eligibility cannot exceed parsed HTML, canonical,
or indexable populations. Sitemap inventory is intentionally separate and is not assumed to be a
strict subset of crawl admission.

The first two authorized Aluma evaluations are preserved unchanged as historical evidence. They
demonstrated the former configuration-only run collision and stale-projection failure. They are
not rewritten or silently relabeled.

The corrected, single additional Aluma evaluation completed on 2026-07-21 after deterministic
fixture and full-suite validation. Audit
`300e0a785c12fb5a5daf09be032bf36f01a9bc2eee56c93b234f179ad6f8609e` owns job
`job-abd48e691d43-0001`, attempt 22, and run `run-abd48e691d43`. Its run identity is distinct from
historical `run-fe31b793f467`, while both runs retain the same stable crawl-configuration snapshot
`d50144835fad5f3d70b27125d8eff197860bde5beb4d91457cbbd5819dda0710`. This demonstrates distinct
execution ownership without changing configuration identity.

The corrected evaluation admitted and fetched 25 URLs, parsed 23 HTML pages, and retained 22
metadata-eligible pages. The wider discovery inventory contains 159 URLs, including 24 scope
denials and 103 over-limit discoveries; those are evidence, not fetch failures. Existing-sitemap
evidence remains separate at seven documents and 103 entries. Nine findings form four issue groups,
including the retained long-title finding. Aggregate specialist-aware accounting records 36
requests, 3,005,631 accepted bytes, two redirects, zero rejected destinations, and 24 scope
denials. All ten final artifacts belong to the new job/run and their physical SHA-256 values match
their durable records. The crawl duration is retained as 30.63 seconds, all lifecycle timestamps
are wall-clock instants, and no January 1970 rendering remains. Real-site operations were enabled
by settings version 5 and returned to suspended in version 6 after the role and artifact checks.

Remaining limitations are explicit: the accepted URL ceiling makes this a partial-population
evaluation; sitemap-only and over-limit discoveries remain indeterminate unless admitted by a
larger separately authorized audit. Direct public IP targets remain prohibited, publication and
external AI remain disabled, and no result-reuse mode is provided.

## Timestamp and duration semantics

Audit and orchestration `submitted_at`, `started_at`, `completed_at`, `created_at`, and `updated_at`
values are database wall-clock instants and may be displayed as calendar dates. Crawl clock values
are monotonic process-local markers. New durable result projections retain only their derived
`crawl_elapsed_seconds` duration and never serialize those markers as timestamps. Historical
durable JSON that contains both legacy markers is read as a non-negative elapsed duration; invalid
or incomplete legacy timing is reported as unavailable. Evidence and exported configuration JSON
use the elapsed field, and the UI labels and formats it as a duration, so monotonic values cannot
appear as January 1970 dates.

Direct public IP URLs remain prohibited by the existing product policy. There is no approved
public support endpoint, so the user-agent includes no invented URL or contact address.

## Private retained evaluation composition

The retained CSA-06 composition at `https://localhost:13443` is the CSA-07 human-evaluation
environment. It has the existing trusted localhost certificate, authenticated users, durable
SQLite database, durable artifact root, ingress, web process, and worker. The application is not
publicly reachable. Real-site operations remain suspended until David creates an enabled global
settings version and explicitly authorizes a named target. No public crawl is part of CSA-07
automated validation.

Start, stop, and restart the composition with its retained supervisor scripts in
`%TEMP%\musimack-csa06-qa-20260720`. Start the application and worker before the HTTPS ingress;
stop ingress before the worker and application. Health is `GET https://localhost:13443/api/health`.
Authenticated readiness and Site Audit diagnostics provide the durable worker and dependency
state. Never place a password, session token, or bearer token in a command line or log.

## Human-evaluation portfolio (not executed)

Every row requires David to name or approve the website and confirm an authorization basis before
submission. Start with the stated limit and stop immediately on access-owner request, repeated
429/403 responses, robots prohibition, unexpected scope expansion, or safety-control failure.

| Website slot | Authorization basis required | Preset | Scope | URLs / depth | Delay / concurrency / duration | Risks and evaluation questions |
|---|---|---|---|---:|---|---|
| Small WordPress site (TBD) | Owner permission or David's documented authorization | WordPress | exact host | 25 / 2 | 2s / 1 / 120s | Plugins, feeds, wp-json; are exclusions and metadata correct? |
| Larger WordPress site (TBD) | Same | WordPress | exact host | 100 / 3 | 2s / 1 / 300s | Sitemap index and archive growth; are limits and cancellation responsive? |
| Shopify site (TBD) | Same | Shopify | exact host | 50 / 2 | 2s / 1 / 240s | Product variants and CDN redirects; are canonicals and scope safe? |
| Squarespace or Wix site (TBD) | Same | Matching preset | exact host | 50 / 2 | 2s / 1 / 240s | Generated paths and script-heavy HTML; is retained evidence useful? |
| Custom site (TBD) | Same | Custom | exact host | 50 / 2 | 2s / 1 / 240s | Nonstandard metadata and status codes; do modules degrade safely? |
| Parameter-heavy site (TBD) | Same | Custom | exact host | 50 / 2 | 3s / 1 / 240s | Query explosion; do rules, queue, and deduplication remain bounded? |
| Cloudflare site (TBD) | Same | Matching preset | exact host | 25 / 1 | 3s / 1 / 120s | 403/429/challenge behavior; does the crawler stop without bypass attempts? |
| Sitemap-index site (TBD) | Same | Matching preset | exact host | 100 / 2 | 2s / 1 / 300s | Nested index limits and XML evidence; are counts consistent? |
| Robots-restricted site (TBD) | Same | Matching preset | exact host | 25 / 2 | 3s / 1 / 180s | Robots denial; are prohibited URLs skipped and explained? |
| Redirect/canonical-complex site (TBD) | Same | Custom | exact host | 50 / 2 | 2s / 1 / 240s | Cross-host redirects and canonical disagreement; are every hop and scope decision safe? |
