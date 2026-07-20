# Combined Site Audit phase ownership and traceability

This matrix prevents CSA-01 design approval from authorizing implementation. Each later phase needs
its own assignment and human gate.

## Phase ownership

| Capability                                             | CSA-01                | CSA-02                                          | CSA-03                                     | CSA-04                                                    | CSA-05                                                     | CSA-06                    | Deferred                |
| ------------------------------------------------------ | --------------------- | ----------------------------------------------- | ------------------------------------------ | --------------------------------------------------------- | ---------------------------------------------------------- | ------------------------- | ----------------------- |
| Terminology, lifecycle, populations, priority contract | Define                | Conform                                         | Persist versions                           | Project                                                   | Present                                                    | Acceptance                | —                       |
| Global settings and site profiles                      | Define                | Domain/service/API implementation               | Persist references as needed by owned plan | Consume snapshots                                         | Management/selection UI                                    | Security/real-site QA     | —                       |
| Presets, rules, preview, parameter governance          | Define semantics      | Implement bounded rule engine and contracts     | Persist definitions/snapshots/matches      | Apply in crawl/orchestration                              | Wizard/preview UI                                          | Collision/safety QA       | Regex                   |
| CSA audit/run persistence                              | Define entities       | Provide settings inputs only                    | Migration, models, repositories, retention | Consume                                                   | Consume                                                    | Backup/recovery QA        | —                       |
| Crawl and specialist orchestration                     | Define integration    | No orchestration                                | Persist links/status                       | Durable parent/child execution, recovery, priority/groups | Status/results UI                                          | Real-site hardening       | Automatic schedules     |
| Combined UI/navigation                                 | Define interaction    | No production CSA wizard                        | No production UI                           | API-ready projections                                     | Implement wizard/history/results while specialists coexist | Browser/accessibility QA  | —                       |
| Artifacts                                              | Define schemas/bounds | —                                               | Persist artifact associations              | Generate safely                                           | List/download                                              | Integrity/large-result QA | Additional formats      |
| Sitemap manual final override                          | Distinguish/defer     | —                                               | —                                          | —                                                         | —                                                          | —                         | Product/security design |
| Numeric/manual priority override                       | Explain/defer         | —                                               | —                                          | —                                                         | —                                                          | —                         | Product design          |
| Production migrations                                  | Prohibited            | Only if separately authorized for settings plan | First CSA aggregate migration              | Only necessary incremental migration                      | Avoid                                                      | Avoid                     | —                       |

## Confirmed-decision traceability

| Decision                                            | Contract implementation                                 |
| --------------------------------------------------- | ------------------------------------------------------- |
| Any normal website; detection optional              | Product contract §§1, 6; frontend step 2                |
| `/wp-json/` optional                                | Product contract §6; frontend step 2                    |
| Pagination included in metadata scoring by default  | Product contract §§6, 10; SDR resolution                |
| Pagination sitemap treatment                        | Product contract §11: default `review`                  |
| Tag/author/date archive defaults                    | Product contract §6                                     |
| Explicit accepted tracking stripping and collisions | Product contract §8; frontend step 3                    |
| Administrator-only reusable profiles                | Product contract §§5–6; API permissions; frontend roles |
| Executive denominator and all supporting counts     | Product contract §10; frontend Summary                  |
| Transparent business importance                     | Product contract §12; frontend step 6                   |
| Image and structured-data first-release summaries   | Product contract §13; ADR 0076                          |
| Specialist navigation coexistence                   | Product contract §1; frontend information architecture  |
| Seven safe initial match types; no regex            | Product contract §7.3; frontend step 3                  |
| Required initial actions                            | Product contract §7.4                                   |
| Three independently evaluated URL layers            | Product contract §7.1; ADR 0075                         |
| Bounded browser/API/export/retention/preview        | Product contract §14; API shared behavior               |
| Existing sitemap timing and sitemap-only frontier   | Product contract §§9, 11                                |
| Run versus population versus module completeness    | Product contract §4.3; frontend result behavior         |

## Requirement ownership by contract area

| Contract area                                         | Implementing phase | Required acceptance evidence                                                                 |
| ----------------------------------------------------- | ------------------ | -------------------------------------------------------------------------------------------- |
| Effective settings merge, preset acceptance, profiles | CSA-02             | Unit/property tests for hierarchy/permissions/version pins; private API authorization        |
| Match normalization and precedence                    | CSA-02             | Table-driven semantics, collision/conflict tests, bounded preview, SSRF regression           |
| Audit drafts/runs/snapshots/populations               | CSA-03             | One-head migration tests, cascades/retention, restart-safe repositories, immutable history   |
| Issue/group/task and artifact persistence             | CSA-03/04          | Stable ordering, row bounds, schema versions, hashes, partial labels                         |
| Durable execution and specialist links                | CSA-04             | Worker/recovery/cancellation, provenance/freshness, partial matrices, no duplicate evidence  |
| Wizard/history/result/detail UI                       | CSA-05             | Role, refresh/direct route, query persistence, paging, error/partial/recovery, accessibility |
| Controlled fixture and authorized real site           | CSA-06             | Security regression, bounds, restart/backup, browser matrix, no unsafe target bypass         |

## Current specialist reuse matrix

| Module          | Accepted source and durable output                                                       | Eligible selection / permissions                                           | CSA reuse and current usability note                                                                |
| --------------- | ---------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| Metadata        | `crawl_page_evidence`; audit pages/issues/duplicate groups/summary/events/exports        | Terminal runs with usable evidence; create `jobs.submit`, read `runs.view` | Has searchable run candidates with seed/date/status/profile/count; directly link summaries/details. |
| Sitemap         | Safe fetched sitemap documents/entries plus crawl evidence; findings/comparisons/exports | Explicit discovery/audit; authenticated private API                        | Link comparisons and specialist exports; do not duplicate network discovery.                        |
| Link            | Retained source-link occurrences; targets/chains/loops/findings/recommendations/exports  | Run evidence endpoint; create/execute submit permission                    | Link derived evidence; technical run context still appears in parts of specialist workflow.         |
| Internal Links  | Page/source-link evidence; durable graph/metrics/findings/exports                        | Run evidence endpoint; create/execute                                      | Link graph summary; technical IDs remain a secondary workflow limitation.                           |
| Images          | Retained image occurrences/resources; analyses/groups/pages/findings/exports             | Run evidence endpoint; create/execute                                      | Embedded base counts plus linked audit details; technical IDs remain in portions of creation flow.  |
| Structured Data | Retained inert JSON-LD/Microdata/RDFa; entities/profiles/findings/exports                | Run evidence endpoint; create/execute                                      | Embedded base counts plus linked audit details; technical IDs remain in portions of creation flow.  |
| Migration QA    | Explicit source/destination inventory, maps, readiness/findings/exports                  | Run evidence plus project workflow                                         | Link only when explicitly relevant; project and run technical context remains specialized.          |

CSA-05 should reuse the metadata run-selector pattern—searchable seed/site, completion time, status,
profile, evidence count, eligibility explanation—with one shared eligible-evidence selector instead of
requiring pasted internal IDs. It must not broadly redesign specialist screens as part of CSA.

## Repository gaps assigned forward

- No CSA draft/profile/preset/rule domain authority: CSA-02.
- No immutable CSA aggregate/population/rule-match persistence: CSA-03.
- No parent-child coordinator or combined priority/group projection: CSA-04.
- No CSA routes or screens: CSA-04/05 respectively.
- Existing crawl normalization has no configurable accepted tracking-parameter policy: CSA-02
  defines the pure policy; CSA-04 injects it into the accepted crawl composition.
- Existing evidence does not by itself record discovery-exclusion matches because excluded URLs may
  never enter page evidence: CSA-03 persists bounded discovery decisions; CSA-04 supplies them.

## Open decisions

No unresolved first-release product decision blocks CSA-02. The following are deliberately deferred,
not hidden open requirements:

| Question                                       | Options / implications                                                                        | Recommendation                                                                          | Must resolve by                      |
| ---------------------------------------------- | --------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- | ------------------------------------ |
| Add regex matching?                            | Regex adds denial-of-service and semantic portability risk.                                   | Keep absent until a safe engine, complexity budget, and preview UX are approved.        | Future roadmap before implementation |
| Allow manual final sitemap overrides?          | Could preserve editorial intent but must not erase evidence and requires history/conflict UX. | Design a separate versioned override layer only after generated recommendations mature. | Future roadmap                       |
| Allow manual/numeric priority overrides?       | Numeric weights are harder to explain and may obscure severity.                               | Retain transparent tuple; reconsider with observed product needs.                       | Future roadmap                       |
| Add resource-only or issue-ignore URL actions? | These cross evidence classification and issue policy ownership.                               | Design in the owning subsystem, not URL governance.                                     | Future roadmap                       |

Implementation details such as exact SQL table names are intentionally owned by CSA-03 and are not
product decisions, provided they satisfy the immutable external contract.
