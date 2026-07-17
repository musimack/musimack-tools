# ADR 0062: Metadata audit frontend workflow

Status: accepted

The authenticated frontend exposes `/audits`, `/audits/metadata`, creation, dashboard, pages, page detail, issues, duplicate groups, and duplicate detail. Creation requires `jobs.submit`; audit reading requires `runs.view`; exports retain artifact permissions. The client narrows exact states, severities, categories, issue codes, and formats at runtime, supports abort/timeout, and never retries mutations.

The UI renders server decisions only. It uses metric cards, definition lists, filter bars, semantic tables, text-bearing severity badges, breadcrumbs, loading/empty/error states, keyboard-reachable pagination, external-link labeling, responsive stacking, and reduced motion. It stores no token, embeds no bearer credential, uses no dangerous HTML, and exposes no filesystem path.
