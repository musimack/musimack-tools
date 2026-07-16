# ADR 0013: Deterministic run identity and summaries

## Status

Accepted

## Decision

Derive the run ID from lowercase SHA-256 of canonical UTF-8 JSON containing the normalized seed,
requested stages, portable crawl/scope/policy/XML/publication settings, and orchestration version.
Display the first 12 hexadecimal characters with a `run-` prefix while retaining the full digest.
Caller labels are separate. Absolute roots, machine identity, timestamps, credentials, environment
values, and temporary paths are excluded.

Serialize `crawl-run-summary-v1` JSON and a human-readable Markdown companion deterministically in
memory. Both use UTF-8, LF newlines, and a final newline; exact hashes and byte counts remain outside
their own bytes. Optional local writing uses fixed filenames and the accepted filesystem safety and
atomic-write primitives under a separately configured absolute root.

Durable summaries contain authoritative final counts but not the in-memory progress-event stream.

## Consequences

Equal portable requests and evidence produce equal IDs and summary bytes. The 48-bit display prefix
is for human reference, not uniqueness enforcement; the full 256-bit digest is authoritative.
Summaries are operational artifacts separate from the sitemap manifest. Persistent history,
signatures, remote storage, and replay-only summary generation remain deferred. Future changes must
introduce a new schema or orchestration version and supersede this ADR when compatibility changes.
