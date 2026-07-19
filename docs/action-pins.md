# Official GitHub Action pins

Verified on 2026-07-18 UTC. Only repositories owned by the GitHub `actions` organization are permitted. Workflow references use the complete commit ID and retain the release tag as an inline comment. Pins never advance automatically; replacement requires a reviewed pull request that repeats this verification.

| Action | Stable release | Release date (UTC) | Immutable commit | Verified status | Runtime / runner |
| --- | --- | --- | --- | --- | --- |
| `actions/checkout` | `v7.0.0` | 2026-06-18 | `9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0` | GitHub-verified signature, valid | Node 24; Actions Runner 2.327.1+ |
| `actions/setup-python` | `v6.3.0` | 2026-06-24 | `ece7cb06caefa5fff74198d8649806c4678c61a1` | GitHub-verified signature, valid | Node 24; Actions Runner 2.327.1+ |
| `actions/setup-node` | `v7.0.0` | 2026-07-14 | `820762786026740c76f36085b0efc47a31fe5020` | GitHub-verified signature, valid | Node 24; Actions Runner 2.327.1+ |
| `actions/upload-artifact` | `v7.0.1` | 2026-04-10 | `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a` | GitHub-verified signature, valid | Node 24; Actions Runner 2.327.1+ |

## Official observations

For every action, verification used the official release page, official commit metadata/page, the official repository `action.yml` at the selected commit, and the official Git tag reference returned by `git ls-remote`:

- `https://github.com/actions/checkout/releases/tag/v7.0.0`
- `https://github.com/actions/checkout/commit/9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0`
- `https://github.com/actions/setup-python/releases/tag/v6.3.0`
- `https://github.com/actions/setup-python/commit/ece7cb06caefa5fff74198d8649806c4678c61a1`
- `https://github.com/actions/setup-node/releases/tag/v7.0.0`
- `https://github.com/actions/setup-node/commit/820762786026740c76f36085b0efc47a31fe5020`
- `https://github.com/actions/upload-artifact/releases/tag/v7.0.1`
- `https://github.com/actions/upload-artifact/commit/043fb46d1a93c77aae656e7c1c64a875d1fc6a0a`
- `https://api.github.com/repos/actions/<repository>/releases/latest`
- `https://api.github.com/repos/actions/<repository>/commits/<commit>`
- `https://api.github.com/repos/actions/<repository>/contents/action.yml?ref=<commit>`

The release pages and commit API reported valid GitHub signatures. The full tag IDs independently matched the release commits. These are lightweight tags, so no annotated-tag dereference was required.

## Compatibility and selection

The workflows use explicit `ubuntu-24.04` and `windows-2025` hosted labels rather than mutable `*-latest` labels. GitHub documents both as supported x64 hosted runners. Each selected action executes on Node 24 and requires Actions Runner 2.327.1 or later; current GitHub-hosted runners satisfy that requirement. `setup-python` installs the repository baseline Python 3.14.4 from GitHub's official `actions/python-versions` inventory when it is not already cached. `setup-node` installs Node 24.15.0, matching the locally validated major and the frontend's `>=22` requirement.

The newest stable releases were selected because they are signed, immutable upstream releases and include current dependency/security maintenance. Notable changes are:

- Checkout v7 uses Node 24/ES modules and adds protection against unsafe fork checkout in elevated event types. Workflows still avoid those event types and set `persist-credentials: false`.
- Setup Python v6 moved from Node 20 to Node 24. Version 6.3 adds platform/cache fixes; CI does not enable its cache.
- Setup Node v7 migrated to ES modules. Earlier major lines enabled package-manager caching behavior, so workflows explicitly set `package-manager-cache: false` to avoid cache poisoning and hidden state.
- Upload Artifact v7 produces immutable workflow artifacts. It is used only by the manual candidate workflow, with a fixed artifact name, approved files, five-day retention, and no hidden files. Version 4+ is not supported on GHES; this design targets GitHub-hosted Actions.

## Review and replacement

Review pins at least quarterly and immediately after an upstream security advisory, runtime deprecation, runner-image migration, or action deprecation. To replace a pin:

1. Confirm the owner remains exactly `actions` and the release is stable.
2. Review release notes, breaking changes, runtime, minimum runner, and security notices.
3. Verify the release and full tag/commit through at least two official observations.
4. Update this record and every workflow reference in one pull request.
5. Run workflow-structure tests and the complete local CI rehearsal.
6. Obtain human review before merging; never use an automated pin advance.

For a security incident, disable the affected workflow or artifact upload, preserve evidence, identify the last accepted pin, and require explicit human approval for replacement. Do not fall back to a mutable tag.
