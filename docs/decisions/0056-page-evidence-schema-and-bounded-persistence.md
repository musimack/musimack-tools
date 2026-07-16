# ADR 0056: Page evidence schema and bounded persistence

## Status

Accepted.

## Decision

Alembic revision `0006_page_crawl_evidence` (`add durable page crawl evidence`) adds normalized
page, redirect-hop, parse-warning, summary, and event tables. A single terminal observer writes the
projection in batches after the accepted crawl result exists. There is no new run stage or
competing crawler sink.

Identity is SHA-256 over run ID, discovery sequence, and normalized requested-URL identity.
Ordering is `crawl_discovery_sequence_asc_url_identity_asc-v1`. Defaults cap runs at 100,000 pages,
batches at 250, redirect chains at 20 hops, warnings at 50 per page, and metadata at 4,096
characters.

## Consequences

Writes are idempotent, collisions are explicit conflicts, and downgrade removes only Phase 20A
tables. Existing run IDs and durable execution semantics do not change.
