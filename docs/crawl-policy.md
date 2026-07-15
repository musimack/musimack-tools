# Current Crawl Policy

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
`url_limit_reached`, `duration_limit_reached`, `byte_limit_reached`, `queue_limit_reached`,
`cancelled`, `frontier_invariant_violation`, `worker_failure`, `progress_observer_failure`, and
`unexpected_orchestration_error`. Stable link-admission reasons are `admitted`,
`updated_better_depth`, `duplicate_url`, `invalid_url`, `unsupported_scheme`, `empty_href`,
`fragment_only`, `same_document`, `scope_denied`, `depth_exceeded`, `excluded_by_rule`,
`query_url_disallowed`, `url_limit_reached`, `queue_limit_reached`, `crawl_stopping`,
`redirect_final_already_seen`, and `cancelled`.

## Current limitations and deferred controls

The internal orchestrator can traverse one approved site in memory through the accepted fetch and
parse boundaries. It is not exposed through the API. The following remain deferred:

- connected-peer verification and DNS-answer pinning
- deployment-level egress enforcement
- `robots.txt`, X-Robots-Tag interpretation, and final robots precedence
- canonical, duplicate, indexability, and sitemap decisions
- robots-aware admission and crawl-delay interpretation
- background job ownership, persistence, durable progress streaming, restart recovery, XML, and CSV

No caller should treat scope `decision.allowed` as sufficient permission to connect. The safe
fetcher combines it with the current DNS, address, port, redirect, time, and resource controls;
future production authorization must also include infrastructure egress controls.
