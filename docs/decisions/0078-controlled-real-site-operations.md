# 0078: Controlled real-site operations

Status: proposed for CSA-07 product-owner review

## Decision

Reuse the existing versioned Site Audit settings and immutable snapshot architecture for a
fail-closed global real-site enable/suspend control. Keep the application private and authenticated.
Bind each outbound HTTP connection to an address approved by the central destination validator,
while retaining the original Host header and TLS server name. Revalidate retries and every redirect.

No new persistence table is required. The existing global configuration JSON retains authorization
versions, Site Audit snapshot JSON retains the accepted policy and identities, and the existing
bounded durable result projection JSON retains safe operational evidence.

Each new Site Audit execution is distinct even when its immutable configuration is identical to a
prior audit. The execution/run digest combines the portable configuration with a submission-scoped
audit discriminator. Configuration and snapshot hashes stay content-stable; they are not evidence
lookup keys. Retry and recovery keep the already attached execution identity. There is no implicit
retained-result reuse.

Projection is fail-closed. Crawl status, terminal result, page summary, every page record,
specialist association, finding reference, and artifact association must resolve to the attached
job/run owner. Terminal persistence failure, missing evidence, an impossible population relation,
or an owner mismatch marks execution integrity failed and suppresses final artifacts.

Monotonic crawl clock markers are internal measurement inputs, not wall-clock instants. Durable
result JSON and the application projection expose only `crawl_elapsed_seconds`; database lifecycle
timestamps remain ISO wall-clock instants. Legacy marker pairs are converted to a duration when
valid and otherwise shown as unavailable.

## Consequences

Real-site work defaults to suspended. Operators cannot begin new real-site validation, preflight,
or submission until an administrator creates an enabled settings version. Emergency suspension
does not mutate an already-running immutable job; it stops new outbound work and operators retain
cancellation. Direct IP URLs remain blocked under the established product policy.

Connection reuse is disabled for the safe fetch client. This favors deterministic destination
binding over throughput and is consistent with the conservative internal-evaluation concurrency.
No public ingress, proxy rotation, browser impersonation, CAPTCHA bypass, dependency, lock-file
change, or migration is introduced.

## Corrected acceptance evidence

Two identical deterministic fixture submissions produced distinct job/run owners and disjoint
ten-artifact sets while retaining one stable configuration hash. The single authorized corrected
Aluma submission then produced distinct run `run-abd48e691d43` for job
`job-abd48e691d43-0001`, even though its configuration snapshot matched historical
`run-fe31b793f467`. Its 25 admitted and fetched records, 23 parsed HTML records, findings,
specialist projections, counters, and ten hash-verified artifacts all resolve to that new owner.
Only a 30.63-second elapsed crawl duration is serialized from the monotonic clock. Settings version
6 restored the final suspended state after the evaluation.
