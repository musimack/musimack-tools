# Release readiness

This checklist governs a future internal release-candidate decision. Phase 29 does not authorize or
perform a tag, GitHub Release, deployment, production migration, or customer crawl.

## Required green gates

- Exact reviewed commit; clean worktree; one Alembic head; dependency/lock comparison unchanged.
- Ruff format/lint, strict MyPy, full backend tests, accepted platform skips only, import audit,
  `pip check`, offline lock comparison, network-isolation checks, secret/artifact scans, and
  `git diff --check`.
- Prettier, ESLint, TypeScript, full Vitest, production build, offline development/production npm
  audits, bundle secret scan, and no source maps.
- Hosted Linux and focused Windows CI green at the exact candidate commit after publication.
- Administrator/operator/viewer browser acceptance, responsive matrix, accessibility smoke,
  authentication/authorization/error review, and no blocking known limitation.
- Empty-database migration, preflight, web/worker health/readiness, worker failure/recovery,
  reconciliation, retention, offline backup, non-destructive restore, restored authentication and
  artifact verification, and rollback rehearsal.
- Deterministic candidate generation and verification twice, identical checksums, complete manifest,
  safe exclusions, and cleanup of local rehearsal output.

## Human approvals and release sequence

1. Review Phase 29 changes, security/accessibility reviews, and every known limitation.
2. Authorize a normal commit and push; require hosted CI at that exact commit.
3. Select and record one semantic version consistently across backend and frontend metadata.
4. Complete release notes from `docs/templates/release-notes.md`, including migrations, backup,
   rollback, security, validation, and limitations.
5. Stop writers and create/verify a pre-upgrade backup in the authorized environment.
6. Authorize the manual review-candidate workflow for the exact commit and candidate identifier.
7. Verify downloaded manifest/checksums and inspect the candidate. Record human acceptance.
8. Obtain separate explicit authorization for the tag, GitHub Release, deployment, and migration
   window. None is implied by earlier steps.

## Rollback readiness

Disable ingress, stop web and worker, preserve the failed database/artifacts/logs, restore the
pre-upgrade backup into new paths, run the prior accepted application and its preflight, start worker
then web, verify health/readiness/login/history/artifacts, and only then restore ingress. Never
automatically downgrade or overwrite the failed state. Keep both states until incident closure.

## Decision rule

Use **Ready** only when every gate passes and no limitation is blocking. Use **Ready with
nonblocking limitations** only when every blocking gate passes and each remaining issue has explicit
impact, workaround, severity, and treatment. Any security bypass, corruption/recovery failure,
public exposure, migration incompatibility, broken primary workflow, major accessibility/responsive
barrier, or CI failure requires **Not ready**.

## CSA-06 engineering recommendation

The evidence in `combined-site-audit-csa06-acceptance.md` is **ready for final product-owner
acceptance** after deterministic and bounded real-site data-quality review, role/security gates, 40
responsive combinations, restart/recovery, isolated backup/restore, all-ten-artifact verification,
and initial-bundle reduction. This does not declare human acceptance or grant commit, publication,
migration, release, or deployment authority.
