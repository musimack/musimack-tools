# ADR 0023: Internal bearer authentication

## Status

Accepted for the internal production-composition boundary.

## Decision

Use one environment-backed bearer credential for v1. The explicit production verifier strictly
accepts `Authorization: Bearer <credential>`, compares it with `hmac.compare_digest`, and returns a
separately configured non-secret caller identifier. Missing or invalid credentials receive the
same safe `401` response and `WWW-Authenticate: Bearer`; secrets never enter reports, responses,
OpenAPI, or logs.

## Consequences

Production composition fails when enabled without a credential. The default health app loads no
secret. This is a bounded internal gate, not users, roles, sessions, OAuth, JWT, persistence, or a
public authorization model. Managed secret storage and rotation remain future work.
