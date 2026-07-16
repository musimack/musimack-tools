# 0044: Server-side session security

Status: Accepted for `seo-toolkit-session-v1`.

## Decision

Issue opaque `session-<64 lowercase hex>` browser tokens and persist only their SHA-256 hashes.
Carry the raw token only in the bounded-path `musimack_session` HttpOnly, Secure,
SameSite=Strict cookie. Validate expiry, idle timeout, active user state, and the current user
revocation generation on every protected request.

## Consequences

Roles and permissions never become client claims. Role, lifecycle, and password changes invalidate
stale sessions. Session cleanup and login-evidence cleanup are explicit bounded operations; no
background task, Redis, signed JSON token, or process-local session authority is introduced.
