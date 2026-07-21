# Release checklist

## Source and CI

- [ ] Worktree is clean and the exact commit is recorded.
- [ ] Local and hosted `main` agree.
- [ ] Required Linux and Windows checks are green.
- [ ] No unexpected skip, secret, network, lock, migration, or artifact failure exists.
- [ ] Backend and frontend dependency/lock files changed only when explicitly authorized.
- [ ] The accepted published baseline has exactly head `0015_sitemap_recommendation_retention` with parent `0014_durable_result_projection`, or the release notes explain an approved successor.
- [ ] Production frontend build has no source maps or embedded credentials.

## Candidate evidence

- [ ] Candidate identifier and exact 40-character commit are correct.
- [ ] Manifest schema, commit, source timestamp, migration, tool versions, and lock hashes are correct.
- [ ] Archive contains only approved paths.
- [ ] External checksums and every manifest file hash verify.
- [ ] Repeated packaging produced matching archive, manifest, and checksum bytes.
- [ ] Release notes include user, operations, migration, security, backup, upgrade, limitations, validation, and rollback sections.

## Human authorization

- [ ] Known limitations are accepted.
- [ ] Pre-upgrade backup location, retention, and restore rehearsal are confirmed.
- [ ] Human product acceptance is recorded.
- [ ] Tag creation is separately authorized.
- [ ] GitHub Release publication is separately authorized.
- [ ] Deployment is separately authorized.
- [ ] Rollback owner and decision threshold are recorded.

Do not infer authorization for a later checkbox from completion of an earlier one.

## CSA-06 product-owner gate

- [x] Deterministic WordPress, Custom, No preset, and parameter-heavy audits retained.
- [x] Corrected Aluma audit retained; no additional public crawl submitted.
- [x] Roles, sessions, SSRF, exposure, evidence security, and hard bounds validated.
- [x] Responsive/accessibility and bounded large-table behavior reviewed.
- [x] Restart, recovery, backup/restore, and ten-artifact integrity validated.
- [x] Initial bundle reduced by lazy Site Audit route splitting without a dependency.
- [ ] David has reviewed and accepted CSA-06.
- [ ] Separate authorization exists for staging, commit, release, publication, or deployment.
