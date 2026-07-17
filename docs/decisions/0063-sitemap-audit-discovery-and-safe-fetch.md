# 0063: Sitemap audit discovery uses the accepted safe-fetch boundary

Status: implemented for review

Phase 21 orders explicit, robots, common-location, and child-index candidates deterministically and normalizes them before retrieval. Every robots and sitemap request uses the accepted fetch protocol, preserving DNS, SSRF, redirect, scope, timeout, byte-limit, and safe-logging controls. The accepted host-scope mode and approved-host set are reconstructed from the durable run configuration snapshot; an absent or unreadable historical snapshot is rejected instead of being silently reinterpreted as exact-host. No raw HTTP client or second crawler is introduced.

Missing discovery candidates are evidence, not fatal errors. Requested and final URLs plus redirect evidence are retained, while payload bodies are not. Gzip is reported as unsupported and is never decompressed.
