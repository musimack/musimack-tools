# Current Crawl Policy

## Audit reuse of crawl evidence

Metadata audits consume the bounded Phase 20A projection only after a run is terminal. They issue no DNS, HTTP, redirect, robots, or parsing work. Failed fetches never imply missing HTML metadata; non-HTML pages never receive HTML metadata findings; missing evidence remains distinct from empty evidence; partial or truncated evidence carries explicit partial determinacy.

Canonical-target findings are limited to targets already represented by durable evidence. Sitemap recommendation state remains separate and is never recomputed by the audit engine. Phase 21 sitemap comparison, link graphs, broken links, images, schema, keywords, content scoring, and AI rewriting remain deferred.

This document describes URL, scope, and internal single-URL network-safety policy. A successful
scope decision alone is **not** authorization to perform a network request.

## URL normalization contract

`normalize_url` accepts absolute HTTP and HTTPS URLs. Relative references are accepted only
when the caller supplies an already validated `NormalizedUrl` base. Missing schemes are never
guessed, and protocol-relative references require an explicit base.

The returned value retains the original submitted string and exposes the normalized absolute
URL, scheme, normalized hostname, effective port, and origin. `NormalizedUrl` instances cannot
be constructed through their public constructor; they come from the validation boundary.

Normalization:

- accepts only `http` and `https`;
- rejects missing hosts, URL credentials, malformed ports, invalid hostname labels, whitespace,
  control characters, and invalid percent escapes;
- lowercases schemes and hostnames;
- converts Unicode hostnames to lowercase ASCII IDNA form;
- removes fragments;
- removes explicit port 80 from HTTP and port 443 from HTTPS;
- preserves other valid ports and reports effective ports for all URLs;
- changes an empty path to `/`;
- removes literal `.` and `..` path segments;
- preserves path case, repeated slashes, and trailing-slash distinctions;
- preserves query order, repeated keys, blank values, name/value casing, and all parameters;
- preserves percent-encoded reserved characters and uppercases escape hex digits without
  decoding them into delimiters; and
- is idempotent.

It does not perform canonicalization, strip UTM/session values, sort queries, merge `www` with
an apex host, merge slash variants, resolve DNS, or make an HTTP request.

## Scope policies

Every policy has a validated seed URL, host-matching mode, and allowed scheme/effective-port
pairs. The seed's scheme and effective port are always included.

### Exact host

This is the default. Only the seed hostname is allowed. `example.com` and `www.example.com` are
distinct. Hostname comparison occurs after lowercase and IDNA normalization.

### Include subdomains

The seed hostname and true descendants ending with `.` plus the seed hostname are allowed.
`blog.example.com` is a descendant of `example.com`; `badexample.com` and
`example.com.evil.test` are not. A seed of `shop.example.com` can include
`news.shop.example.com`, but it does not broaden to `example.com` or `blog.example.com`.

### Explicit approved hosts

The seed host and a normalized explicit set of additional hosts are allowed. Approved hosts use
the same hostname validation as URLs. Approval of `blog.example.com` does not imply approval of
`news.blog.example.com`.

## Port and scheme sensitivity

HTTP without an explicit port has effective port 80; HTTPS has effective port 443. Explicit
default ports normalize to the same origins. Other ports are denied unless their exact
scheme/effective-port pair is configured. HTTP and HTTPS remain distinct.

This is a crawl-scope decision only. It is not the future network port-safety policy.

## Stable reason codes

| Code | Meaning |
|---|---|
| `allowed_exact_host` | Host exactly matches the seed host. |
| `allowed_subdomain` | Host is a true descendant under subdomain mode. |
| `allowed_approved_host` | Host appears in the explicit approved set. |
| `denied_host_mismatch` | Host is outside the selected host policy. |
| `denied_false_suffix_match` | Text suffix resembles the seed but lacks a label boundary. |
| `denied_port_mismatch` | Effective port is not allowed for the destination scheme. |
| `denied_scheme` | Scheme is unsupported or absent from allowed origins. |
| `denied_invalid_url` | Destination failed URL validation for another reason. |

Each decision also includes a human-readable explanation, evaluated hostname and effective
port when available, and the relevant configured host and origin.

## Network safety and crawl scope

The fetcher requires both crawl-scope approval and independent network-safety approval before
every request. Scope answers whether a URL belongs to the approved site boundary. Network safety
answers whether its scheme, credentials, hostname, effective port, and all resolved addresses
are permitted. Either layer can deny the request.

Production safety rejects `localhost`, descendants of `localhost`, names ending in `.local`,
`.internal`, `.home`, or `.lan`, and known metadata aliases. IP-literal URLs are rejected by
default. Every DNS answer is checked; a mixed public/prohibited answer set is rejected rather
than silently selecting the public member.

Prohibited addresses include loopback, private, link-local, multicast, unspecified, reserved,
documentation/test, carrier-grade NAT, benchmarking, IPv4-mapped unsafe IPv6, IPv6 unique-local,
and represented site-local ranges. This includes `169.254.169.254`, RFC1918, `100.64.0.0/10`,
the standard IPv4 documentation ranges, `2001:db8::/32`, `fc00::/7`, and `fe80::/10`.

Only configured production ports are permitted; defaults are 80 and 443. HTTP and HTTPS can be
disabled independently. Scope origin approval does not override the production port policy.

## Requests, redirects, and limits

Requests are asynchronous GETs with `MusimackSEOToolkit/0.1`, an HTML-capable `Accept` header,
no cookies, no authorization, no arbitrary caller headers, no automatic redirects, no browser,
and no environment proxy inheritance by default. Connect, read, write, pool, and total-deadline
timeouts are explicit.

Application events retain query-free URL summaries, host, port, correlation identifier when
provided, duration, and stable failure codes. Bodies, credentials, cookies, authorization,
environment values, and full query strings are excluded. HTTPX's own query-bearing INFO request
logger is held at WARNING by application logging configuration.

301, 302, 303, 307, and 308 are handled manually. Each `Location` is resolved against the
current normalized URL, fragments are removed by normalization, and the resulting target is
checked for loops, hop limits, scope, DNS, address safety, and ports. Blocked hops remain in the
typed redirect chain and never masquerade as a successful previous response.

Response headers are bounded and selected SEO-relevant headers are retained without
interpretation. `Content-Length` is validated but never trusted as the sole limit. Bodies are
streamed and retained only when fully within the default 5,000,000-byte bound. Reading stops and
the response closes as soon as an undeclared stream would cross the limit.

One retry is permitted by default for mapped connect/read/write/pool timeouts and other HTTPX
transport failures. Safety denials, scope denials, invalid URLs, redirect failures, size
failures, and HTTP status responses are not retried. Retry sleep is short, bounded, and
injectable; server `Retry-After` is not implemented.

## Stable fetch failure codes

- Boundary and scope: `unsupported_scheme`, `credentials_not_allowed`, `invalid_hostname`,
  `ip_literal_not_allowed`, `unsafe_hostname`, `port_not_allowed`, `scope_denied`.
- DNS and addresses: `dns_resolution_failed`, `dns_answer_limit_exceeded`,
  `unsafe_resolved_address`, `mixed_safe_unsafe_dns_answers`.
- Time and transport: `connect_timeout`, `read_timeout`, `write_timeout`, `pool_timeout`,
  `request_deadline_exceeded`, `transport_error`.
- Redirects: `redirect_missing_location`, `redirect_invalid_location`, `redirect_loop`,
  `redirect_limit_exceeded`, `redirect_scope_denied`, `redirect_unsafe_destination`.
- Response bounds: `response_too_large`, `response_headers_too_large`,
  `invalid_content_length`.

Public explanations are controlled summaries. The internal exception type may be retained for
diagnostics, but raw low-level exception messages are not the user-facing contract.

## Remaining network limitation

DNS is resolved and validated immediately before each first request, retry, and redirect. No
safety result is cached across fetches. HTTPX then performs its own connection resolution, and
this layer cannot confirm or pin the connected peer address cleanly. DNS rebinding therefore
remains possible between validation and connection. Production deployment must add egress
firewall restrictions; future transport work may pin validated answers while retaining correct
Host and TLS behavior.

## HTML parse policy

HTML extraction consumes a completed bounded `FetchResult`; it never performs DNS, HTTP, script
execution, or browser automation. Fetch and parse evidence remain separate and immutable.
Failed fetches, truncated bodies, missing or empty bodies, and non-2xx responses are skipped with
typed reasons rather than treated as successful page metadata.

### Content type and encoding

Declared media types are compared case-insensitively without parameters. `text/html` and
`application/xhtml+xml` are parsed. JSON, non-XHTML XML, PDF, image, CSS, JavaScript, and plain
text are skipped. A missing or `application/octet-stream` media type may be inferred as HTML
only when the first 1,024 bytes start with a structural HTML signature.

Decoding precedence is:

1. a valid HTTP `charset` parameter;
2. UTF-8, UTF-16, or UTF-32 byte-order mark;
3. `<meta charset>` in the first 4,096 bytes;
4. `<meta http-equiv="content-type">` in the same bounded prefix; then
5. Windows-1252 fallback.

Invalid declarations remain warnings and allow the next source to be considered. Strict
decoding is attempted first; replacement characters and their warning are recorded when bytes
cannot be decoded strictly. Beautiful Soup with lxml recovers malformed real-world HTML, and
observable recovery is reported.

### Metadata and base URLs

Title and description text is entity-decoded, descendant text is combined where applicable,
whitespace runs collapse to one space, and edges are trimmed. Every observation is retained.
The first observation is the deterministic selected text. Review warnings use initial title
thresholds of 15–60 characters and description thresholds of 70–160 characters. These are not
hard SEO rules and never decide sitemap eligibility.

Canonical `rel` is a case-insensitive token. Every raw href and normalization result is retained.
Relative canonicals resolve through the effective base; a canonical is selected only when all
valid candidates normalize to one target. Canonical values are never fetched or treated as
authoritative by the parser.

The first valid `<base href>` is effective. Empty, unsupported, credential-bearing, and malformed
values remain warning evidence; a later valid value may become effective after earlier invalid
values. All base elements remain in document order. Base resolution never changes the fetched
document identity and never initiates a request.

### Meta robots and links

Crawler-named meta records such as `robots` and `googlebot` remain separate. Directive names are
case-normalized; raw content and tokens remain available. Known directives include `index`,
`noindex`, `follow`, `nofollow`, `none`, `noarchive`, `nosnippet`, `noimageindex`, `notranslate`,
`max-snippet`, `max-image-preview`, `max-video-preview`, and `unavailable_after`. Unknown,
invalid, empty, and conflicting tokens are warnings only. X-Robots-Tag and final indexability
precedence are deferred.

Only navigable `<a href>` and `<area href>` observations are extracted. Resource attributes on
images, scripts, stylesheets, media, and CSS are excluded. HTTP(S), relative, root-relative,
parent-relative, query-only, and fragment-only references use the accepted normalizer. Other
schemes remain raw evidence and are not HTTP destinations; `javascript:` receives an explicit
warning and is never executed. Anchor text combines descendant text, decodes entities, and
normalizes whitespace without borrowing nested image alt text. Repeated links remain in document
order and are not queued or globally deduplicated. When supplied, an existing scope policy adds
scope evidence but does not authorize or perform a request.

### Stable HTML warning codes

- Document and decoding: `non_html_content`, `missing_body`, `empty_body`,
  `http_error_response`, `response_truncated`, `media_type_inferred`, `invalid_charset`,
  `encoding_declaration_ignored`, `decode_replacement_used`, `parser_recovery_used`.
- Title: `missing_title`, `empty_title`, `multiple_titles`, `conflicting_titles`, `short_title`,
  `long_title`.
- Description: `missing_meta_description`, `empty_meta_description`,
  `multiple_meta_descriptions`, `conflicting_meta_descriptions`, `short_meta_description`,
  `long_meta_description`.
- Canonical: `missing_canonical`, `empty_canonical`, `multiple_canonicals`,
  `conflicting_canonicals`, `invalid_canonical`, `cross_host_canonical`,
  `canonical_url_differs`, `canonical_origin_differs`.
- Robots: `empty_meta_robots`, `conflicting_meta_robots`,
  `unknown_meta_robots_directive`, `invalid_meta_robots_directive`.
- Base: `multiple_base_elements`, `empty_base_href`, `invalid_base_href`,
  `cross_host_base_href`, `base_origin_differs`.
- Links: `empty_link_href`, `invalid_link_href`, `javascript_link`,
  `unsupported_link_scheme`.

Every warning has a severity and controlled explanation plus an occurrence index and bounded,
query-free observed value where practical. Warnings do not contain response bodies, headers,
credentials, or full sensitive query strings.

## Single-site frontier and admission policy

The crawl key is the accepted normalized absolute URL. Fragments therefore collapse, while path
case, query order, repeated keys, blank query values, and trailing-slash variants remain distinct.
The frontier retains first discovery evidence, bounded referring URLs, first and best-known depth,
and stable discovery order. Pending work is ordered by best depth and then discovery order. A
better-depth rediscovery updates a pending item; active or completed URLs are never requeued.

Only links already extracted by the HTML boundary are considered. Empty, invalid, unsupported,
JavaScript, fragment-only, and same-document references are rejected with stable evidence. An
HTTP(S) candidate must pass the accepted crawl-scope policy, depth bound, optional query policy,
and explicit exclusion rules. Current exclusion rules support exact paths, path prefixes, and
query-parameter names. They are deterministic URL-string policies, not robots or indexability
decisions.

`rel=nofollow` is retained on discovery evidence but is admitted under the current policy. A
canonical is metadata evidence and never substitutes for a discovered URL. When a fetched URL
redirects to a normalized final URL already pending, the redundant pending entry is skipped while
both the redirect and URL records remain available.

## Orchestration resources and lifecycle

One breadth-first depth batch is active at a time. Fetches inside the batch are asynchronous and
bounded by the per-crawl concurrency setting; evidence is processed in stable frontier order.
Request starts are paced per origin. Pacing does not replace the safe fetcher's own connection,
timeout, response-size, DNS, redirect, and network-concurrency controls.

Validated crawl requests have limits for unique normalized URLs, depth, total elapsed duration,
total accepted response bytes, concurrent fetches, pending queue size, and minimum per-origin
delay. Server hard maxima cannot be overridden by ordinary request values. A per-response fetch
size failure remains separate from the aggregate crawl-byte limit. Limit events record the kind,
stable code, configured bound, observed value, and elapsed time.

Cancellation is cooperative and independently injectable. Once observed, no new URL is fetched;
already returned evidence is retained and pending records are marked skipped. Terminal precedence
is: an orchestration invariant or worker failure produces `failed`; otherwise cancellation produces
`cancelled`; otherwise an enforced resource stop produces `limit_reached`; otherwise recorded
recoverable errors produce `completed_with_errors`; otherwise the result is `completed`.

Counters distinguish unique URLs, queued and fetched URLs, fetch outcomes, parsed and skipped
responses, scope/depth/rule exclusions, duplicates, redirects, observed links, and admitted or
rejected links. Progress snapshots are immutable, best-effort views; observer failures become
controlled errors and cannot drive or abort worker execution.

Stable crawl-level error codes are `invalid_crawl_request`, `seed_scope_denied`,
`robots_unavailable`,
`url_limit_reached`, `duration_limit_reached`, `byte_limit_reached`, `queue_limit_reached`,
`cancelled`, `frontier_invariant_violation`, `worker_failure`, `progress_observer_failure`, and
`unexpected_orchestration_error`. Stable link-admission reasons are `admitted`,
`updated_better_depth`, `duplicate_url`, `invalid_url`, `unsupported_scheme`, `empty_href`,
`fragment_only`, `same_document`, `scope_denied`, `depth_exceeded`, `excluded_by_rule`,
`query_url_disallowed`, `url_limit_reached`, `queue_limit_reached`, `crawl_stopping`,
`redirect_final_already_seen`, `cancelled`, `robots_denied`, and `robots_unavailable`.

## Robots retrieval and response policy

For each frontier origin, the robots URL is the normalized
`scheme://host[:effective-non-default-port]/robots.txt`. Document paths, queries, bases, and
canonicals never affect that URL. Retrieval uses the accepted safe GET boundary, including its
scope, DNS, address, port, redirect, timeout, proxy, concurrency, and hard streaming limits.

Status behavior is explicit:

- 200: parse an accepted plain-text body.
- 204: no policy; allow.
- 400 and 404: policy not found; allow with evidence.
- 401 and 403: conservatively deny the origin.
- 429 and 500–599: temporarily unavailable; deny ordinary page requests for this crawl.
- transport and timeout failures: temporarily unavailable and denied.
- oversized, unsupported status, or invalid content type: invalid evidence and denied.

Missing Content-Type, `text/plain`, and `application/octet-stream` are accepted. Other media types,
including HTML, are not parsed. Invalid UTF-8 is replacement-decoded with a warning. The default
robots-specific body limit is 1,000,000 bytes with a 5,000,000-byte hard maximum. This additional
limit is checked on the bounded fetch evidence; the accepted fetcher may have read up to its own
hard stream limit first.

Every result is cached per normalized origin for one crawl. Concurrent requests share one in-flight
retrieval. Successful, missing, forbidden, temporary-failure, invalid, and oversized results are
cached. No decision is cached across crawls. Accepted robots bytes count toward total crawl bytes
and also appear in `robots_bytes`.

Robots permission is a required injected orchestrator dependency. Production composition must
explicitly provide `RobotsTxtService`; omission is a construction error and there is no runtime
allow-all default. Tests unrelated to robots may explicitly provide a named allow-all service
defined only in test code.

## Robots parsing and matching

Parsing is line-oriented and bounded to 8,192 characters per line and 10,000 lines by default.
UTF-8 BOM, blank lines, comments, inline comments, and case-insensitive field names are handled.
Malformed lines and unknown directives remain warning evidence. User-agent, Allow, Disallow,
Crawl-delay, and Sitemap are recognized; Sitemap values are never fetched or placed in the
frontier.

Consecutive User-agent fields before group directives belong to one group. A User-agent field after
group directives starts a new group. Later groups are never merged merely because they repeat an
agent value. Matching uses the case-insensitive `MusimackSEOToolkit` product token. The earliest
group with the longest matching non-wildcard agent token wins; `*` has specificity zero and is the
fallback. When no group matches, crawling is allowed with `robots_no_matching_group` evidence.

Rules match the normalized, case-sensitive path plus `?query` when present. Query ordering and
percent-encoding remain exactly as normalized. `*` matches zero or more characters and a final `$`
anchors the target end. The matching specificity is the rule length excluding wildcards and the
terminal anchor. The longest match wins; Allow wins equal-specificity ties; earlier source order is
the final tie-breaker. Empty Disallow has no effect. `/` denies every path.

Crawl-delay accepts finite non-negative numbers and records invalid or conflicting values. It is
evidence only: configured per-origin pacing remains authoritative, and robots can never reduce the
server delay. Every valid absolute HTTP(S) Sitemap directive is normalized and retained, while
relative and unsupported values receive warnings. Sitemap URLs do not change scope or frontier
admission.

Stable robots warning codes are `robots_not_found`, `robots_access_denied`,
`robots_temporarily_unavailable`, `robots_fetch_failed`, `robots_response_too_large`,
`robots_invalid_content_type`, `robots_decode_warning`, `robots_malformed_line`,
`robots_line_too_long`, `robots_line_limit_exceeded`, `robots_unknown_directive`,
`robots_invalid_user_agent`, `robots_invalid_rule`, `robots_invalid_crawl_delay`,
`robots_conflicting_crawl_delay`, `robots_invalid_sitemap`, and `robots_no_matching_group`.

Stable permission reasons are `allowed_by_allow_rule`, `denied_by_disallow_rule`,
`allowed_no_matching_rule`, `allowed_no_robots_file`, `denied_robots_access_forbidden`,
`denied_robots_temporarily_unavailable`, `denied_invalid_robots_response`,
`allowed_no_matching_group`, and the explicit injected-test-policy reason `allowed_test_policy`.

## X-Robots-Tag and combined indexability evidence

Repeated X-Robots-Tag values remain ordered. Header lookup is case-insensitive in the accepted
fetcher. Generic values and crawler-prefixed values such as `googlebot: noindex, nofollow` remain
separate records. Known simple and parameterized directives match the existing meta robots set;
unknown, empty, and invalid directives remain warnings.

The combined view preserves all meta and header records. It detects index/noindex,
follow/nofollow, parameter-value, meta/header, and generic/crawler-specific differences. It never
collapses evidence into an `indexable` boolean and never decides sitemap eligibility. Noindex,
nofollow, and canonical evidence still do not suppress frontier discovery.

Stable indexability warning codes are `empty_x_robots_tag`, `invalid_x_robots_tag`,
`unknown_x_robots_directive`, `conflicting_x_robots_directives`,
`meta_header_index_conflict`, `meta_header_follow_conflict`, `parameter_value_conflict`, and
`crawler_specific_directive_difference`.

## Sitemap eligibility recommendation policy

Sitemap eligibility is a pure evidence decision separate from crawl permission, page-level
indexability observations, and metadata quality. The internal engine produces `include`, `exclude`,
`review`, or `indeterminate`. State precedence is:

1. hard exclusion
2. indeterminate evidence
3. human review
4. include

An included URL must normalize successfully, remain in approved scope and origin policy, have an
allowed robots permission, complete a successful fetch, represent its own final URL identity,
return final status 200, and be confirmed as `text/html` or `application/xhtml+xml`. Structurally
sniffed HTML from a missing Content-Type or `application/octet-stream` is eligible by default.
Contradictory declared non-HTML and parsed-HTML evidence is indeterminate. PDF, JSON, image, CSS,
JavaScript, plain text, and other confirmed non-HTML media are excluded.

Robots denial is a crawl-permission exclusion and never implies noindex. Generic meta robots or
generic X-Robots-Tag `noindex` excludes. A generic `index` does not cancel `noindex`; the conflict is
retained as warning evidence. Crawler-specific noindex is retained separately and does not exclude
by default. Nofollow, follow, noarchive, nosnippet, noimageindex, notranslate, and parameterized
directives do not affect default eligibility.

A missing canonical permits inclusion with a warning. One or more valid canonicals that all
normalize to the final page URL permit inclusion. A deterministic canonical to any different path,
query, trailing-slash form, host, scheme, or port excludes the page. Cross-host and cross-origin
differences add specific evidence codes. Multiple disagreeing valid canonicals require review. One
or more invalid canonicals with no valid selection require review; invalid evidence plus a valid
self-canonical includes with a warning; invalid evidence plus a selected canonical elsewhere
excludes.

Every requested URL that redirects to a different normalized final URL is excluded as a redirect
source, including temporary redirects. The final target is evaluated only through its own crawl
record. If absent, no target recommendation row is created; each excluded source retains
`redirect_target_not_independently_evaluated` warning evidence. Multiple redirect sources therefore
cannot synthesize duplicate target candidates. Redirect chains remain evidence.

Exact-path, path-prefix, and query-parameter exclusions are reapplied from the immutable crawl
configuration, and every matching configured rule is retained. The projection emits at most one
recommendation per normalized identity in first crawl-record order and counts suppressed duplicate
records.

Path-prefix rules are case-sensitive and segment-aware. `/blog` matches `/blog`, `/blog/`, and
descendants beginning `/blog/`, but not `/blogging`, `/blogs`, or `/blog-old`. A configured trailing
slash is deterministically trimmed to the same segment boundary. Root prefix `/` matches every
absolute path. Empty prefixes are rejected by the crawl exclusion contract, and query strings do
not affect path matching. Exact-path and query-parameter semantics are unchanged.

Missing, empty, short, long, multiple, and conflicting title or meta-description observations are
metadata warnings only. They do not cause review or exclusion. Parser recovery, conflicting valid
canonicals, and invalid canonical evidence without a valid selection require review under the
default policy. Missing robots, parse, or combined indexability evidence makes an otherwise
qualifying result indeterminate.

Ordered rule identifiers evaluate URL/scope, robots permission, fetch outcome, redirect source,
final status, HTML content, generic indexability, configured exclusions, canonical target and
quality, then evidence quality. All relevant reasons remain; primary reason follows that order
within the winning state precedence.

Stable recommendation reasons are `eligible_html_page`, `invalid_url`, `unsupported_scheme`,
`outside_scope`, `disallowed_port`, `configured_url_exclusion`, `not_fetched`, `fetch_failed`,
`redirect_failed`, `redirect_source`, `non_200_status`, `missing_http_status`,
`response_too_large`, `non_html_content`, `robots_denied`, `generic_noindex`,
`conflicting_generic_indexability`, `canonical_points_elsewhere`, `cross_host_canonical`,
`cross_origin_canonical`, `conflicting_canonicals`, `invalid_canonical`, `missing_canonical`,
`missing_required_evidence`, `ambiguous_content_type`,
`redirect_target_not_independently_evaluated`, `severe_parser_recovery`, and
`crawler_specific_noindex`.

Projection counters cover each state, primary reason, metadata warning, duplicate suppression,
redirect sources, canonical exclusions, generic-noindex exclusions, robots denials, non-HTML
responses, and non-200 or missing statuses. The immutable configuration snapshot retains all five
policy booleans and rule-set identifier `sitemap-eligibility-v1`.

`SITEMAP_RULE_SET_VERSION` is the single authoritative code constant for that identifier.
Determinacy values are `determinate`, `blocked_missing_evidence`, and
`blocked_conflicting_evidence`. Include, exclude, and review are determinate because the engine has
enough coherent evidence to reach those states. Indeterminate results use the applicable blocked
value to distinguish absent evidence from contradictory evidence.

Default policy values are: missing canonical does not require review; invalid canonical without a
valid selection does require review; ambiguous structurally sniffed HTML does not require review;
crawler-specific noindex does not require review; severe parser recovery does require review; and
the rule-set identifier is `sitemap-eligibility-v1`. These values are internal typed configuration,
not request-controlled API input.

## Sitemap XML serialization policy

The `sitemap-xml-v1` serializer consumes the completed immutable recommendation projection. Only
final `include` recommendations serialize; `exclude`, `review`, and `indeterminate` are counted as
skipped states rather than XML errors. Recommendation order is authoritative. The serializer does
not re-evaluate crawl permission, indexability, canonical evidence, redirects, metadata quality,
or scope, and it never mutates a recommendation.

Exact duplicate normalized URL strings are suppressed while preserving the first occurrence.
Trailing-slash, path-case, and query-order variants remain distinct. Each accepted location is
limited to 2,048 characters before XML escaping and must remain a valid, already normalized HTTP
or HTTPS absolute URL. Impossible included values receive stable typed rejections; they are never
truncated and do not prevent other valid entries from being emitted.

XML is UTF-8 with declaration `<?xml version="1.0" encoding="UTF-8"?>`, the sitemap 0.9 namespace,
two-space structural indentation, LF newlines, and a final newline. Standard-library escaping
protects XML text without changing the URL identity. URL documents contain only `<url><loc>`.
There is no `lastmod`, `changefreq`, `priority`, compression, extension namespace, or inferred
metadata. Zero eligible URLs produce one valid empty URL-set document.

URL documents default to at most 50,000 entries and 52,428,800 uncompressed UTF-8 bytes. A complete
candidate document, including declaration, wrapper, indentation, and escaped text, is measured
before an entry is accepted. Splits occur before either limit and retain global order. An entry
that cannot fit an otherwise empty document becomes a typed rejection.

Multiple URL documents use deterministic one-based logical names. A sitemap index is generated
only when an explicit normalized HTTP(S) `sitemap_base_url` supplies their public locations. If the
base is absent, the URL documents remain available and a typed warning blocks the index; no host is
guessed. Indexes have the same 50,000-reference and 52,428,800-byte defaults. Capacity excess is
reported without omitting URL documents or creating recursive indexes.

Generation remains in process memory. This policy does not authorize file writing, publication,
download routes, persistence, or sitemap submission.

## Local sitemap publication policy

Publication consumes accepted XML bundle bytes unchanged and therefore cannot alter eligibility,
ordering, XML content, split points, or index blockage. The orchestration service preserves XML
warnings and rejections alongside publication planning and execution results.

An explicit absolute local output root is required. Relative roots, `.git` paths, regular files,
and roots containing symbolic-link or Windows junction components are rejected. A missing root is
blocked unless `create_output_directory` is explicitly enabled; dry run reports that intended
creation without performing it. Logical package names must be single safe filenames. Empty names,
path separators, traversal, POSIX absolute paths, Windows drive-qualified paths, UNC paths, null
bytes, reserved device names, duplicate names, and case-normalized collisions are rejected.
Targets that are directories or link-like paths are blocked.

`fail_if_exists` is the default. Planning reports every existing package target in deterministic
order and execution writes nothing. `overwrite` permits atomic replacement of planned files only;
unrelated files remain untouched. No-clobber finalization creates a hard link from the secure
same-directory temporary file to the absent final name. A target appearing after preflight is never
replaced. Unsupported hard links, hard-link permission denial, and other finalization failures are
reported as `no_clobber_finalization_unsupported`,
`no_clobber_finalization_permission_denied`, and `no_clobber_finalization_failed`; all fail safely
without an overwrite fallback. Temporary cleanup failure remains `cleanup_failed`.
`replace_only_if_changed` is deferred.

Dry run uses the same manifest and publication plan as real execution. It validates roots,
filenames, containment, target types, and conflicts; returns intended target paths, exact bytes,
hashes, counts, and manifest content; and creates no directory, temporary file, or final file.

Real execution creates a secure unpredictable temporary file in the final target directory, writes
the exact immutable bytes, flushes and `fsync`s them, then performs a same-filesystem atomic final
operation. Each published file is read back and verified against its planned byte count and
SHA-256. Temporary files are cleaned on success and controlled failure. Atomicity is guaranteed per
file, not for the package as a whole. A later failure yields `partially_failed` evidence and leaves
earlier completed files in place; it never deletes user files as rollback.

Symbolic-link and junction roots, ancestors, and targets are rejected using the link kinds exposed
by the standard library. Capability-dependent symlink tests catch only recognized errors from the
minimal link-creation probe; publication errors cannot become skips. Windows junction tests use
temporary local directories and run independently of symlink privilege. Other reparse-point kinds
not identified as a symlink or junction remain outside the claimed application-level guarantee.

The `sitemap-publication-manifest-v1` JSON manifest is UTF-8, sorted-key, two-space-indented,
LF-terminated, and deterministic. It records the XML and recommendation versions, counts, index
presence or blockage, conflict policy, and ordered XML file media types, entry counts, byte counts,
and lowercase SHA-256 hashes. It contains no timestamps, machine identity, username, absolute local
path, or its own recursive hash. The publication result carries the manifest hash separately.

This local publication policy does not itself authorize an API, download delivery, remote upload,
sitemap submission, persistence, scheduling, or export history. The separately composed Phase 16
artifact boundary may register and serve verified local outputs internally.

## Crawl-run orchestration policy

An internal run request composes accepted crawl evidence; it does not alter normalization, scope,
robots permission, fetch safety, redirect, byte, concurrency, or frontier semantics. Every v1 run
explicitly requests `crawl`. Recommendation, XML, planning, and publication stages must list their
ordered prerequisites. Scope approval and network-safety approval remain separate inside the
accepted crawler.

Cancellation is cooperative. A request present before start cancels crawl and blocks its dependent
stages. Cancellation returned by the crawler preserves its partial `CrawlResult`. Cancellation
after crawl cancels the next requested dependent stage and blocks later ones. It is checked again
before publication mutation. The accepted synchronous publication executor completes its own
atomic file operations and currently exposes no safe checkpoint between package files, so v1 does
not claim mid-package cancellation. Summary serialization may still run after cancellation and
records the blocked stages.

The run service adapts the accepted asynchronous crawl observer for each execution. Every immutable
callback snapshot is preserved in delivery order as a run event, including discovered, queued,
fetched, parsed, byte, queue, active-fetch, depth, and recent-error evidence actually available from
the crawler. Exact duplicate callbacks are preserved. If final crawl evidence advances beyond the
last callback, one reconciliation event appears before crawl completion; otherwise no duplicate
final event is added. Sink failure never enters crawler error evidence. Cancellation observation
follows the last translated snapshot, while cancellation arriving after completed crawl evidence is
handled by the next stage rather than retroactively changing crawl state.

Portable summaries contain controlled stage states, counts, versions, warnings, and failures. They
exclude wall-clock timestamps, absolute paths, environment data, raw stack traces, response bodies,
and raw exception messages. They retain authoritative final counters, not the unbounded progress
event history. Output paths never participate in run identity. Summary writing uses a
separate explicitly configured absolute root, two fixed filenames, link/junction rejection,
dry-run, and the accepted no-clobber or overwrite atomic writer. Sitemap publication behavior is
unchanged.

## Current limitations and deferred controls

The internal orchestrator can traverse one approved site in memory through the accepted fetch and
parse boundaries. It is not exposed through the API. The following remain deferred:

- connected-peer verification and DNS-answer pinning
- deployment-level egress enforcement
- duplicate-content fingerprinting and final search-engine-specific directive precedence
- enforcement of robots Crawl-delay values
- a pre-redirect robots callback inside ordinary page redirect sequences; the accepted fetcher
  still revalidates scope and network safety at every redirect target
- persistent job ownership, durable progress streaming, restart recovery, and CSV
- manual include/exclude overrides and approval workflows

No caller should treat scope `decision.allowed` as sufficient permission to connect. The safe
fetcher combines it with the current DNS, address, port, redirect, time, and resource controls;
future production authorization must also include infrastructure egress controls.

## Job coordination does not change crawl policy

The internal `crawl-job-registry-v1` manager queues and invokes accepted run requests without
altering their normalized seed, scope, safety, robots, fetch, frontier, recommendation, XML, or
publication configuration. Queue order and attempt number do not participate in deterministic run
identity. Duplicate detection uses that complete accepted run ID, never the seed URL alone.

Cancellation remains cooperative. Queued cancellation prevents execution; a starting or running
job receives the exact registry-owned token accepted by the run service. No task termination
changes partial-result or stage semantics. Retention stores immutable results or configured subsets
without rewriting evidence.

Job state is process-local. There is no restart durability, persistent queue, cross-process lock,
distributed execution, or public admission route. Progress and terminal history are bounded, so
older evidence may be intentionally evicted. These operational policies do not grant network
authorization or relax existing scope and destination-safety decisions.

## Application profiles and bounded projections

Application profiles select values already accepted by crawl, fetch, recommendation, XML,
publication, and summary contracts. They do not redefine normalization, scope, robots permission,
network safety, frontier ordering, recommendation precedence, XML serialization, or filesystem
publication. Application maxima are additional admission gates; lower layers remain authoritative.
Values above a gate are rejected with supplied-value evidence and are never silently clamped.

Preparation and validation make no network, DNS, registry, or filesystem mutation. Operational
preflight may read current registry state and inspect existing output paths, but it allocates no job
attempt, reserves no active or queue capacity, and creates no directory or temporary file. Its
likely-start, likely-queue, duplicate, conflict, and readiness findings can become stale.
Submission performs validation again and is the authoritative outcome.

Default application status and result projections are deliberately bounded. They report counts,
states, stable error and warning codes, logical filenames, hashes, and version identifiers. They do
not expose URL records, recommendation rows, progress histories, raw HTML, response bodies, XML
bytes, summary bytes, stack traces, cancellation tokens, locks, tasks, or absolute machine paths.
Detailed export and record delivery require a separately authorized boundary.

## Internal API adaptation does not change crawl policy

The private internal API is a transport adapter over accepted application projections. Its named
request fields and Pydantic validation do not redefine URL normalization, scope, network safety,
robots permission, frontier ordering, crawl limits, recommendation precedence, XML generation, or
publication safety. Application validation and preparation remain side-effect free. Advisory
preflight still allocates no attempt, reserves no queue capacity, creates no output path, and may
be stale before authoritative submission.

API status, progress, registry, and result responses remain bounded. Progress is latest-only unless
a bounded retained-history limit is explicitly requested; no SSE or WebSocket stream exists.
Registry responses expose counts rather than job lists. Result responses omit detailed URL rows,
recommendation rows, HTML, response bodies, XML, manifests, summaries, filesystem paths, and
runtime objects. Three optional artifact routes form a separately authorized, authenticated,
bounded retrieval boundary; they do not broaden these job/result projections.

The default application remains health-only. Explicitly mounted routes fail closed without an
injected verifier, but that gate is not complete authentication and does not authorize public
exposure. HTTP adaptation never grants crawl or network permission; every submitted run continues
through the accepted scope, destination-safety, robots, limit, job, and publication contracts.

## Deployment security does not change crawl policy

Internal bearer authentication is evaluated before any application-service operation. Trusted
network and proxy rules authorize the client-to-API boundary only; they do not authorize a crawl
destination, modify URL scope, bypass DNS/address safety, or alter redirect and robots decisions.
The direct peer is authoritative unless explicitly trusted as a proxy. A trusted proxy may supply
one bounded `X-Forwarded-For` chain; malformed evidence fails closed for authenticated operations.

Correlation IDs and access logs are operational evidence only. They do not participate in run,
job, URL, recommendation, XML, publication, or sitemap identity. Logs omit URL query strings,
request bodies, credentials, publication roots, and summary roots. Security configuration never
changes metadata warnings or sitemap recommendation precedence.

The production application still depends on deployment controls for TLS, reverse-proxy isolation,
actual streamed request-body limits beyond the accepted declared `Content-Length` check, and
network ingress/egress policy. The internal access gate and shared bearer credential are not a
public authorization system.

## Persistence does not change crawl policy

Optional SQLite persistence records bounded accepted evidence after the same normalization, scope,
destination safety, robots, frontier, indexability, recommendation, XML, and publication decisions.
It does not authorize a request, broaden scope, alter normalized URL identity, recompute a
recommendation, or make retained rows authoritative over current domain contracts.

Stored URLs omit query strings for safe operational evidence. The database does not retain raw
HTML, response bodies, full crawl records, XML bytes, manifest bytes, summary bytes, credentials,
or arbitrary filesystem roots. Configuration snapshots are canonical, path-free, immutable, and
deduplicated by SHA-256. Progress, warnings, failures, summaries, artifacts, and terminal jobs are
bounded by deterministic sequence-based retention.

After restart, no crawl automatically resumes. Accepted, queued, starting, running, and cancelling
records are mapped to failed or partially completed with `process_restart_interrupted`; completed
stage and artifact metadata remains. Recovered attempts prevent duplicate job IDs, while queued
capacity rejection still allocates no attempt. Metadata-only bootstrap restores no task,
cancellation token, response body, XML payload, or full `CrawlRunResult`.

Explicit cleanup removes or marks only database metadata according to policy. It never deletes
filesystem sitemap or summary artifacts, and retention never changes sitemap recommendation or XML
generation outcomes.

## Durable page evidence does not change crawl policy

The optional Phase 20A terminal observer persists the accepted `UrlCrawlRecord` projection without
re-fetching, DNS resolution, HTML reparsing, or robots re-evaluation. Existing normalized URL,
fetch, redirect, parsed metadata, robots permission, and indexability evidence remains
authoritative. Missing, empty, unavailable, partial, failed, non-HTML, and truncated states stay
distinct.

Persistence ordering is discovery sequence ascending with normalized URL identity as tie-breaker.
Page, redirect, and warning limits are enforced before storage. Raw HTML, response bodies, complete
headers, and binaries are excluded. The persisted evidence is an enabling input for future Phase 20
audits; it does not classify issues, severity, duplicates, eligibility, or metadata quality.

## Durable execution does not change crawl policy

Durable scheduling changes where queued work is coordinated, not how URLs are normalized, scoped,
fetched, checked against robots, interpreted for indexability, or recommended for a sitemap. A job
must still pass every accepted crawl and network-safety boundary. Retry classification cannot turn
a robots denial, noindex directive, canonical exclusion, validation failure, or explicit
cancellation into an eligible sitemap URL.

Cancellation remains cooperative. The durable worker persists the request, checks it before
execution and during heartbeats, and forwards it to the accepted cancellation token. It does not
use unsafe task termination as the normal mechanism. After process loss, stale recovery may create
a new execution attempt under the same job ID, but it never resumes a partially consumed frontier,
reuses an old lease, or changes URL/run identity. Completed stage and artifact metadata can remain
as evidence without becoming resumable crawler state.

Lease expiry and retries are execution-coordination evidence only. They do not modify crawl limits,
recommendation precedence, metadata warnings, XML rules, or publication behavior. Durable mode is
single-machine SQLite coordination; it provides neither distributed fencing nor authorization for
public worker control.

## Artifact storage does not change crawl or eligibility policy

Artifact registration consumes only successfully generated local outputs. Missing, corrupt,
expired, retained, or deleted artifact state cannot change URL normalization, scope, fetching,
robots permission, indexability, recommendation, XML serialization, or publication success.
Registration failures are artifact-management evidence and do not retroactively exclude URLs or
delete successfully published files. Retrieval is authenticated internal delivery only and never
authorizes a crawl, remote publication, sitemap submission, or public sharing.

## History does not change crawl policy

Durable history is a read-only projection of already accepted persistence evidence. Filtering,
pagination, retention state, interruption state, or artifact availability cannot authorize a URL,
change normalized identity, broaden scope, bypass DNS/SSRF controls, alter robots or indexability
decisions, modify recommendation precedence, or resume a frontier. A historical warning or failure
is safe evidence, not permission to refetch. History API requests perform no public HTTP or DNS.

## Authentication does not change crawl authority

Users, roles, sessions, login throttling, and authentication audit records control admission to
private application operations only. They do not alter URL normalization, scope, DNS/SSRF checks,
robots evaluation, fetch limits, indexability, recommendation precedence, sitemap serialization,
or publication safety. A `jobs.submit` permission admits a request to the already accepted
validation and preflight pipeline; it cannot bypass that pipeline. Authentication and user
administration perform no public HTTP, DNS, crawl, publication, or artifact filesystem operation.

## Frontend does not change crawl authority

The private frontend is an authenticated presentation adapter. Its route guards, navigation, crawl
form, polling, and review pages cannot authorize a URL, broaden scope, bypass DNS/SSRF controls, or
change robots or indexability evidence. Submission always passes the backend validation and
preflight pipeline. Polling reads bounded status evidence and stops at terminal state. Frontend
tests mock every API call and perform no public HTTP or DNS. History, recommendation filters, and
artifact downloads do not trigger a crawl or change sitemap eligibility.
