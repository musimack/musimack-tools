# ADR 0026: Request correlation, access logging, and security headers

## Status

Accepted for `seo-toolkit-security-v1`.

## Decision

Accept bounded ASCII `X-Request-ID` values and replace missing or invalid values with a securely
random `req-<32 lowercase hexadecimal characters>` identifier. Return it in headers and API
envelopes. Emit keyed access events containing bounded route, status, duration, correlation,
caller, client, validated job, and version fields while omitting query strings, headers, bodies,
credentials, and filesystem roots.

Apply `nosniff`, no-store/no-cache, no-referrer, frame denial, and a restrictive content security
policy when enabled. Do not add HSTS because TLS termination is not owned here. Internal CORS is
disabled by default and uses exact origins without credentials or wildcard reflection.

## Consequences

Correlation is diagnostic evidence, never identity or authorization. Logging is process-local and
uses the existing Python logging stack. Central aggregation, retention policy, TLS, and external
audit infrastructure remain future deployment concerns.
