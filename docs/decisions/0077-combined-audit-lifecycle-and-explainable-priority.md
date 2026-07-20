# ADR 0077: Separate lifecycle completeness and use explainable priority

## Status

Proposed for CSA-01 product-owner review.

## Context

Durable crawling, optional specialist modules, and partial site coverage cannot be represented by one
ambiguous success flag. Issue priority must incorporate business context without overriding facts.

## Decision

Use the lifecycle defined in the product contract and separately expose run completion, population
completeness, and per-module completeness. Recovery-required is visible and nonterminal; reruns are
new immutable executions. Optional child failure affects module and warning/partial reporting rather
than automatically failing the parent.

Order issue groups with a versioned, disclosed lexicographic tuple: security protection, factual
severity, business importance, indexability/sitemap/internal-link impacts, affected count, pattern
leverage, confidence/determinacy, and stable identity. Business importance never changes severity or
evidence. Numeric weights and manual final-priority overrides are deferred.

## Consequences

- A bounded crawl may finish with warnings while clearly reporting incomplete population coverage.
- Exports can label exactly which evidence is partial.
- Users can understand and reproduce issue order.
- CSA-04 owns lifecycle reconciliation/priority projections; CSA-05 must expose all inputs.

## Rejected alternatives

- One composite status: conceals why evidence is incomplete.
- Child status directly controlling parent state: makes optional work unexpectedly fatal.
- Opaque numeric score: cannot explain changes and invites business context to alter factual severity.
