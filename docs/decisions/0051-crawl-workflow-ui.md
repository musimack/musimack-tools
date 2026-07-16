# 0051: Crawl workflow UI

Status: Accepted for `seo-toolkit-crawl-workflow-ui-v1`.

## Decision

Provide one permission-gated, guided crawl form that emits only the existing application request
schema. Validation and preflight run before confirmation; submission remains explicit. Profiles,
scope, overrides, recommendation, and XML choices map directly to backend enums and bounds. The
browser does not accept publication roots or other server filesystem paths.

## Consequences

Operators can create bounded jobs without bypassing backend policy. Drafts remain only in React
memory and URLs contain filters and identifiers, never request bodies, credentials, or paths.
