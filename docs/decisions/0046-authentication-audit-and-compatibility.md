# 0046: Authentication audit and compatibility

Status: Accepted for `seo-toolkit-auth-audit-v1` and
`seo-toolkit-auth-compatibility-v1`.

## Decision

Persist append-only, secret-free authentication and authorization audit events with deterministic
ordering. Keep expanded authentication disabled by default and retain `shared_bearer` as the
default mode. Permit persisted sessions only in explicit `user_session` or `hybrid` composition.

## Consequences

Existing deployments and the health-only default app do not change. Hybrid mode has no silent
downgrade: a presented invalid session is rejected, and bearer compatibility is considered only
when no session cookie is present. Audit records exclude passwords, hashes, raw tokens, bearer
credentials, headers, database URLs, paths, and raw exception text.
