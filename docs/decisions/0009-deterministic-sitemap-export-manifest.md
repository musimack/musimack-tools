# ADR 0009: Deterministic Sitemap Export Manifest

## Status

Accepted for implementation review.

## Context

A published XML package needs machine-readable evidence tying filenames and counts to the exact
bytes generated, without adding timestamps or host-specific data that would defeat reproducibility.

## Decision

Define the centralized schema identifier `sitemap-publication-manifest-v1`. Generate UTF-8 JSON
with sorted keys, two-space indentation, `ensure_ascii=False`, LF newlines, and a final newline.
Order records as URL sitemap documents followed by the optional sitemap index.

Record XML format and recommendation rule-set versions, package and URL counts, index presence or
blockage, duplicate/rejection/skipped counts, safe conflict configuration, and each XML payload's
logical name, document type, media type, entry count, exact byte count, and lowercase SHA-256.
Hash the precise immutable XML bytes.

The manifest does not list itself and contains no timestamp, username, machine name, random ID,
absolute repository path, or absolute export path. Its own exact byte count and SHA-256 are returned
outside the JSON, preventing recursive self-hashing.

## Consequences

Equal bundle evidence and safe configuration produce byte-for-byte equal manifests. Changing any
XML bytes changes its file hash, manifest bytes, and manifest hash. The manifest describes intended
XML payloads even in dry run and does not imply that publication occurred.

## Deferred work

Signatures, external attestations, database-backed manifests, timestamps, export history,
compression, remote storage metadata, submission receipts, public APIs, and CI remain deferred.
