# ADR 0036: Durable artifact integrity and lifecycle

## Decision

SQLite stores artifact metadata and histories, never bytes. Expected size and SHA-256 remain
immutable; observed evidence is updated by bounded streaming verification. Lifecycle states are
planned, available, missing, corrupt, expired, deleted, and retained. Invalid transitions fail with
typed codes, and missing or corrupt artifacts return to available only after verification.

Publication manifests may reference only safe logical filenames registered for the same run and
root.

## Consequences

File publication remains successful when later metadata registration fails. Registration evidence
does not become a second publication authority.
