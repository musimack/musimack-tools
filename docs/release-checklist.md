# Release checklist

## Source and CI

- [ ] Worktree is clean and the exact commit is recorded.
- [ ] Local and hosted `main` agree.
- [ ] Required Linux and Windows checks are green.
- [ ] No unexpected skip, secret, network, lock, migration, or artifact failure exists.
- [ ] Backend and frontend dependency/lock files changed only when explicitly authorized.
- [ ] Migration has exactly head `0013_website_migration_qa` with parent `0012_structured_data_audit`, or the release notes explain an approved successor.
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
