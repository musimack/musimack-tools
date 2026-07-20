# Combined Site Audit product contract

Status: CSA-01 product-owner review draft

Authority: `combined_site_audit_extended_sdr.md`, as resolved by the confirmed CSA-01 decisions

Implementation phases: CSA-02 through CSA-06

Published persistence baseline: `0015_sitemap_recommendation_retention`

This is the implementation contract for the first Combined Site Audit (CSA) release. It is design
only: it creates no route, table, worker, rule engine, or screen. Existing specialist audits remain
available and authoritative for their detailed evidence and exports.

Related contracts:

- [Conceptual private API](combined-site-audit-api-contract.md)
- [Frontend interaction contract](combined-site-audit-frontend-contract.md)
- [Phase ownership and traceability](combined-site-audit-phase-ownership.md)
- [SDR resolutions](combined-site-audit-sdr-resolution.md)
- [ADR 0075](decisions/0075-layered-url-governance-and-immutable-settings.md)
- [ADR 0076](decisions/0076-reproducible-populations-and-specialist-integration.md)
- [ADR 0077](decisions/0077-combined-audit-lifecycle-and-explainable-priority.md)

## 1. Scope and invariants

CSA is the primary operator-facing orchestration and reporting workflow. It supports WordPress,
Shopify, Squarespace, Wix, custom sites, no preset, and any other normal website type. Detection is
advisory; a preset is optional and never silently applied. Custom and no-preset paths provide the
complete core workflow.

Protected authentication, authorization, SSRF, DNS, redirect, host, scope, crawl, export, artifact,
and retention bounds cannot be weakened by a preset, profile, rule, or audit override. CSA never
writes to a target website. Existing specialist navigation and contracts coexist with CSA.

## 2. Repository authority map

CSA implementations must reuse rather than reinterpret these accepted boundaries:

| Concern          | Accepted authority                                                                                                         | Reuse and gap                                                                                                                                                                                                                |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Request flow     | `domain/application.py`, application validation/preflight/submission                                                       | Reuse profiles, effective limits, normalized seed, scope summary, and run identity; CSA-02 adds CSA settings contracts.                                                                                                      |
| Crawl and worker | `domain/run*.py`, `run/`, `jobs/`, durable worker composition                                                              | Reuse job/run/stage/cancellation/recovery semantics; CSA-04 composes them.                                                                                                                                                   |
| URL safety       | `crawl/normalization.py`, `scope.py`, `safety.py`, safe fetch and redirect contracts                                       | Reuse without bypass. Existing normalization does not implement CSA policy-based parameter stripping.                                                                                                                        |
| Page evidence    | durable crawl page, redirect, link, image, and structured-data evidence                                                    | Reuse requested/final URL, outcome, status, type, robots, canonical, metadata, depth, discoveries, warnings, failures, and evidence IDs. CSA-03 adds policy decisions and population membership, not duplicate raw evidence. |
| Sitemap          | recommendation projection/detail, `recommendation/sitemap.py`, sitemap XML and sitemap audit                               | Reuse include/exclude/review/indeterminate, determinacy, reasons, pagination, XML, comparisons, and artifact integrity. There is no accepted manual recommendation override.                                                 |
| Persistence      | durable job/run repositories, normalized specialist repositories, Alembic single-head convention                           | CSA-03 adds one later migration and repository abstractions. Restart reconciliation remains worker-owned.                                                                                                                    |
| Artifacts        | authenticated artifact repository/service, path safety, hashes, retention                                                  | Reuse bounded creation, authorization, expiry, deletion state, and downloads.                                                                                                                                                |
| Frontend         | workflow serializer, metadata run selector, cursor/offset tables, route-query filters, recommendation details, role guards | CSA-05 composes a wizard and CSA result routes without removing specialist routes.                                                                                                                                           |
| Authorization    | administrator/operator/viewer and centralized permissions                                                                  | Viewer reads; operator submits/cancels and applies audit overrides; administrator alone manages reusable profiles/defaults.                                                                                                  |

The current specialist APIs use stable private prefixes, authenticated error envelopes, bounded
cursor or offset pagination, immutable summaries, and artifact records. Technical run IDs remain
secondary implementation identifiers; future CSA selection is site/date/status oriented.

## 3. Glossary

| Term                 | Exact meaning                                                                                                                                                    |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Site Audit           | The CSA aggregate identified by a stable audit ID, containing drafts, submitted audit runs, snapshots, summaries, and artifact references for one governed site. |
| Audit draft          | Editable, durable configuration before submission; it is not evidence and cannot be reported as a run.                                                           |
| Audit run            | One immutable submitted execution of a Site Audit configuration snapshot.                                                                                        |
| Crawl job            | Durable scheduling and coordination record used to execute a crawl run.                                                                                          |
| Crawl run            | Accepted crawl lifecycle and retained crawl evidence associated with a deterministic run ID.                                                                     |
| Site profile         | Administrator-managed, versioned reusable settings for a named site and authorized seeds/hosts.                                                                  |
| Platform preset      | Versioned, optional suggested rules/settings for a platform; effective only after explicit acceptance.                                                           |
| Global default       | Administrator-managed versioned fallback below protected security policy.                                                                                        |
| Per-audit override   | Draft-only choice applied by an administrator or operator to that audit snapshot.                                                                                |
| Effective settings   | Deterministic merge of the protected boundary, defaults, accepted preset, profile, and audit overrides.                                                          |
| URL rule             | One versioned match/action/reason record.                                                                                                                        |
| Rule set             | Ordered rules from one source and version.                                                                                                                       |
| Rule snapshot        | Immutable submitted copy of every effective rule and disabled inherited rule.                                                                                    |
| Rule source          | `global`, `preset`, `site_profile`, or `per_audit`, including source identity/version.                                                                           |
| Rule match           | Retained evaluation linking an observed URL, rule snapshot, decision layer, outcome, and reason.                                                                 |
| Original URL         | Exact observed or user-supplied string before policy normalization.                                                                                              |
| Requested URL        | Safe normalized URL actually passed to the fetch boundary.                                                                                                       |
| Normalized URL       | URL identity after syntax normalization and explicitly accepted parameter policy.                                                                                |
| Final URL            | Terminal URL after accepted redirects, or absent when no terminal response exists.                                                                               |
| Discovered URL       | Actual URL observed from seed input, HTML, sitemap, robots, redirect, or canonical evidence.                                                                     |
| Enqueued URL         | Discovered URL admitted to the bounded crawl frontier.                                                                                                           |
| Fetched URL          | Enqueued request for which a fetch outcome, including a typed failure, was retained.                                                                             |
| Parsed HTML URL      | Fetched HTML with retained parser evidence, complete or explicitly partial.                                                                                      |
| Resource URL         | Non-page target such as an image, stylesheet, script, or document; not automatically a page.                                                                     |
| Scoring-eligible URL | Parsed HTML admitted to normal metadata-health denominators by the metadata decision.                                                                            |
| Sitemap-eligible URL | URL whose generated sitemap recommendation is `include`; `review` is not eligible yet.                                                                           |
| Indexable URL        | Evidence-supported page not prohibited by robots directives or another accepted indexability rule.                                                               |
| Canonical URL        | Page whose evaluated canonical identity is valid and non-conflicting; absence is separately visible.                                                             |
| Partial URL          | URL with useful retained evidence but an incomplete required observation.                                                                                        |
| Indeterminate URL    | URL for which evidence is insufficient to make a specified decision.                                                                                             |
| Issue finding        | Atomic versioned fact or policy result tied to evidence.                                                                                                         |
| Issue group          | Deterministic aggregation of findings sharing the defined grouping key.                                                                                          |
| Pattern candidate    | Cautious, evidence-backed suggestion of shared remediation leverage; never a claimed template identity.                                                          |
| Remediation task     | Explainable action derived from one or more issue groups.                                                                                                        |
| Business importance  | Manual `critical`, `high`, `medium`, `low`, or `not_assigned` context that affects priority, never factual severity.                                             |
| Specialist view      | Existing module-owned detail route for metadata, sitemaps, links, internal links, images, structured data, or migration QA.                                      |
| Child audit          | Specialist audit explicitly linked to and, in CSA-04, optionally launched by an audit run.                                                                       |
| Audit artifact       | Immutable, hashed, authenticated output associated with an audit run and schema version.                                                                         |

## 4. Lifecycle

### 4.1 States and transitions

| From                                                                   | To                                                                         | Actor/condition                                                                   |
| ---------------------------------------------------------------------- | -------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| new                                                                    | `draft`                                                                    | Administrator or operator creates a draft.                                        |
| `draft`, `validation_failed`, `preflight_failed`, `validated`, `ready` | `validating`                                                               | Editor requests validation; current draft revision is recorded.                   |
| `validating`                                                           | `validation_failed` or `validated`                                         | Service returns bounded field errors or accepts the revision.                     |
| `validated`                                                            | `draft`                                                                    | Editor changes configuration, invalidating validation.                            |
| `validated`                                                            | `preflighting`                                                             | Editor requests network preflight.                                                |
| `preflighting`                                                         | `preflight_failed` or `ready`                                              | Service records typed preflight result.                                           |
| `ready`                                                                | `draft`                                                                    | Editor changes configuration.                                                     |
| `ready`                                                                | `queued`                                                                   | Administrator/operator submits exactly the ready revision and immutable snapshot. |
| `queued`                                                               | `running`                                                                  | Durable worker claims the job.                                                    |
| `queued`, `running`                                                    | `cancel_requested`                                                         | Administrator/operator requests cancellation.                                     |
| `cancel_requested`                                                     | `cancelled`                                                                | Worker/queue safely acknowledges cancellation.                                    |
| `running`, `cancel_requested`                                          | `completed`, `completed_with_warnings`, `partially_completed`, or `failed` | Orchestrator reconciles required stages and retained evidence.                    |
| `running`                                                              | `recovery_required`                                                        | Lease/process recovery cannot proceed automatically without reconciliation.       |
| `recovery_required`                                                    | `queued` or `failed`                                                       | Authorized recovery retries safely or records a terminal failure.                 |

`cancelled`, `completed`, `completed_with_warnings`, `partially_completed`, and `failed` are
terminal. `recovery_required` is nonterminal and explicitly operator-visible. A retry/rerun creates
a new audit run and snapshot; it never rewrites the historical run.

### 4.2 Capabilities

- Draft-like states (`draft`, validation/preflight failures, `validated`, `ready`) permit editing.
- Only `ready` permits submission; validation and preflight apply to the same draft revision.
- `queued`, `running`, and `cancel_requested` permit cancellation subject to accepted job policy.
- Terminal states with retained data permit clearly labeled exports; `failed` permits only evidence
  that exists. `recovery_required` permits no final export.
- Site Audits and profiles are archived/disabled, not physically deleted while referenced.
- Child specialist status never silently defines parent status. Each module reports `complete`,
  `partial`, `unavailable`, `failed`, `stale`, or `not_enabled` independently.

### 4.3 Three independent completeness dimensions

1. **Run completion** describes orchestration: completed, warning-complete, partial, failed, etc.
2. **Population completeness** reports discovered/enqueued/fetched/parsed/skipped/failed coverage.
3. **Module completeness** describes whether each requested analysis had sufficient evidence.

A run with 25 discovered, 3 fetched, and 22 safely skipped may be
`completed_with_warnings`, while population coverage is partial and Metadata Audit is
`partial`. Skipped and indeterminate URLs are shown but do not enter the executive denominator.

## 5. Settings hierarchy and snapshots

| Order | Layer                         | Owner/edit permission                    | Persistence/versioning               | Override behavior                                                  |
| ----: | ----------------------------- | ---------------------------------------- | ------------------------------------ | ------------------------------------------------------------------ |
|     1 | Protected security boundaries | Product/security code; no user edit      | Accepted versioned configuration     | Cannot be weakened.                                                |
|     2 | Global defaults               | Administrator                            | Durable, versioned                   | Lower layers may narrow or choose within allowed ranges.           |
|     3 | Accepted platform preset      | Product defines; user explicitly accepts | Versioned definition plus acceptance | No silent application; optional rules individually disabled.       |
|     4 | Site profile                  | Administrator                            | Durable versioned profile            | May override defaults/preset within safe bounds.                   |
|     5 | Per-audit override            | Administrator/operator                   | Draft then immutable snapshot        | Applies only to one audit; cannot be saved as profile by operator. |
|     6 | Evidence-derived decisions    | Versioned analysis service               | Retained projection with provenance  | Facts/recommendations; not a settings override.                    |

Reset removes the current layer's value and reveals the next inherited value. Submission snapshots
effective settings, limits, approved hosts, preset ID/version/acceptance, all effective rules,
disabled inherited rule IDs, thresholds, modules, business-importance assignments, population and
issue definition versions, priority/projection/application versions, and artifact schema versions.

## 6. Platform presets and site profiles

A preset has stable ID, semantic version, supported platform, detection suggestion evidence,
acceptance state, rules with default/optional enablement, explanations, the exact tracking-parameter
list, and upgrade notes. WordPress `/wp-json/` is optional and never auto-excluded. Applicable
presets default tag, author, and date archives to crawl for evidence as needed, exclude from normal
metadata scoring, and exclude from sitemap; each decision is separately disableable. Pagination is
not excluded from metadata scoring by default.

Existing profiles remain pinned to the accepted preset version. A newer preset creates an
administrator-reviewed upgrade proposal; it does not mutate the profile or historical audits.

A site profile contains stable ID, label, authorized seeds, approved hosts, preset association,
site rules and parameter exceptions, crawl limits, thresholds, enabled modules, business-importance
assignments, creator, version, enabled/archived state, and audit references. Administrators alone
create, edit, disable, archive, or upgrade it. Operators select approved profiles and apply audit
overrides. “Delete” means archive while any audit references the profile.

## 7. URL governance

### 7.1 Independent decisions

- **Discovery:** `enqueue`, `exclude_from_discovery`, `mark_review_before_enqueue`. The review state
  is a nonblocking enqueue-with-review marker in the first release, not a queue requiring separate
  human approval.
- **Metadata scoring:** `include_in_metadata_scoring`, `exclude_from_metadata_scoring`,
  `indeterminate_for_metadata_scoring`.
- **Sitemap:** generated `include`, `exclude`, `review`, or `indeterminate`.

User sitemap rules contribute explicit policy evidence to the versioned recommendation; they do
not overwrite observed evidence or a generated recommendation. A future manual final override is
deferred. The result retains user policy, observations, recommendation, primary reason, and all
contributors separately.

### 7.2 Rule fields and bounds

Every rule has stable rule ID; name; description; enabled flag; match type/value; case-sensitivity
flag where allowed; action; explanation; reason code; source identity/version; integer priority;
decision scope; explicit `overrides_rule_ids`; creator and timestamps; version; preset/profile
association; and submitted snapshot association. An override target must name an inherited rule in a
lower source and the same decision layer; unknown, same-source, cyclic, or cross-layer targets are
validation errors.

| Bound                  |            Value | Reason                                                                   |
| ---------------------- | ---------------: | ------------------------------------------------------------------------ |
| Rules per source       |              500 | Supports large governance sets while bounding validation and evaluation. |
| Name                   |   128 characters | Human label, not content storage.                                        |
| Match value            | 2,048 characters | Covers valid URLs within accepted request bounds.                        |
| Explanation            | 1,000 characters | Sufficient auditable rationale without becoming a document store.        |
| Preview sample input   |         100 URLs | Interactive deterministic testing, not a crawl.                          |
| Preview matched output |         500 rows | Useful bounded evidence without unbounded browser payloads.              |

Broad rules require a warning and explicit confirmation. Preview estimates use retained evidence
only and never become discovery evidence.

### 7.3 Match semantics

All rule inputs reject credentials, fragments, control characters, unsafe schemes, and invalid
percent encoding. Fragments are removed before matching. Hosts use IDNA/ASCII normalization,
case-folding, and default-port removal. URL rules are limited to approved hosts but cannot approve
a host. Percent-encoded unreserved characters normalize to their literal form; reserved characters
are not decoded into different path structure. Query ordering does not affect query match types.

| Match type               | Operand and semantics                                                                                                                     | Stage                                                                |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| `exact_url`              | Absolute original syntax-normalized URL, including normalized host/path and canonical query ordering; trailing slash remains significant. | Before fetch; may be reevaluated on final URL for post-fetch layers. |
| `exact_path`             | Normalized path, beginning `/`; trailing slash significant. Host ignored after approved-host check.                                       | Before and after fetch.                                              |
| `path_starts_with`       | Code-point prefix over normalized path.                                                                                                   | Before and after fetch.                                              |
| `path_contains`          | Contiguous code-point substring over normalized path.                                                                                     | Before and after fetch.                                              |
| `path_ends_with`         | Code-point suffix over normalized path.                                                                                                   | Before and after fetch.                                              |
| `query_parameter_exists` | Parameter name occurs at least once; an empty value counts as existing. Names are case-sensitive by default.                              | Before fetch on original syntax-normalized URL.                      |
| `query_parameter_equals` | At least one repeated occurrence has the exact normalized value; empty is allowed explicitly.                                             | Before fetch on original syntax-normalized URL.                      |

Path match types are case-sensitive by default; an explicit flag may request Unicode case-folded
comparison. Exact URL is case-insensitive only for scheme/host. Query rules can explicitly request
case-insensitive name/value matching. Repeated values are retained in order for evidence. Path
matching happens before parameter stripping because stripping does not change paths; query rules
evaluate the original syntax-normalized query. The normalized URL is then available to post-fetch
decisions. No regex or ambiguous “pattern” match exists in the initial contract.

### 7.4 Initial actions

| Action                                    | Decision layer and exact effect                                                                                                                                         |
| ----------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `exclude_from_discovery`                  | Discovery is `exclude_from_discovery`; later layers have no page evidence unless other evidence already exists.                                                         |
| `crawl_but_exclude_from_metadata_scoring` | Discovery is `enqueue`; metadata scoring is `exclude_from_metadata_scoring`; sitemap remains evidence-derived.                                                          |
| `crawl_but_exclude_from_sitemap`          | Discovery is `enqueue`; metadata scoring remains evidence-derived; explicit sitemap-exclude policy contributes to the generated recommendation.                         |
| `crawl_and_mark_for_review`               | Discovery is nonblocking `mark_review_before_enqueue`; metadata remains evidence-derived; sitemap receives review policy evidence only when the rule scope includes it. |
| `strip_query_parameter`                   | Normalization removes the named parameter before dedup/frontier/fetch; it does not directly decide discovery, metadata-scoring, or sitemap state.                       |

`normalize_to_parameterless_url` is deferred because indiscriminate removal risks functional URLs;
explicit parameter stripping covers the safe use case. `retain_as_resource_only` is deferred because
resource classification should be evidence-derived. `ignore_issue_category` is deferred to issue
policy design and is not URL governance.

### 7.5 Deterministic precedence

1. Enforce security, approved-host, scope, DNS, redirect, and absolute limits first.
2. Evaluate original-query normalization rules and exceptions; retain original and normalized forms.
3. Evaluate each decision layer independently. Source precedence is global < accepted preset < site
   profile < per-audit, but precedence authorizes replacement only through an explicit inherited
   stable rule ID.
4. A higher source may explicitly disable/replace a named inherited stable rule ID. An explicitly
   targeted enabled replacement becomes primary; the replaced rule remains a contributor marked
   overridden. Similar match text never implicitly shadows another rule.
5. Within one source, higher explicit integer priority wins. Then specificity orders:
   `exact_url`, `exact_path`, `query_parameter_equals`, `query_parameter_exists`,
   `path_starts_with`/`path_ends_with`, `path_contains`. Stable rule ID is the final ordering key.
6. Same-decision conflicts without an explicit override—including overlap across sources—yield a
   visible conflict and `review`/`indeterminate`, not an automatic “most restrictive wins”. When
   nonconflicting rules agree, the highest source, priority, specificity, and stable ID determine
   the primary explanation while all matches remain contributors.
7. Rules affecting different layers accumulate. Retain primary and contributing matches.
8. Evidence-derived analysis runs after policy and keeps policy distinct from facts.

## 8. Parameter governance

After explicit preset acceptance, these names default to stripping:
`utm_source`, `utm_medium`, `utm_campaign`, `utm_term`, `utm_content`, `gclid`, `fbclid`, and
`msclkid`. The review shows the exact list. A site exception names the functional parameter and has
higher-layer precedence.

All occurrences of an accepted stripped name, including empty/repeated occurrences, are removed.
Remaining pairs preserve multiplicity and are serialized in deterministic name/value order for
identity. The original discovery and ordered query, normalized request, applied rule, and collisions
are retained. Deduplication uses the normalized identity. Only that normalized URL enters the
frontier and fetch boundary; stripped variants remain discoveries and are not separately fetched.
A collision groups all originals and reports the chosen deterministic requested identity.

Canonical evidence is observed independently: it neither retroactively changes the request nor
hides a collision. Sitemap and metadata decisions evaluate the retained normalized identity and
show original variants. No parameter policy can bypass safe URL validation.

## 9. Discovery evidence

Durable discoveries come only from a user seed, fetched HTML link, existing sitemap entry, robots
sitemap directive, redirect target, or canonical target. Approved hosts are configuration, not
discoveries. Samples, previews, estimates, and hypothetical matches never become discoveries.

Every excluded discovery retains original and normalized URL; source kind; source page/artifact or
user-input reference; matched rule snapshot and source; decision and reason; observed timestamp;
and explicit enqueued/fetched flags. Sitemap discovery occurs during crawl discovery after robots
is available and within the submitted time/URL/byte limits. User-supplied sitemaps are considered
before robots directives, then common-location discovery, with deterministic order. Sitemap-only
URLs are discoveries and may join the frontier only if scope/safety/rules allow and shared crawl
limits have capacity; they receive no separate quota or safety path.

## 10. Populations and denominators

Population memberships are nonexclusive, retained, versioned projections. Counts use normalized
URL identity; collision groups additionally expose original-discovery counts. Redirect sources and
final targets remain separate observed identities. Canonical targets do not collapse page evidence.

| Population                | Inclusion                                                         | Important exclusion/handling                                                             |
| ------------------------- | ----------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| Discovered                | Actual discovery record                                           | Preview/estimate excluded.                                                               |
| Enqueued                  | Frontier admission retained                                       | Discovery exclusion and capacity skip excluded.                                          |
| Fetched                   | Retained fetch attempt/outcome                                    | Never-attempted excluded; typed failures included in fetched and failed.                 |
| Parsed HTML               | Retained HTML parse evidence                                      | Non-HTML excluded; partial parse is included and marked partial.                         |
| Indexable                 | Parsed HTML with affirmative indexability                         | Conflict/missing required evidence is indeterminate.                                     |
| Canonical                 | Valid non-conflicting canonical identity under definition version | Missing/conflicting canonical shown separately.                                          |
| Metadata-scoring-eligible | Parsed HTML + indexable + canonical + policy include              | Partial/indeterminate/excluded omitted from denominator. Pagination included by default. |
| Sitemap-eligible          | Generated recommendation `include`                                | `review`, `exclude`, `indeterminate` omitted.                                            |
| Resource                  | Observed non-page resource evidence                               | Not automatically a page population member.                                              |
| Excluded                  | Any explicit policy exclusion, labeled by layer                   | Can overlap fetched/parsed when scoring/sitemap-only exclusion.                          |
| Partial                   | Useful but incomplete required evidence                           | May overlap parsed/fetched.                                                              |
| Failed                    | Typed fetch or required module failure                            | Failure evidence retained.                                                               |
| Indeterminate             | Insufficient evidence for a named decision                        | Decision-specific; never silently counted as eligible.                                   |

The executive metadata-health denominator is exactly **indexable, canonical,
metadata-scoring-eligible HTML pages**. Reports also label discovered, enqueued, fetched, parsed,
indexable, canonical, scoring-eligible, sitemap-eligible, excluded, partial, failed, and
indeterminate counts. Unfetched sitemap-only URLs can be discovered/enqueued/skipped but cannot
enter parsed or scoring populations.

## 11. Sitemap contract

Pagination defaults to `review` for sitemap purposes—not default include or exclude. Canonical,
indexability, content uniqueness, existing sitemap membership, and explicit site policy determine
the generated recommendation. This preserves potentially valid series pages without polluting XML
automatically. Pagination remains metadata-scoring eligible by default.

Existing sitemap comparison states and include/exclude/review/indeterminate recommendation concepts
are reused. User policy is evidence, not a hidden final override. Only `include` enters recommended
XML. Generation uses stable normalized URL ordering, accepted XML limits/splitting, authenticated
hashed artifacts, and explicit partial labels. An empty eligible set yields an explicit empty-result
state, not a misleading published sitemap. Publication is disabled by default. Manual final
override is deferred. CSA-01 changes none of the current production sitemap behavior.

## 12. Issues, patterns, remediation, and priority

An atomic finding retains code/category, definition version, evidence ID, URL, factual severity,
confidence, determinacy, explanation, and impacts. An issue group key is
`(definition_version, issue_code, normalized remediation key, applicable population)` and retains
affected count, bounded samples, a complete paginated membership reference, highest severity,
business-importance distribution, sitemap/metadata/indexability impact, confidence range,
determinacy distribution, and suggested action.

A pattern candidate requires at least three affected URLs and one retained shared structural
signal (for example path family or common source evidence). It is labeled candidate with confidence;
URL similarity alone cannot claim a shared template. A remediation task references source groups,
keeps their evidence, and never erases individual findings.

Priority is an explainable lexicographic tuple, not an opaque score:

1. protected security finding flag;
2. factual severity (`critical`, `high`, `medium`, `low`, `informational`);
3. highest manual business importance (`critical`, `high`, `medium`, `low`, `not_assigned`);
4. indexability, sitemap, and internal-link impact flags in that order;
5. affected URL count (descending);
6. pattern leverage (`confirmed evidence`, `candidate`, `none`);
7. confidence (`high`, `medium`, `low`), then determinacy (`determinate`, `indeterminate`);
8. stable issue code and group ID.

Missing importance is `not_assigned`; missing impact is false but visibly unknown if evidence is
absent. Business importance raises ordering only within factual constraints and never changes
severity, security, or evidence. Manual final-priority override and numeric weights are deferred.
Every displayed priority includes the tuple inputs and priority-model version.

## 13. Specialist integration

| Specialist          | Source of truth / first-release mode                                               | CSA behavior                                                                                                       |
| ------------------- | ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Metadata Audit      | Durable crawl page evidence plus linked child or eligible prior audit              | CSA core may embed bounded metadata facts; specialist owns detail/groups/exports.                                  |
| Sitemap Audit       | Specialist documents/entries/comparisons                                           | Link child/eligible prior audit; CSA recommendation remains provenance-aware.                                      |
| Link Audit          | Retained source links and specialist derived targets/chains                        | Summary/link only; no duplicate graph.                                                                             |
| Internal Links      | Specialist durable internal graph                                                  | Summary/link only.                                                                                                 |
| Images and Alt Text | Existing retained image occurrences; optional linked eligible audit                | Base counts from crawl evidence; high-priority specialist findings only when linked, otherwise detail unavailable. |
| Structured Data     | Existing retained inert structured blocks/entities; optional linked eligible audit | Base counts from crawl evidence; high-priority specialist findings only when linked, otherwise detail unavailable. |
| Migration QA        | Explicit project/source/destination evidence                                       | Optional linked audit only; never automatically launched for ordinary CSA.                                         |

CSA-04 owns optional child execution. A child records audit ID, source run/evidence versions,
requested module, status, freshness, and timestamps. Parent status uses the independent completeness
model; an optional child failure yields a module failure and parent warning/partial state, not
automatic parent failure. Eligible prior audits must match run/evidence identity and configuration,
and are labeled stale rather than silently reused after divergence. Each specialist owns its
exports and deep route. Rerun creates a new child link.

## 14. Bounded listing and retention

- API page size: default 50; accepted choices 50, 100, 500; hard maximum 500.
- Interactive listing: “All” means explicit client accumulation of all filtered rows only when the
  server-reported total is at most 5,000, fetched through bounded pages. Otherwise export is offered.
- Export rows: maximum 100,000 per tabular artifact, with truncation metadata if applicable.
- Total retained URL identities per audit run: maximum 100,000.
- Rule-preview matches: maximum 500.

No endpoint or browser request uses an unbounded `All`. Stable sequence/keyset ordering is required;
filters reset the cursor/offset and remain in the route query.

## 15. Artifact contract

All artifacts use authenticated artifact infrastructure, `artifacts.view`/`artifacts.download`,
safe paths, SHA-256, audit/run association, creation/expiry/deletion lifecycle, stable schemas, and
partial/truncation labels.

| Artifact               | Filename                                     | Type               | Source and maximum                                               |
| ---------------------- | -------------------------------------------- | ------------------ | ---------------------------------------------------------------- |
| Executive Markdown     | `site-audit-executive.md`                    | `text/markdown`    | Summary/groups; bounded narrative.                               |
| Full page inventory    | `site-audit-pages.csv`                       | `text/csv`         | Population projection; 100,000 rows.                             |
| Full evidence          | `site-audit-evidence.json`                   | `application/json` | Safe retained projections only; 100,000 URLs; no bodies/secrets. |
| Grouped issues         | `site-audit-issues.csv`                      | `text/csv`         | Issue groups; 100,000 rows.                                      |
| Sitemap comparison     | `site-audit-sitemap-comparison.csv`          | `text/csv`         | Comparison projection; 100,000 rows.                             |
| Excluded URLs          | `site-audit-exclusions.csv`                  | `text/csv`         | Decisions/rules; 100,000 rows.                                   |
| Applied rules          | `site-audit-applied-rules.csv`               | `text/csv`         | Rule matches; 100,000 rows.                                      |
| Recommended sitemap    | `site-audit-sitemap.xml` (split if required) | `application/xml`  | Generated includes; accepted XML document limits.                |
| Action plan            | `site-audit-action-plan.csv`                 | `text/csv`         | Ordered remediation tasks; 100,000 rows.                         |
| Configuration snapshot | `site-audit-configuration.json`              | `application/json` | Complete immutable submitted snapshot; bounded rules/settings.   |

CSV stable order is retained sequence then stable ID; JSON uses documented key order/version; XML
uses normalized URL order. Every artifact declares `site-audit-*-v1` schema (specific name per
artifact), projection version, completeness, generated timestamp, and source snapshot hash.

## 16. Historical immutability

Submitted audit data is append-only from the product perspective. Defaults, presets, profiles,
rules, definitions, projections, and artifact schemas are referenced by immutable version and
snapshotted where required for interpretation. Reanalysis under new definitions creates a new audit
run/projection, never changes historical counts or priority. Historical links continue to resolve
to the recorded specialist audit or an explicit unavailable/expired state.

## 17. Deferred work

Regex, arbitrary script/pattern execution, manual final sitemap override, manual priority override,
numeric priority weights, indiscriminate parameterless normalization, resource-only user rules, and
issue-category ignore rules are not first-release requirements. They require later security and
product decisions and must not appear as latent production options.
