# ADR 0032: Worker leases and heartbeats

Status: Accepted

## Context

Durable claims need ownership evidence that survives process loss and rejects obsolete workers.

## Decision

Register explicit bounded worker identities and create one active lease per claimed job. Every claim
uses a secure random `lease-<32 lowercase hexadecimal characters>` token, increasing generation,
durable acquired sequence, UTC expiry, and the exact protocol
`seo-toolkit-worker-protocol-v1`. Heartbeats validate job, worker, token, generation, active state,
and expiry before extending a lease. A partial unique SQLite index enforces one active lease per job.

Tokens are internal credentials: public APIs, logs, diagnostics, and readiness never expose them.
No worker identity is inferred from hostname, username, process arguments, or environment defaults.

## Consequences

Old generations cannot write after a replacement claim. UTC clock correctness is required for
expiry, while integer sequences remain the ordering authority. This is database fencing for one
machine, not a distributed consensus protocol.
