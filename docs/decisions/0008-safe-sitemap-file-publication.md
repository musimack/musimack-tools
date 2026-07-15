# ADR 0008: Safe Sitemap File Publication

## Status

Accepted for implementation review.

## Context

The XML serializer returns immutable bytes but intentionally owns no filesystem behavior. Internal
operators need a bounded local publication boundary that cannot turn logical package names into
arbitrary filesystem destinations or silently overwrite existing content.

## Decision

Require an explicit absolute `pathlib.Path` output root and construct every target from a validated
simple logical filename. Reject traversal, separators, absolute and drive-qualified names, UNC
paths, nulls, reserved Windows device stems, duplicate and case-folded collisions, `.git` roots,
link-containing roots, linked targets, and directory targets. Directory creation defaults off.

Support `fail_if_exists` by default and explicit `overwrite`. Preflight the complete package before
mutation. No-overwrite finalization uses atomic same-filesystem hard-link creation so a target that
appears after planning cannot be replaced. Overwrite uses atomic replacement. Temporary files use
secure unpredictable names inside the target directory; bytes are flushed, `fsync`ed, finalized,
read back, and hash-verified. Temporary files are cleaned on controlled failure.

Classify a target appearing after preflight as `target_exists`. Classify unavailable hard-link
support, permission denial, and other no-clobber finalization failures as
`no_clobber_finalization_unsupported`, `no_clobber_finalization_permission_denied`, and
`no_clobber_finalization_failed`. Cleanup failure remains `cleanup_failed`. None may fall back to
`replace`; inability to obtain the race-safe primitive blocks that file and may produce a typed
partial-package result when earlier files completed. Same-directory temporary files keep the
ordinary operation on one filesystem.

Atomicity is per file. A later package failure reports completed files and remains
`partially_failed`; earlier files are not rolled back and existing user files are never deleted.
Dry run shares the planner and performs no filesystem mutation.

## Consequences

The publisher is local-filesystem only and deliberately conservative around links and platform
path ambiguity. Filesystems that do not support hard links cannot use the no-overwrite executor,
although planning remains available. Application checks cannot eliminate every directory-ancestor
replacement race when an adversary can concurrently mutate the export path, so deployment must
restrict write access to the output root and its parents. New files use platform-default ownership
and permissions.

Reject link components reported by `Path.is_symlink()` and Windows junctions reported by
`Path.is_junction()`. Tests exercise junction roots and ancestors without administrator symlink
privilege. Symlink tests skip only after a minimal link-creation probe returns a recognized
capability or privilege error; later production failures remain test failures. Other Windows
reparse-point types are not claimed as fully covered.

## Deferred work

`replace_only_if_changed`, whole-package transactions, rollback history, versioned exports, remote
publication, public APIs, CLI, persistence, background jobs, submission, frontend, authentication,
Docker, and CI remain deferred.
