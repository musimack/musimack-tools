# 0042: Private history API contract

Status: Accepted for `seo-toolkit-history-api-v1`.

## Decision

Mount ten history paths only during explicit enabled production composition beneath
`/api/internal/v1/history`. Apply the accepted bearer, trusted-network, trusted-proxy, correlation,
security-header, access-log, and error-envelope controls. The default application remains
health-only, and disabled history changes neither routes nor readiness.

Typed Pydantic schemas describe job/run pages, details, attempts, stages, messages, artifacts,
availability, pagination, and diagnostics. Typed filters replace arbitrary query construction.
Stable history failures map to safe 400, 404, or 503 responses without SQL or database detail.

## Consequences

Production route totals are 11 without optional features, 14 with artifacts only, 21 with history
only, and 24 with both. No public, client-facing, streaming, export, or frontend contract is added.
