# Final security review

## Threat boundaries

The default application is a health-only process with schema/documentation handlers disabled.
Product routes require explicit private
composition, trusted-host configuration, loopback binding behind a private TLS ingress, and
authentication. Same-origin browser requests use a Secure, HttpOnly, SameSite=Strict cookie scoped
to `/api/internal/v1`; no cookie Domain is set. CORS is not enabled as a cross-origin trust mechanism.

## Authentication and authorization

Passwords are normalized and validated, then stored with salted PBKDF2-HMAC-SHA256 using bounded
configuration. Login failures are generic, rate limited, audited, and can lock accounts. Sessions
have idle, rolling, and absolute bounds, rotate atomically, are stored only as hashes, and are revoked
by logout, password/role/lifecycle changes, or explicit session management.

Every private request is authenticated before the centralized resource/operation permission mapping
is applied. Viewer is read-only, operator adds job/audit submission and cancellation, and
administrator receives the complete permission set. Shared-bearer compatibility is explicit and
hybrid mode gives a presented session cookie precedence over bearer fallback.

Phase 29 corrected duplicate same-name cookie handling. Raw Cookie headers are enumerated without
framework order collapse, identical values are de-duplicated, the only valid session is selected when
stale values coexist, and multiple distinct valid sessions fail closed. Logout revokes the exact
session selected by authentication, including a just-rotated token.

## Network and request safety

The fetch boundary rejects credentials, unsafe schemes, non-HTTP destinations, loopback/private/
link-local/reserved addresses, DNS changes, unsafe redirect hops, excess redirects, excess bytes, and
timeouts. Each connection is bound to validated resolution evidence. Crawl concurrency, pacing,
depth, duration, URL count, queue size, and total bytes are bounded. Request-body and pagination
limits prevent unbounded private API input/output.

Trusted proxies and trusted networks are explicit CIDR allowlists. Forwarded headers are ignored or
rejected outside that boundary; host allowlisting is applied by the production runtime. Request IDs
are generated/validated as bounded evidence and appear in safe operator support references.

## Filesystem, artifacts, backup, and restore

Publication, artifacts, backup, restore, and release packaging canonicalize roots, reject traversal,
symlinks, junctions/reparse points, path collisions, unsafe archive members, and source mutation.
Artifact downloads are authorized, size/hash verified, and revalidated before streaming. Backups use
SQLite's backup API plus integrity checking and content manifests; restore verifies hashes and the
exact migration before atomically publishing into a new location.

## Secrets, logs, CI, and release tooling

Credentials and tokens are excluded from URLs, structured diagnostics, manifests, candidates, and
committed documentation. Error normalization and log redaction prevent tracebacks, raw SQL,
credentials, filesystem roots, and provider tokens from reaching browser responses. Operators must
still control log access and retention.

CI uses read-only repository permissions, immutable full-length action pins, bounded timeouts and
concurrency, no `pull_request_target`, no secret-bearing release step, and no deployment. The manual
candidate workflow validates a bounded identifier and exact commit, produces deterministic ZIP
bytes, checksums and manifests, excludes runtime/generated/private material, and never tags,
releases, or deploys.

## Remaining risk

The supported topology depends on a correctly configured private ingress, OS account isolation,
trusted local storage, supervision, log handling, and off-host backup policy. Capacity and broad
assistive-technology testing remain bounded as described in `known-limitations.md`. No unresolved
authentication bypass, authorization bypass, SSRF bypass, arbitrary filesystem access, secret
exposure, data-corruption, or public-route exposure was found.
