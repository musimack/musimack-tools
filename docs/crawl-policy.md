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

## Current limitations and deferred controls

The current fetcher handles one starting URL and bounded redirects only. The following remain
deferred:

- connected-peer verification and DNS-answer pinning
- deployment-level egress enforcement
- `robots.txt`, meta robots, and X-Robots-Tag handling
- crawl-frontier rate scheduling beyond request concurrency bounds
- HTML and metadata extraction
- canonical, duplicate, indexability, and sitemap decisions
- background jobs, persistence, progress, cancellation, XML, and CSV

No caller should treat scope `decision.allowed` as sufficient permission to connect. The safe
fetcher combines it with the current DNS, address, port, redirect, time, and resource controls;
future production authorization must also include infrastructure egress controls.
