# ADR 0071: Durable Structured-Data Evidence and Audit

Status: accepted

## Decision

Extend the existing crawl parser and page-evidence terminal transaction to retain bounded, inert JSON-LD, Microdata, and conservative RDFa evidence. Analyze only that evidence in a durable, restart-safe Phase 25 audit with a private authenticated API and protected frontend.

## Rationale

Parser ownership prevents drift between crawl and audit interpretation. Durable raw and normalized fingerprints preserve explainability and deterministic duplicate analysis. Standard-library JSON parsing avoids a dependency change. Conservative vocabulary and versioned profiles provide useful review signals without implying remote vocabulary resolution or rich-result certification.

## Consequences

Migration `0012_structured_data_audit` is the single schema head. Evidence and derived rows consume bounded storage and follow existing retention. Malformed, external-context, unsupported, and truncated patterns remain findings. The system performs no new network activity, JavaScript execution, live-site mutation, or search-engine eligibility validation.
