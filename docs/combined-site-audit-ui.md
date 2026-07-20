# Combined Site Audit UI

CSA-05 is the authenticated operator interface for the accepted Combined Site Audit contracts.
It adds presentation and narrow private draft/read endpoints; it does not change URL governance,
SSRF controls, durable execution, specialist ownership, or persistence schema.

## Navigation and roles

`/site-audits` is Audit History. Operators and administrators also see New Site Audit and Saved
Site Profiles; only administrators see Global Audit Settings and administrative recovery/archive
actions. Viewers can inspect history, lifecycle, results, details, and authorized artifacts but
cannot mutate an audit. Anonymous users are handled by the existing sign-in guard.
Administrators can reconcile audits in `recovery_required` directly from the lifecycle view.

## Wizard

The seven steps are Website, Platform and Preset, URL Governance, Crawl Limits, Audit Modules,
Thresholds, and Review and Submit. The audit ID and step are addressable in the route. Each save
uses the current durable revision, and unsaved browser edits trigger the standard leave warning.
Validation and preflight run against the same saved draft. Submit is enabled only for `ready` and
requires confirmation; the resulting snapshot is immutable.

## Lifecycle and results

Lifecycle pages poll only queued or running audits and show explicit partial, unavailable, failed,
cancelled, and warning-complete states. Completed results have Summary, Pages, Issues, Sitemap,
Exclusions, Evidence, Settings Snapshot, and Artifacts tabs. Page and issue rows open internal
detail routes first. Safe HTTP(S) source links are separate new-tab actions.

Sitemap, Exclusions, Evidence, Settings Snapshot, and Artifacts are purpose-built result views,
not generic JSON renderers. Governance rows identify the effective rule and bounded contributing
rules. Settings are labeled immutable submitted values. Artifact downloads use the authenticated
artifact route and never expose a filesystem path.

Page sizes are 50, 100, and 500. The browser All option requests repeated 500-row pages and stops
at 5,000. Query parameters retain offsets and page size across refresh and detail-return links.
Tables never request an unbounded API response.

## Safety, accessibility, and responsive behavior

Safe projections redact body, raw-HTML, secret, token, password, and local-path shaped keys.
External links reject non-HTTP(S) schemes and use `noopener noreferrer`. The UI uses semantic
landmarks, labelled inputs, keyboard-native actions, visible focus from the shared design system,
live pagination text, and status labels independent of color. Seven-step navigation and dense
grids collapse at tablet and phone widths; reduced-motion preferences remain honored.

## Deferred acceptance

CSA-06 retains ownership of an explicitly authorized, bounded real-website acceptance crawl.
CSA-05 must not submit a public-network crawl. Remaining limits are recorded in
`docs/known-limitations.md`.
