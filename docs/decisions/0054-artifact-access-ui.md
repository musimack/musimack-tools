# 0054: Artifact access UI

Status: Accepted for `seo-toolkit-artifact-access-ui-v1`.

## Decision

List and inspect artifact metadata through the existing authenticated API. Download is always an
explicit user action, uses cookie credentials, validates the identifier, accepts only a safe
attachment filename, creates a short-lived object URL, and revokes it immediately after use.

## Consequences

The browser receives no storage root or absolute path. Lifecycle and integrity failures remain
clear non-downloadable states, and metadata browsing never triggers a file transfer.
