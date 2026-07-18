# 0072: Evidence-backed website migration QA

## Status

Accepted for Phase 26 review.

## Context

Migration review combines operator plans with observations from several crawl products. Treating a redirect map as proof, silently fetching missing pages, or collapsing uncertainty into pass/fail would violate safety and explainability boundaries.

## Decision

Implement migration QA as an opt-in orchestration layer over retained crawl evidence. Persist plans, mappings, observations, comparisons, findings, recommendations, summaries, exports, and lifecycle events in normalized tables. Preserve planned and observed values separately. Use explicit confidence, human-review, and indeterminate states. Keep the private API permission mapped and exports within authenticated artifact storage.

The service performs no network request and generates no live redirect or server configuration. Its policies and exports are deterministic, versioned, and bounded.

## Consequences

Operators receive a durable pre-launch or post-launch QA record. Complete comparisons depend on retained evidence; gaps produce warnings, not fabricated conclusions. The implementation adds schema and UI surface but no dependency or public-network authority.
