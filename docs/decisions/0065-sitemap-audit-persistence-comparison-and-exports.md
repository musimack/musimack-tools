# 0065: Sitemap audits persist normalized evidence and deterministic comparisons

Status: implemented for review

Migration `0008_sitemap_audit`, down revision `0007_metadata_audit`, adds seven normalized tables with foreign keys, uniqueness, checks, indexes, and cascades. Raw XML, complete headers, passwords, tokens, and artifact bytes are excluded. Audit configuration and stable parser/comparison versions are captured.

The comparison domain evaluates the sorted union of valid sitemap entries and durable crawl evidence. It reuses accepted recommendation states and emits stable comparison states, actions, and reason codes. Specific retained redirect, noindex, canonical, and known non-HTML evidence precedes generic failed or unavailable evidence; invalid raw locations remain validation findings. The adapter is intentionally conservative where a separately persisted recommendation projection is unavailable. CSV formula-like values receive a leading apostrophe; JSON and Markdown are stable and versioned. All formats use existing artifact registration and download authority.

Execution remains a synchronous authenticated request, but admission is an atomic durable state claim and every lifecycle transition is committed independently. Duplicate and terminal execution are rejected. Request cancellation and execution failure become terminal, and service startup reconciles process-interrupted nonterminal audits as failed; stored results are durable, while execution itself is not resumable.
