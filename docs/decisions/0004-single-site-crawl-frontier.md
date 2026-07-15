# ADR 0004: Single-Site Crawl Frontier and In-Memory Orchestration

- Status: Accepted for implementation
- Date: 2026-07-15

## Context

The accepted safe-fetch and HTML-extraction boundaries operate on one URL. Reusable SEO modules
need a deterministic way to traverse one approved site without embedding scheduling in the
fetcher or parser, and without prematurely introducing databases, job services, or public crawl
endpoints.

## Decision

Add an internal asynchronous orchestrator with an in-memory breadth-first frontier. The accepted
normalized URL is the sole crawl key. Pending URLs are ordered by best-known depth and stable
discovery order; only one depth batch is processed at a time, with bounded concurrency inside the
batch. Completion order does not determine link admission order.

The orchestrator composes narrow fetcher and parser protocols. It applies scope, depth, query, and
explicit exclusion rules before frontier admission. Nofollow and canonical values remain evidence,
not frontier-control directives. Redirect final URLs may suppress a redundant pending URL.

Each crawl request is validated against server hard maxima for URLs, depth, duration, total bytes,
workers, and pending queue size. Starts are paced independently per origin. Cancellation and
progress observation are injected protocols. Results, URL records, counters, discoveries, limit
events, cancellation evidence, and controlled errors are immutable and remain in memory.

No crawl API, persistence, background job, progress transport, robots behavior, sitemap decision,
or export is introduced by this decision.

## Consequences

- Future sitemap, broken-link, redirect, and metadata workflows can reuse one traversal boundary.
- Deterministic ordering and fake time/fetch dependencies make tests network-free and repeatable.
- Depth-batch processing favors reproducibility over fully opportunistic queue throughput.
- Cooperative cancellation cannot preempt arbitrary third-party awaits; accepted fetch timeouts
  remain the outer bound for an active request.
- Process failure loses the in-memory crawl and its progress.
- Network authorization continues to belong to the safe fetcher and deployment egress controls;
  frontier admission alone never authorizes a connection.

## Deferred decisions

Durable job execution, persistence schema, progress streaming, restart recovery, robots policy,
indexability, sitemap eligibility, XML/CSV exports, authentication, deployment, and frontend
integration require later decisions.

## Supersession

A later ADR may supersede this decision by naming this record, explaining the new trade-offs, and
preserving or explicitly migrating the stable crawl evidence contracts.
