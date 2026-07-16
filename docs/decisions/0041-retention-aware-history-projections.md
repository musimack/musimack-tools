# 0041: Retention-aware history projections

Status: Accepted for `seo-toolkit-history-service-v1`.

## Decision

Return immutable projections with explicit full, metadata-only, result-unavailable, evicted,
interrupted, retained, and artifact missing/expired/deleted availability. Durable metadata remains
queryable when process-local payloads or files are gone. Missing evidence is not fabricated.

Related attempts, stages, warnings, failures, and artifact references are independently bounded
and include truncation evidence. Messages use persisted safe summaries and normalized URLs.
Artifact references expose safe names and download availability but no root, relative path, or
hash. Attempts never expose lease tokens.

## Consequences

Not-found remains distinct from unavailable result content. Existing retention, reconciliation,
and artifact lifecycle authorities are preserved.
