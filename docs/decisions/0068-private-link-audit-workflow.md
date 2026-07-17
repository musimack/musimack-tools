# ADR 0068: Private durable link-audit workflow

Status: implemented for review

Link analysis is a durable, network-free derived audit over one selected terminal run. Normalized targets, ordered redirect chains, findings, recommendations, lifecycle events, and artifact references are persisted under migration `0009_broken_link_redirect_analysis`.

The API exists only below `/api/internal/v1/audits/links`, uses existing authentication and permissions, and exposes deterministic bounded queries. The React **Link Audits** workspace is protected by the same permissions. Export bytes use the existing artifact authority; no direct filesystem route is added. Results are suggestions for human review and never modify a website.
