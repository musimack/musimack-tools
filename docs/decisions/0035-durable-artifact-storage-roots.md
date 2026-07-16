# ADR 0035: Explicit local artifact-storage roots

## Decision

Artifact storage is disabled by default. Enabled composition requires unique safe root IDs,
absolute non-overlapping local paths, and an explicit default root. Root paths remain runtime-only;
API diagnostics expose only IDs and safe readiness evidence. The managed layout is
`jobs/<job-id>/runs/<run-id>/artifacts/<filename>`.

All operations recheck containment, regular-file status, symlinks, and Windows junctions. There is
no current-directory, repository-relative, cloud, or import-time root creation fallback.

## Consequences

Published files can be registered without copying when their location already matches a configured
managed root. Moving legacy outputs and cloud storage are deferred.
