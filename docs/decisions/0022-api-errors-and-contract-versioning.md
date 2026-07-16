# ADR 0022: Internal API versioning, envelopes, and bounded errors

## Status

Accepted for implementation.

## Context

HTTP consumers need deterministic schemas and status mappings without receiving lower-layer
objects, submitted values, machine paths, or raw exception evidence.

## Decision

Version the adapter as `seo-toolkit-internal-api-v1`. Every success and error envelope includes
that identifier. Success envelopes contain a null request ID, typed bounded data, and bounded
warnings. Error envelopes contain a stable code, safe message, and bounded details with optional
field and source codes.

Normalize Pydantic request errors to HTTP 400 and omit input values. Use deterministic mappings:
200 for successful inspection and duplicate return, 202 for accepted/queued work and newly
requested cancellation, 400 for malformed schemas and application validation, 403 for access
denial, 404 for well-formed unknown job IDs, 409 for conflicts or unavailable retained results,
429 for queue capacity, and 503 for closed or unavailable required services. Readiness remains a
typed success envelope with HTTP 503 when not ready. Unexpected exceptions produce a generic safe
500 response and remain available to normal server logging.

Requests and projections are bounded. Job IDs use the lowercase deterministic format. Registry
responses are counts-only, progress history is optional and capped, and result responses exclude
payload bytes and detailed records.

## Consequences

- Equal projections produce equal JSON structures without timestamps or random request IDs.
- FastAPI may still describe its conventional validation response in generated schema metadata;
  runtime internal validation is normalized to the v1 HTTP 400 envelope.
- Declared `Content-Length` is enforced, while deployment infrastructure must later enforce bodies
  whose actual length cannot be established from that header.

## Supersession

Breaking field, code, or status changes require a separately versioned route and schema contract
with an ADR explicitly superseding this record.
