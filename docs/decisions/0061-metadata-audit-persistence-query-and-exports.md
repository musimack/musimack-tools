# ADR 0061: Metadata audit persistence, query, and exports

Status: accepted

Migration `0007_metadata_audit` adds audits, pages, issues, duplicate groups/members, summaries, exports, and events. Foreign keys retain jobs, runs, durable evidence, and artifact authority. Unique constraints make page and issue writes idempotent. Downgrade removes only Phase 20 tables and returns to `0006_page_crawl_evidence`.

All lists are bounded and use versioned opaque cursors tied to query kind, ordering, filter fingerprint, and continuation key. Exports are CSV, JSON, and Markdown with a 100,000-row ceiling and explicit truncation evidence. CSV formula-leading cells receive an apostrophe. Files are written under configured artifact roots, SHA-256 verified, registered, privately downloaded, and reused.
