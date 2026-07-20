# Combined Site Audit settings and URL governance

CSA-02 implements the bounded configuration authority defined by CSA-01. It does not create or run
a Combined Site Audit. The implementation is deliberately network-free and is not connected to the
production crawl frontier.

## Ownership and composition

- `domain/site_audit_settings.py` owns immutable settings, built-in presets, profile validation,
  URL normalization, rule matching, independent decision layers, precedence, conflicts, parameter
  stripping, and collision projections.
- `site_audit_settings/service.py` resolves global defaults, an explicitly accepted versioned
  preset, an enabled site profile, and stateless per-audit overrides.
- `persistence/site_audit_settings_*` stores append-only global-setting versions and versioned site
  profile configurations. Built-in presets are deterministic code definitions, so a profile pins
  their stable ID and version without allowing user mutation of the definitions.
- Private routes are opt-in under `/api/internal/v1/site-audits`. The default application remains
  `/api/health` only, and there is no public alias.
- The protected `/settings` workspace route is the bounded Site Audit Settings surface. Operators
  can review presets and enabled profiles, resolve temporary settings, and test samples.
  Administrators additionally manage global settings and reusable profiles. Viewers are denied.

Revision `0016_site_audit_settings` follows `0015_sitemap_recommendation_retention` and creates only
`site_audit_global_settings_versions`, `site_audit_profiles`, and
`site_audit_profile_versions`. There is no CSA audit aggregate, URL inventory, audit rule snapshot,
match-evidence record, orchestration record, issue record, or combined artifact in this phase.

## Presets and explicit acceptance

The built-in catalog contains WordPress, Shopify, Squarespace, Wix, Custom, and No preset. Each has
a stable version. Selecting or suggesting a preset does not apply it. The effective-settings request
must explicitly send its ID, version, and acceptance state. Profile configurations retain the
accepted version. A later built-in version does not rewrite an existing profile.

The WordPress definition visibly includes default discovery exclusions for `/wp-admin/`,
`/wp-login.php`, `/xmlrpc.php`, and `/cdn-cgi/`. `/wp-json/`, feeds, search, attachment pages, and
comment-reply routes are optional and disabled by default. Tag, author, and date archives have
independent metadata and sitemap exclusions. Pagination remains metadata eligible and contributes
only a sitemap Review policy. Categories are not excluded automatically.

The initial tracking list is exactly `utm_source`, `utm_medium`, `utm_campaign`, `utm_term`,
`utm_content`, `gclid`, `fbclid`, and `msclkid`. Stripping occurs only after explicit preset
acceptance. A profile or temporary request may retain named functional parameters as exceptions.

## Safe rule model

The only match types are `exact_url`, `exact_path`, `path_starts_with`, `path_contains`,
`path_ends_with`, `query_parameter_exists`, and `query_parameter_equals`. The only actions are
`exclude_from_discovery`, `crawl_but_exclude_from_metadata_scoring`,
`crawl_but_exclude_from_sitemap`, `crawl_and_mark_for_review`, and `strip_query_parameter`.
There is no regex, wildcard, executable pattern, network lookup, or live-site preview.

Scheme and host normalization reuse the accepted URL authority. Hosts use lower-case IDNA form,
default ports are removed, fragments are ignored, unreserved percent escapes are decoded, reserved
escapes retain structure, query identity is deterministic, empty and repeated values are retained,
and trailing slashes and path case remain significant. Exact URL matching includes canonical query
ordering. Query match operations inspect the syntax-normalized original before parameter stripping.

Rules resolve by protected boundary, global, accepted preset, site profile, and per-audit source.
A higher source replaces a lower rule only with an explicit inherited `overrides_rule_ids` target in
the same decision layer. Overlapping outcomes without an explicit override remain a visible conflict;
the implementation does not use “most restrictive wins” or “last rule wins.” Discovery, metadata,
sitemap, and normalization decisions resolve independently, retaining primary and contributing rules.

## Bounds

| Input or projection | Bound |
| --- | ---: |
| Rules per source | 500 |
| Rule name | 128 characters |
| Match value | 2,048 characters |
| Description / reason | 1,000 characters |
| Explicit override IDs per rule | 100 |
| Sample URLs per test | 100 |
| Retained-evidence preview results | 500 |
| API page size | 500 |
| Browser bounded All | 5,000 |
| Retained/exported audit URLs | 100,000 |

Profile crawl overrides are limited by the unchanged application hard maxima. Settings can never
relax SSRF, DNS, redirect, authentication, authorization, approved-host, artifact, export, or crawl
hard boundaries.

## Private operations and deferred retained preview

Administrators use `settings.manage` for global reads/writes and reusable-profile mutations/version
history. Administrators and operators use `jobs.submit` for preset/profile selection, effective
settings, rule validation, and sample testing. Viewers have no CSA-02 management access.

Sample testing returns original and normalized URLs, matches, decisions, primary and contributing
rules, conflicts, collision groups, and validation warnings. It reports `network_access: false` and
`discoveries_created: false`. Stateless preview requests do not create a draft or audit.

Retained-evidence rule preview is explicitly deferred. CSA-02 cannot provide the required
operator-friendly eligible-evidence selector without leaking CSA-03 aggregate ownership or CSA-05
wizard work. `/rule-previews` therefore returns `site_audit_rule_preview_deferred` rather than
accepting an internal ID or pretending an empty preview succeeded.
