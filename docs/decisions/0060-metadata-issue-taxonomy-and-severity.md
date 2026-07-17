# ADR 0060: Metadata issue taxonomy and severity

Status: accepted

The versioned taxonomy has title, meta description, canonical, robots, indexability, status, and content-type categories. Severity is deterministic and caller-independent: critical, high, medium, low, or information. Critical is limited to 5xx responses and redirect loops; invalid/conflicting canonical, indexability conflict, recommendation mismatch, 4xx, and determinate missing status are high. Other exact mappings live in the centralized domain table.

Title thresholds default to 20 and 60; description thresholds default to 70 and 160. They are heuristics, not search-engine rules. Duplicate normalization is Unicode NFKC, trim, internal whitespace collapse, Unicode case-fold, preserved punctuation/stop words, and exclusion of empty values. It is exact, hash-grouped, bounded, and never fuzzy.
