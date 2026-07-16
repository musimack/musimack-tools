# ADR 0021: Deny-by-default internal access gate

## Status

Accepted for implementation.

## Context

Even explicitly mounted internal routes can expose job existence or mutate process-local state.
No complete authentication or authorization system is currently authorized.

## Decision

Apply one router-level access dependency to every internal endpoint. Missing verifiers deny all.
Denied and unavailable decisions return safe HTTP 403 envelopes. Verifier exceptions fail closed.
Access runs before application-service invocation, so denial performs no validation, preflight,
submission, lookup, cancellation, queue mutation, or filesystem inspection beyond ordinary request
parsing.

The verifier is injected by composition. Production code provides only a deny-all verifier; test
allow verifiers live in tests. Decisions contain stable outcomes and denial reasons plus an
optional safe caller identifier. Credentials, tokens, and raw verifier errors never enter response
contracts.

## Consequences

- Denied status and cancellation requests cannot become job-existence oracles.
- Importing or mounting without deployment configuration cannot create an allow bypass.
- The gate is not authentication: it has no identities, credentials, sessions, roles, or durable
  policy and is insufficient for public exposure.
- Future authentication and authorization must be separately designed and reviewed.

## Supersession

A future ADR may replace the verifier with a complete authenticated principal and authorization
model. It must retain fail-closed behavior and explicitly supersede this record.
