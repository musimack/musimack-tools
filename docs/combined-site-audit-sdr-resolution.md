# Combined Site Audit SDR resolution record

The named `combined_site_audit_extended_sdr.md` remains product direction. This repository contract,
together with confirmed CSA-01 decisions, resolves its inconsistent or stale statements. No
production behavior changes in CSA-01.

| SDR location                        | Conflict or ambiguity                                             | Authoritative resolution                                                                                                                    | Contract location                          |
| ----------------------------------- | ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------ |
| Sections 23 and baseline references | Describes `0013` as published and `0015` as unpublished.          | Published single head is `0015_sitemap_recommendation_retention`; no CSA-01 migration.                                                      | Product contract header and repository map |
| 5.2, 8.1 scoring exclusions         | Pagination appears as default metadata-scoring exclusion.         | Pagination is audited and scoring-eligible by default; site policy may exclude it with visible evidence.                                    | Product contract §§6, 10                   |
| 5.3, 8.1 sitemap exclusions         | Metadata decision is conflated with sitemap eligibility.          | Pagination defaults to sitemap `review`, resolved using policy plus canonical/indexability/content evidence.                                | Product contract §11                       |
| 6.2, 17.2                           | Operator may save reusable profiles if authorized.                | Only administrators manage reusable profiles; operators select and override per audit.                                                      | Product contract §§5–6; API contract       |
| 9.2 and rule examples               | Regex/pattern matching appears initial.                           | Initial match types are seven safe string/query operations; regex is deferred.                                                              | Product contract §7.3                      |
| 8.1 WordPress rules                 | `/wp-json/` may be treated as automatic exclusion.                | It is optional, with effect explained, and never auto-excluded.                                                                             | Product contract §6                        |
| 10                                  | Parameter removal timing and fetch identity are ambiguous.        | Explicit preset acceptance; query rules inspect original; accepted names strip before dedup/frontier/fetch; originals/collisions remain.    | Product contract §8                        |
| 12.4, 22                            | “All”, 50,000, and 100,000 are mixed.                             | API page max 500; browser All max 5,000 via pages; export/retained max 100,000; preview max 500.                                            | Product contract §14                       |
| 14.1                                | Existing sitemap discovery timing/frontier behavior is not exact. | Deterministic user/robots/common discovery; sitemap-only observations enter shared frontier only under safety/scope/rules/shared limits.    | Product contract §§9, 11                   |
| 13.3                                | Priority resembles an unspecified combined score.                 | Versioned explainable lexicographic tuple; importance cannot change facts/security.                                                         | Product contract §12; ADR 0077             |
| 16, image/schema summaries          | Source and launch behavior are unresolved.                        | Base counts use retained crawl evidence; specialist findings require linked child/eligible prior audit, else unavailable.                   | Product contract §13; ADR 0076             |
| 11, lifecycle/reporting             | Run, population, and module partial states are conflated.         | Report three independent completeness dimensions and immutable lifecycle.                                                                   | Product contract §4; ADR 0077              |
| 27–28                               | Product-owner questions remain open in the SDR.                   | Confirmed assignment decisions and this record close first-release contract questions; future-only capabilities remain explicitly deferred. | Product contract §17                       |

## Deliberate first-release decisions

- User sitemap rules are policy evidence; generated recommendation remains distinct. Manual final
  overrides are deferred.
- `normalize_to_parameterless_url`, `retain_as_resource_only`, and `ignore_issue_category` are
  deferred for the safety/ownership reasons in the product contract.
- Tracking stripping affects request identity as well as dedup only after explicit acceptance and
  site-specific functional exceptions.
- Site profile deletion is archive/disable when referenced.
- No unresolved product decision blocks CSA-02. Later phases may refine storage or presentation
  mechanics only if they preserve these externally visible semantics.
