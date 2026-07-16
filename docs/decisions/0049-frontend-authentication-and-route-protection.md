# 0049: Frontend authentication and route protection

Status: Accepted for `seo-toolkit-frontend-auth-v1`.

## Decision

Represent authentication as the exact states `initializing`, `authenticated`, `unauthenticated`,
`expired`, and `unavailable`. Discover sessions through `GET /auth/me`, sign in and out through the
existing password-session endpoints, and rely exclusively on the server-managed HttpOnly cookie.
Centralize protected route metadata and require an exact permission before rendering each private
page.

## Consequences

Loading, expired-session, unavailable-service, unauthorized, and missing-route experiences are
deterministic. Permission-aware navigation avoids misleading links, while every API request still
depends on authoritative backend enforcement. No local storage, session storage, cookie parsing,
JWT, OAuth, or browser bearer-token lifecycle is introduced.
