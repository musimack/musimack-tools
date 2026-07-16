# 0048: Frontend API client boundary

Status: Accepted for `seo-toolkit-frontend-api-client-v1`.

## Decision

Use a small native-fetch adapter for `/api/internal/v1`. Always request JSON and include browser
credentials, validate authentication response shapes at runtime, map backend snake-case fields at
the boundary, and normalize structured and non-JSON failures into a bounded `ApiError`. Reject
unknown roles and permissions rather than silently expanding browser authority.

## Consequences

The foundation needs no Axios, generated client, or server-state library. Passwords occur only in
the sign-in request body. The client never stores bearer tokens, passwords, session tokens, or
cookies and never exposes raw network exception text. Workflow-specific response contracts can be
added narrowly when their frontend phases are accepted.
