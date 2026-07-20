# ADR 0076: Reproduce populations and link specialist authorities

## Status

Proposed for CSA-01 product-owner review.

## Context

A combined report needs explicit denominators and image/structured-data summaries, while accepted
specialist modules already own normalized evidence, derived findings, exports, and routes.

## Decision

Retain versioned, nonexclusive population memberships derived from durable evidence. The executive
denominator is indexable, canonical, metadata-scoring-eligible HTML pages. Report all discovery,
queue, fetch, parse, eligibility, exclusion, failure, partial, and indeterminate counts separately.
Normalized collisions retain original discovery counts; redirects and canonicals do not collapse
page evidence.

Specialists remain the deep source of truth. CSA may embed accepted crawl evidence, link an explicit
child audit, use an identity-compatible eligible prior audit, or declare the summary unavailable.
Image and structured-data base counts come from retained crawl evidence; specialist findings require
a provenance-bearing linked audit. CSA does not duplicate specialist tables or exports.

## Consequences

- Counts can be reproduced after restart and definition changes remain versioned.
- “Completed with warnings” does not imply complete population or every module complete.
- CSA-03 stores policy/population projections and links, not raw specialist duplicates.
- CSA-04 owns child orchestration and freshness checks.

## Rejected alternatives

- One unlabeled page count: not auditable.
- Canonical collapsing: destroys observed URL evidence.
- Automatically launching every specialist: costly and hides operator intent.
- Copying specialist findings into new CSA authorities: creates drift and conflicting exports.
