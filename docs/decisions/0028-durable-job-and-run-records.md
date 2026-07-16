# ADR 0028: Durable job and run records

## Status

Accepted for `seo-toolkit-persistence-v1`.

## Decision

Persist immutable configuration snapshots and bounded operational evidence for runs, jobs, run
stages, progress, warnings, failures, summaries, and published-artifact metadata. Repository
interfaces use typed domain records; ORM rows remain private storage representations.

Accepted job submission is recorded before in-memory scheduling. Subsequent transitions and
terminal evidence are written through short, explicit transactions. Stored URLs omit query strings,
and persisted evidence excludes credentials, raw response bodies, XML, manifests, and summary
blobs. Artifact records contain metadata and hashes only.

A null repository preserves existing behavior when persistence is disabled. A persistence write
failure does not silently erase execution evidence: orchestration adds a stable, safe coordination
warning while keeping the existing public API contract unchanged.

## Consequences

Job and run history can survive process restarts without making the database the live scheduler.
No public persistence routes, cross-process queue, automatic resume, artifact blob store, or user
ownership model is introduced by this decision.
