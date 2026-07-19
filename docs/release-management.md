# Release management

Phase 28 creates reviewable release candidates but does not authorize tags, GitHub Releases, deployment, or production migration. Those remain distinct human-controlled actions.

## Version and identifiers

The current product version is `0.1.0`, recorded consistently in backend module/project metadata and frontend package metadata. Phase 28 does not create a new version source or change that value. Until a later accepted release changes all three deliberately, they collectively remain the version evidence.

Release candidates use lowercase identifiers beginning with `rc-`, followed by lowercase ASCII letters, digits, dots, or hyphens. They are at most 64 characters, cannot contain `..`, cannot end in punctuation, and never become filesystem paths before validation. Example: `rc-phase28-validation`.

Future accepted release tags should use `vMAJOR.MINOR.PATCH`; pre-release tags should use `vMAJOR.MINOR.PATCH-rc.N`. Semantic versioning is recommended because product metadata already uses that shape, but no tag may be created until the version change, release notes, migration compatibility, backup plan, candidate checksums, and human acceptance are approved. Emergency fixes use a reviewed hotfix branch and patch increment; they do not bypass CI or backup requirements.

## Candidate package

The manual workflow requires an exact lowercase 40-character commit and a validated candidate identifier. It checks out only that commit with credentials disabled, repeats mandatory backend/frontend validation, builds the frontend, and packages approved content:

- `.env.example` and `README.md`
- Backend source, Alembic configuration/revisions, metadata, and requirements lock
- Frontend production build plus package metadata/lock evidence
- Deployment, operations, backup, architecture, CI, release, checklist, template, and relevant decision documents
- `release-manifest.json` inside and outside the archive
- External `CHECKSUMS.sha256`

It excludes Git history, tests, source frontend files, `node_modules`, virtual environments, caches, databases, artifact roots, backups, credentials, certificates, browser traces, logs, PID files, and temporary paths.

The ZIP uses sorted POSIX paths, fixed 1980 timestamps, stable regular-file modes, UTF-8 names, and deterministic compression. The manifest is sorted compact JSON with a final newline. It records schema version, candidate, product version, exact commit, detached source marker, UTC commit timestamp, migration head/parent, lock hashes, validation summary, build-tool versions, known-limitations reference, and each payload file's size/SHA-256. The commit timestamp is used instead of mutable wall-clock time so two builds of the same source/toolchain are reproducible. External checksums cover the archive and manifest. The verifier rejects missing, unexpected, duplicate, traversing, corrupt, or hash-mismatched members.

The candidate artifact has a fixed CI name, five-day retention, and contains only the ZIP, manifest, and checksums. It is private to the workflow run; reviewers must verify checksums before inspection.

## Human gates and release sequence

1. Merge only after required CI and review.
2. Prepare release notes from the template and identify known limitations.
3. Confirm migration head and upgrade compatibility.
4. Produce a candidate for an exact accepted commit.
5. Verify manifest, checksums, contents, reproducibility evidence, and CI results.
6. Complete human acceptance and record backup/rollback readiness.
7. Obtain separate authorization before tag creation.
8. Obtain separate authorization before GitHub Release publication.
9. Obtain separate authorization before deployment.

Candidate validation never implies authorization for later steps.

## Migration, backup, and rollback

Before any upgrade, stop writers and take the Phase 27 database/artifact backup described in `docs/backup-and-restore.md`. Ordinary application startup must not migrate. Run preflight, inspect the exact migration path, and execute the explicit migration command only in the authorized deployment window.

Rollback means disabling ingress, stopping web/worker, preserving the failed database/artifacts, restoring the pre-upgrade backup into new empty paths, and running the prior accepted application against that restored state. Never automatically downgrade or overwrite the failed state. A release containing a migration must state whether the prior application can read the upgraded schema; absent explicit evidence, rollback requires restored pre-upgrade data.

## Branch and tag protection recommendations

These settings are recommendations only; Phase 28 does not change GitHub repository configuration:

- Require pull requests and at least one independent approval for `main`.
- Require the Linux and Windows checks and conversation resolution.
- Require branches to be current when the merge queue or repository traffic justifies it.
- Restrict direct pushes, deletion, and force pushes; enforce rules for administrators.
- Protect `v*` tags from deletion, update, and unauthorized creation.
- Require separate human approval for candidate acceptance, tag creation, publication, and deployment.
- Consider signed commits only after confirming contributor tooling and recovery procedures; it is not currently required by repository evidence.

## Known limitations

- Hosted GitHub execution must be confirmed after review; local rehearsal validates commands and structure but cannot emulate GitHub's service.
- Reproducible archive bytes assume the same Python/ZIP implementation and build outputs; manifest and per-file hashes remain authoritative across toolchain changes.
- The package is an internal deployment candidate, not a Python/npm distributable and not an SBOM.
- GitHub-hosted runner images and registries remain external availability dependencies even with explicit runner labels and action pins.
- Release publication, tag protection, branch rules, deployment, and production backup execution remain human-controlled external operations.
