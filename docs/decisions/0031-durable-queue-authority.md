# ADR 0031: Durable queue authority

Status: Accepted

## Context

The in-memory registry cannot retain queued execution across process restarts. Optional persistence
previously recorded evidence but deliberately did not schedule work.

## Decision

Add explicit in-memory and durable scheduler modes. In durable mode, SQLite queue records and
transactional integer sequences are the sole scheduling authority. Submission persists the accepted
run request and returns without creating a local registry task. Claims use a short `BEGIN IMMEDIATE`
transaction and deterministic availability, submission, attempt, and job-ID ordering.

The exact durable contract is `seo-toolkit-durable-execution-v1`. Durable mode is disabled by
default and requires current persistence. No dual scheduler is permitted.

## Consequences

Queued jobs survive restart and can be inspected or cancelled without a live worker. SQLite lock
behavior limits this design to bounded single-machine coordination. Raw bodies, artifact bytes, and
full crawl frontiers remain outside the database. Redis, PostgreSQL, distributed workers, and public
queue controls are deferred.
