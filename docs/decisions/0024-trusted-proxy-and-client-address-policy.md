# ADR 0024: Trusted proxy and client-address policy

## Status

Accepted for the internal production-composition boundary.

## Decision

The direct socket peer is authoritative by default. `X-Forwarded-For` is considered only for an
explicit trusted-proxy CIDR. Exactly one bounded header is parsed left-to-right; the first address
outside proxy CIDRs is the client, or the leftmost address when all entries are proxies. Malformed,
empty, excessive, zone-qualified, or multiple evidence fails closed. Optional trusted-client CIDRs
are applied after resolution. No DNS rules exist.

## Consequences

Untrusted peers cannot spoof forwarded evidence. The policy intentionally supports a simple proxy
topology and does not replace firewall isolation, TLS termination, or topology-specific reverse
proxy configuration.
