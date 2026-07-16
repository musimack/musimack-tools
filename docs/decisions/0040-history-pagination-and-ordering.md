# 0040: History pagination and ordering

Status: Accepted for `seo-toolkit-history-pagination-v1`.

## Decision

Use opaque, deterministic base64url JSON cursors. Strict parsing verifies the cursor format,
pagination version, query kind, ordering identifier, filter fingerprint, durable sequence, and safe
entity identifier. No signing secret is introduced, so cursors are integrity-checked structurally
and are not claimed to be tamper-proof.

Jobs order by `submitted_sequence_desc_job_id_desc-v1`. Runs order by
`submitted_sequence_desc_run_id_desc-v1`, using the latest persisted job sequence. Queries request
one bounded extra row to determine `has_more`; totals are not returned by default.

## Consequences

Stable data produces no duplicates or omissions. Malformed, version-mismatched, filter-mismatched,
and order-mismatched cursors fail safely. Concurrent inserts sort before an existing cursor;
updates to filter fields can change live-query membership.
