# ADR 0074: Pinned CI and review-only release candidates

## Status

Accepted for Phase 28 implementation and human review.

## Context

The repository previously had comprehensive local validation but no hosted workflow, release policy, or reproducible candidate package. CI must execute untrusted pull-request code without secrets, retain the network-free test boundary, exercise Linux symlinks and Windows junctions, and avoid granting validation authority to mutable action tags. Release preparation must not imply permission to tag, publish, migrate production, or deploy.

## Decision

Use one read-only CI workflow for pull requests and `main`, with full Ubuntu 24.04 validation followed by focused Windows 2025 filesystem validation. Pin the four official GitHub actions to independently verified full commits, disable action caches and persisted checkout credentials, and use no third-party actions or write permissions.

Use a separate manual workflow to validate an exact commit and a bounded `rc-` identifier, rerun mandatory gates, build the frontend, create deterministic standard-library ZIP/JSON/SHA-256 evidence, reproduce it, and upload only the sanitized candidate for five days. Tagging, GitHub Release creation, deployment, and production migration are absent.

## Consequences

CI is slower without caches and duplicates validation during candidate creation, but results do not depend on mutable cache state. Explicit runner labels reduce image drift without eliminating hosted-image changes. Linux full-suite execution and Windows focused execution jointly cover platform risk. Action pins and runtime versions require periodic reviewed maintenance. The candidate is suitable for internal human review, not package-registry publication or software-bill-of-materials claims.
