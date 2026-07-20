# Combined Site Audit frontend interaction contract

Status: CSA-01 design contract; no production screen or route is implemented here.

## Information architecture

The future workspace adds, without replacing specialist navigation:

- **New Site Audit** — create and resume drafts.
- **Audit History** — site-oriented searchable audit/run history.
- **Saved Site Profiles** — selectable by all roles, managed only by administrators.
- **Global Audit Settings** — readable by authorized users, editable only by administrators.
- Result tabs: **Summary**, **Pages**, **Issues**, **Sitemap**, **Exclusions**, **Evidence**, and
  **Settings Snapshot**.

Technical audit/run/job IDs are secondary copyable information. Primary labels use site, seed,
date, lifecycle, and completeness. Existing Metadata, Sitemap, Link, Internal Links, Images and Alt
Text, Structured Data, and Migration QA entries remain.

## Wizard-wide behavior

Administrators and operators can create/edit/validate/preflight/submit. Viewers can read saved or
submitted content but cannot mutate or submit. Only administrators see profile-save or global-edit
controls. Authorization is enforced by the API as well as presentation.

Every successful edit persists a revisioned draft. Back/forward does not discard values. Refresh and
direct navigation restore `audit_id`, step, and draft revision from the stable route; secrets are
never placed in route state. Leaving with unsaved local edits prompts before loss. Changing any
validated field returns the draft to `draft` and visibly invalidates preflight. Reset affects the
current field/layer and previews the inherited value before confirmation.

Validation errors are associated with fields and summarized in a focusable error region. Service,
authorization, conflict, unavailable, partial, and recovery states have distinct messages and safe
retry behavior. Focus moves to step heading after navigation and to the error summary after failure.
All controls have accessible names, keyboard activation, visible focus, programmatic required/error
state, and non-color-only status. Desktop layouts may use columns; narrow layouts preserve content
order as one column with no horizontal page scrolling.

## Wizard steps

### 1. Website

- Required: seed URL. Optional: site label, approved additional hosts subject to authorization.
- Normalize for preview but display the exact supplied seed. Validate scheme/host and protected
  bounds without claiming network reachability.
- A chosen profile prepopulates only when its authorized site matches. Do not silently select the
  most recent unrelated site.

### 2. Platform and preset

- Show detected suggestion and confidence as advisory, including “Custom” and “No preset”.
- Show preset ID/version, all enabled/optional rules, explanations, exact tracking parameters, and
  `/wp-json/` as optional for WordPress.
- Require explicit acceptance before any preset rule or parameter strip becomes effective. Disabling
  a rule is independent and visible in effective settings.

### 3. URL governance

- Separate Discovery, Metadata scoring, Sitemap, and Parameter behavior panels.
- Add/edit/disable/delete initial string rules; there is no regex control.
- Test up to 100 samples and preview at most 500 retained matches. Show broad-rule, collision,
  conflict, and estimate-not-available states. Deletion of inherited rules means an explicit disabled
  reference, not loss of provenance.
- Show original and normalized example URLs, rule source, primary rule, contributors, and reason.

### 4. Crawl limits

- Select accepted crawl profile and bounded advanced overrides. Display requested, inherited,
  effective, and protected maximum values.
- Invalid, zero, negative, nonnumeric, or out-of-range values fail locally and at API validation.
  Blank means inherit; it never serializes a conflicting null override.

### 5. Audit modules

- Select combined modules and choose embedded evidence, linked eligible prior audit, or new child
  audit where supported. Show source run/site/date, evidence count, completeness, and freshness.
- Image and structured-data base summaries remain available from retained crawl evidence; deeper
  specialist results clearly say unavailable unless linked.

### 6. Thresholds

- Configure versioned issue thresholds and optional business importance for URL, family, page type,
  section, or profile. Explain that importance changes ordering, not factual severity.
- Reset exposes inherited threshold; ambiguous overlapping importance rules show resolution preview.

### 7. Review and submit

- Show seed/hosts, preset acceptance/version, effective rules and disabled inheritance, parameter
  transformations, exact crawl limits, modules/provenance, thresholds, importance, predicted bounds,
  warnings, and immutable snapshot notice.
- Validation and preflight must apply to this exact revision. Submit is disabled otherwise and uses
  an idempotency key. A successful submission routes to status; it never submits twice on refresh.

## Result behavior

Summary shows lifecycle separately from population and module completeness. Every metric labels its
denominator. Partial, skipped, failed, indeterminate, and unavailable evidence remains visible.
Specialist summary cards show source/provenance and stable internal links only when available.

Pages, Issues, Sitemap, Exclusions, Evidence, and Applied Rules use server pagination. Route query
retains filters, sort/order token, page size, and cursor/offset as appropriate. Filter changes reset
to the first page. Back from internal details restores the exact table state. Page choices are 50,
100, and 500. “All” appears only when filtered total is at most 5,000, requires explicit action, and
loads bounded pages progressively; otherwise the UI offers export. It never requests an unbounded
payload.

Internal detail routes are stable by audit run and durable item ID, support refresh/direct access,
and use the same authorization as their list. Any external URL is displayed exactly, restricted to
safe HTTP(S), opened separately with `target="_blank"` and `rel="noopener noreferrer"`, and never
replaces the app tab. No view exposes bodies, raw HTML, tokens, paths, or unsafe headers.

Artifacts show type/schema, completeness, rows/truncation, hash, lifecycle, expiry, and authenticated
download. Generation controls require operator/administrator permission; viewers may use authorized
existing downloads.

## State-specific presentation

| State                   | Required presentation/action                                                  |
| ----------------------- | ----------------------------------------------------------------------------- |
| Empty history           | Explain how an administrator/operator starts; viewer gets read-only absence.  |
| Draft/invalid           | Resume at first incomplete/error step; no results implied.                    |
| Queued/running          | Bounded polling, current stage, progress history, cancel if authorized.       |
| Cancel requested        | Disable duplicate cancel and explain retained evidence is provisional.        |
| Cancelled/failed        | Safe failure codes, retained evidence availability, rerun as new draft.       |
| Completed with warnings | Warning-complete lifecycle plus explicit coverage/module completeness.        |
| Partially completed     | Prominent partial labels on every summary/export and absent denominator data. |
| Recovery required       | No final exports; operator-visible recovery guidance without internals.       |
| Legacy/missing detail   | Explicit unavailable state, never an empty successful table.                  |

## Accessibility and responsive acceptance

The future CSA-05 implementation must test semantic landmarks/headings, fieldset/legend grouping,
label association, error announcement, table captions or accessible names, keyboard table/detail
actions, focus restoration, 200% zoom/reflow, status text independent of color, reduced motion, and
minimum usable touch targets. Dense tables provide a small-screen record layout without dropping
data or actions. Loading announcements are polite and do not repeatedly steal focus.
