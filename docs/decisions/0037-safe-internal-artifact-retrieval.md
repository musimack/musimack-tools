# ADR 0037: Authenticated bounded artifact retrieval

## Decision

Production composition may add three authenticated internal routes for bounded listing, safe detail,
and download. The default app remains health-only. Download verifies by default, rechecks path and
file identity before opening, streams configured chunks, closes handles deterministically, and uses
type-derived content types and validated filenames.

API projections omit absolute paths, relative storage paths, database rows, credentials, lease data,
and file contents. Range requests, public links, signed URLs, and cloud delivery are unsupported.
