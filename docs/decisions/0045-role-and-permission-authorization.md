# 0045: Role and permission authorization

Status: Accepted for `seo-toolkit-authorization-v1`.

## Decision

Define the exact administrator, operator, and viewer roles and their permissions in one immutable
code contract. Build one authenticated principal per request and authorize operations against a
central permission mapping. Unknown roles, permissions, and unclassified privilege input deny by
default.

## Consequences

Handlers do not compare role strings and callers cannot supply arbitrary privilege lists. The
legacy shared bearer maps explicitly to the administrator permission set for compatibility.
Per-resource ownership, custom roles, and deployment-setting mutation endpoints remain deferred.
