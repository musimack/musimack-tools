# 0066: Sitemap audit product routes remain private and permission-aware

Status: implemented for review

The backend mounts twelve operations across ten paths only below `/api/internal/v1/audits/sitemaps` when the service is explicitly enabled and ready. Audit acceptance and execution are separate explicit requests so durable lifecycle polling is observable without a fire-and-forget task. The health-only default app does not mount them. Reads require `runs.view`; discovery, creation/execution, and export generation require `jobs.submit`; artifact downloads keep their existing permission check.

The React workspace adds a distinct Sitemap Audits navigation entry, creation/discovery form, status and summary dashboard, action/reason/URL filters, cursor pagination, inventories, findings, and export controls. Routes are authentication-protected, labels and table captions are explicit, and existing responsive behavior is reused. This is implementation status, not product acceptance or browser acceptance.
