# ADR 0059: Metadata audit domain and applicability

Status: accepted

Phase 20 uses explicit authenticated execution against a terminal run and consumes only durable Phase 20A page evidence. Central rules apply status checks to attempted URLs, content checks to fetched responses, HTML metadata checks only to parsed HTML, and robots/indexability checks only where evidence exists. Missing, empty, unavailable, partial, and failed evidence remain distinct. No page is re-fetched or reparsed.

Audit identity hashes the run ID, exact versions, and canonical configuration. Identical input is idempotent; conflicting configuration fails closed. Lifecycle states are `planned`, `running`, `completed`, `completed_with_warnings`, `partially_completed`, `failed`, and `cancelled`.
