# ADR 0010: Sitemap Generation Orchestration

## Status

Accepted for implementation review.

## Context

Recommendation, XML serialization, manifest generation, publication planning, and filesystem
execution have distinct policy ownership. Internal callers need one result without duplicating or
collapsing these boundaries into an ambiguous success flag.

## Decision

Define centralized orchestration version `sitemap-publication-v1` and add a framework-independent
`SitemapPublicationService`. Its immutable request contains a recommendation projection, XML
configuration, and optional publication configuration. It invokes the accepted XML generator,
then the manifest and publication planner, and finally the executor unless publication was omitted
or dry run was selected.

The result retains the XML bundle, recommendation and XML versions, publication version, complete
plan, publication files, hashes, byte counts, warnings, rejections, and failures. Explicit states
distinguish generated output from publication `not_requested`, `dry_run`, `published`, `blocked`,
and `partially_failed`. The service does not re-evaluate eligibility, reconstruct XML, duplicate
path logic, or catch unrelated failures as success.

The service is internal Python composition only. It has no FastAPI, crawler, network, database,
queue, frontend, submission, or remote-publication dependency.

## Consequences

Future UI, job, API, persistence, and approval layers can consume one explainable immutable result
while retaining the existing authorities beneath it. Generation can succeed and remain available
when publication is blocked or partially fails.

## Deferred work

Public routes, CLI, frontend, authentication, approval workflows, persistence, export history,
background jobs, scheduling, remote publication, submission, compression, optional sitemap
metadata, rollback history, Docker, and CI remain deferred.
