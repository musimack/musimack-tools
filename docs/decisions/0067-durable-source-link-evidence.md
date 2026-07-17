# ADR 0067: Persist parser-owned source-link occurrences

Status: implemented for review

Phase 22 needs source page, href, anchor, rel, and occurrence evidence. The accepted HTML parser already produces these records transiently, while the durable page projection previously discarded them.

Persist a bounded projection in `crawl_link_evidence` during the existing terminal page-evidence transaction. Preserve parser occurrence order and accepted normalization/scope decisions. Do not add another crawler, parser, redirect resolver, or page authority. Link-audit cleanup never deletes source evidence independently of its run.
