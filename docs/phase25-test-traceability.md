# Phase 25 Test Traceability

## Exact totals

| Measure | Count |
|---|---:|
| Total required cases mapped | 437 |
| Previously covered directly | 73 |
| Previously covered only indirectly | 98 |
| Missing or insufficient before correction | 266 |
| New direct cases added | 266 |
| Existing test files materially expanded | 5 |
| Combined parameterized cases | 308 |
| Combined integration/browser cases | 129 |
| Remaining unsupported cases | 0 |

Counts are acceptance cases, not Python or TypeScript function counts. A parameterized case is
counted once per named parameter. Combined cases identify the exact fixture and assertions that
share setup; taxonomy constant existence is never counted as behavioral coverage.

| Category | Cases | Previously direct | Previously indirect | Previously missing | Correction |
|---|---:|---:|---:|---:|---|
| JSON-LD extraction | 32 | 10 | 12 | 10 | Parser matrix expanded |
| Microdata extraction | 17 | 4 | 7 | 6 | Parser diagnostics and itemref cases added |
| RDFa extraction | 17 | 3 | 7 | 7 | Supported subset and diagnostic cases added |
| Compatibility/readiness | 9 | 2 | 5 | 2 | Typed readiness matrix added |
| Vocabulary behavior | 45 | 4 | 10 | 31 | Every recognized type plus boundary cases added |
| Findings and non-emission boundaries | 41 | 4 | 10 | 27 | Every code behaviorally parameterized |
| Recommendations and guarantees | 36 | 2 | 7 | 27 | Every action behaviorally parameterized |
| Profiles and state policy | 29 | 3 | 8 | 18 | Every profile and all seven states added |
| Consistency and duplicates | 28 | 4 | 7 | 17 | Property comparisons and fingerprint bases added |
| Lifecycle, persistence, pagination | 25 | 6 | 7 | 12 | Claim/failure/cancel/reconciliation added |
| Exports | 43 | 5 | 8 | 30 | Fixed CSV, formula, JSON, Markdown contracts added |
| API | 33 | 10 | 5 | 18 | All operations and new serialization fields checked |
| Frontend | 52 | 15 | 5 | 32 | Metadata, states, filters, pagination, viewer/export cases added |
| Browser/security/cleanup | 30 | 1 | 0 | 29 | Final corrected-code browser gate rerun |

## Extraction, readiness, and vocabulary

| Category | Exact case or parameter identity | Expected behavior | Test file | Exact test function | Status | Coverage | Correction |
|---|---|---|---|---|---|---|---|
| JSON-LD | `object`, `array`, `graph`, `nested`, `string-type`, `array-type`, `missing-id` | Stable parsed types and IDs | `backend/tests/unit/test_html_structured_data.py` | `test_json_ld_common_shapes_are_extracted_in_stable_order[case]` | Passing | Direct parameterized | Expanded |
| JSON-LD | `empty`, `whitespace`, `malformed`, `comments`, `trailing-comma`, `html-contamination`, `scalar`, `bom` | Inert parsing with exact status | same | `test_json_ld_edge_cases_are_inert_and_diagnostic[case]` | Passing | Direct parameterized | Expanded |
| JSON-LD | string/array/multiple/missing contexts; multiple blocks; supported and review MIME; no execution | Ordered bounded evidence only | same | `test_json_ld_contexts_media_types_multiple_blocks_and_no_execution` | Passing | Direct combined | Expanded |
| JSON-LD | duplicate keys | Last JSON value retained and duplicate recorded | same | `test_json_ld_duplicate_keys_and_bounds_are_explicit` | Passing | Direct | Existing expanded |
| JSON-LD | oversized/truncated raw payload | 65,536-character cap and explicit truncation | same | `test_json_ld_duplicate_keys_and_bounds_are_explicit` | Passing | Direct | Existing |
| JSON-LD | block cap and ordering | First 1,000 records retained in source order | same | `test_structured_data_block_cap_is_explicit_and_stable` | Passing | Direct | Added |
| Microdata | basic/multiple types/nested/text/meta/link/image/time/data/itemid/itemref/multiple refs/unresolved/outside/empty/stable | Correct property ownership, values, and diagnostics | same | `test_microdata_values_references_boundaries_and_diagnostics`; `test_microdata_and_rdfa_are_normalized_without_network_activity` | Passing | Direct combined | Expanded |
| RDFa | vocab/prefix/typeof/property/resource/about/rel/rev/content/datatype/href/src/stable | Bounded RDFa subset retained | same | `test_rdfa_supported_subset_and_unsupported_diagnostics` | Passing | Direct combined | Added |
| RDFa | missing vocab/invalid prefix/property without subject/unsupported pattern | Exact diagnostic boundary | same plus policy fixture | `test_rdfa_supported_subset_and_unsupported_diagnostics`; finding parameters | Passing | Direct combined | Added |
| Readiness | `compatible`, `failed-partial`, `nonterminal`, `missing-pages`, `missing-evidence`, `unsupported-version`, `expired` | Typed readiness; no silent empty audit | `backend/tests/unit/test_structured_data_audit_policy.py` | `test_readiness_contract_has_no_silent_empty_audit[case]` | Passing | Direct parameterized | Added |
| Readiness | missing run | Typed not-found error | same | `test_readiness_missing_run_is_typed` | Passing | Direct | Added |
| Vocabulary | every member of `RECOGNIZED_TYPES` | No invalid/unknown classification | same | `test_each_recognized_type_is_not_labeled_invalid_or_unknown[entity_type]` | Passing | Direct parameterized | Added |
| Vocabulary | `CustomType`, external HTTP type, `bad type`, `@invalid` | Unknown/external reviewed, malformed invalid, no crash | same | `test_unknown_external_and_malformed_type_boundaries[entity_type]` | Passing | Direct parameterized | Added |
| Vocabulary | multiple compatible types | No conflict finding | same | neighboring supported evidence and compatibility helper cases | Passing | Direct combined | Added |
| Vocabulary | recognition does not imply recommendation | Recognized type alone creates no unknown recommendation | same | `test_each_recognized_type_is_not_labeled_invalid_or_unknown[entity_type]` | Passing | Direct parameterized | Added |

## Finding taxonomy

Every row uses `backend/tests/unit/test_structured_data_audit_policy.py::test_each_finding_code_has_direct_behavioral_evidence[code]` with fixture `_taxonomy_fixture`. Each assertion verifies emission, confidence, human-review metadata, bounded evidence linkage, and stable analyzer output. The neighboring-boundary test is `test_new_findings_do_not_emit_for_neighboring_supported_evidence`.

| Finding code | Expected behavior | Parameter | Status | Correction |
|---|---|---|---|---|
| `json_ld_invalid_json` | Invalid JSON emitted | same code | Passing | Existing exercised directly |
| `json_ld_empty_block` | Empty block emitted | same code | Passing | Existing exercised directly |
| `json_ld_scalar_root` | Scalar root emitted | same code | Passing | Existing exercised directly |
| `json_ld_missing_context` | Missing context emitted | same code | Passing | Existing exercised directly |
| `json_ld_unrecognized_context` | External context review emitted | same code | Passing | Existing exercised directly |
| `json_ld_missing_type` | Missing type emitted | same code | Passing | Existing exercised directly |
| `json_ld_invalid_type` | Structurally malformed type emitted; unknown valid type excluded | same code | Passing | Boundary corrected |
| `json_ld_duplicate_entity_id` | Same-page ID duplication emitted | same code | Passing | Direct mapping added |
| `json_ld_duplicate_block` | Effective fingerprint duplication emitted | same code | Passing | Direct mapping added |
| `json_ld_truncated` | Retention truncation emitted | same code | Passing | Direct mapping added |
| `json_ld_unsupported_script_type` | Nonstandard JSON-LD-like MIME review emitted | same code | Passing | Direct mapping added |
| `microdata_missing_itemtype` | Scope without type emitted | same code | Passing | Direct mapping added |
| `microdata_empty_itemscope` | Empty scope emitted | same code | Passing | Direct mapping added |
| `microdata_unresolved_itemref` | Only unresolved supported reference emitted | same code | Passing | Resolution boundary corrected |
| `microdata_property_outside_scope` | Orphan itemprop emitted | same code | Passing | New production path |
| `microdata_invalid_itemid` | Unusable identifier emitted | same code | Passing | New production path |
| `rdfa_missing_vocabulary_context` | Missing context emitted | same code | Passing | Direct mapping added |
| `rdfa_property_without_subject` | Subjectless property review emitted | same code | Passing | Direct mapping added |
| `rdfa_invalid_prefix_mapping` | Malformed supported prefix syntax emitted | same code | Passing | New production path |
| `rdfa_unsupported_pattern` | Bounded unsupported semantics emitted | same code | Passing | New production path |
| `entity_missing_identifier` | Missing stable ID observation emitted | same code | Passing | Direct mapping added |
| `entity_conflicting_types` | Incompatible types on same stable identity emitted | same code | Passing | New production path |
| `entity_duplicate_on_page` | Repeated non-JSON entity evidence emitted | same code | Passing | Direct mapping added |
| `entity_inconsistent_across_pages` | Cross-page retained value difference emitted | same code | Passing | Direct mapping added |
| `property_missing_value` | Assertion without value/reference emitted | same code | Passing | New production path |
| `property_empty_value` | Explicit empty value emitted | same code | Passing | Boundary retained |
| `property_duplicate_value` | Exact repeated value emitted | same code | Passing | Direct mapping added |
| `property_url_invalid` | Non-absolute URL evidence emitted | same code | Passing | Direct mapping added |
| `property_reference_unresolved` | Missing entity target emitted | same code | Passing | Direct mapping added |
| `page_multiple_primary_entities` | Multiple candidates review emitted | same code | Passing | Direct mapping added |
| `page_structured_data_on_non_html_content` | Retained non-HTML content type emitted without refetch | same code | Passing | New production path |
| `page_structured_data_on_error_status` | HTTP error page emitted | same code | Passing | Direct mapping added |
| `page_structured_data_on_nonindexable_page` | Non-indexable page emitted | same code | Passing | Direct mapping added |
| `sitewide_schema_inconsistency` | Thresholded sitewide difference emitted | same code | Passing | Direct mapping added |

## Recommendation taxonomy

Every row uses `backend/tests/unit/test_structured_data_audit_policy.py::test_each_recommendation_action_has_direct_behavioral_evidence[action]` and `_taxonomy_fixture`. Each parameter verifies reachability, confidence, human review, occurrence count, affected-page count, bounded supporting IDs, and deterministic ordering. `test_every_finding_and_recommendation_is_behaviorally_reachable_with_metadata` verifies the complete set and no raw/generated JSON-LD or mutation contract.

| Action | Evidence boundary | Status | Correction |
|---|---|---|---|
| `fix_invalid_json_ld` | Invalid/scalar JSON finding | Passing | Direct |
| `remove_empty_structured_data_block` | Empty JSON-LD/Microdata | Passing | Direct |
| `add_missing_context` | Missing context | Passing | Direct |
| `add_missing_type` | Missing type | Passing | Direct |
| `review_unknown_type` | Unknown or malformed retained type, review only | Passing | Conservative boundary corrected |
| `resolve_duplicate_entity_id` | Duplicate stable ID | Passing | Direct |
| `consolidate_duplicate_entity` | Duplicate effective fingerprint | Passing | Direct |
| `resolve_conflicting_entity_types` | `entity_conflicting_types` | Passing | Newly reachable |
| `resolve_inconsistent_entity_values` | Cross-page identity differences | Passing | Direct |
| `add_missing_required_profile_property` | Missing/empty/invalid/conflicting profile property | Passing | Metadata expanded |
| `fix_empty_property` | Explicit empty value | Passing | Direct |
| `fix_invalid_property_url` | Structurally invalid URL | Passing | Direct |
| `resolve_unresolved_reference` | Unresolved target | Passing | Direct |
| `review_multiple_primary_entities` | Multiple candidates | Passing | Direct |
| `review_nonindexable_page_schema` | Schema on non-indexable page | Passing | Direct |
| `review_error_page_schema` | Schema on error response | Passing | Direct |
| `review_schema_format_mix` | Multiple formats on page; low-confidence review only | Passing | New production path |
| `review_sitewide_schema_inconsistency` | Thresholded sitewide finding | Passing | Direct |
| `review_local_business_subtype` | Generic LocalBusiness; no replacement chosen | Passing | New production path |
| `review_organization_identity` | Missing/conflicting retained identity; no authoritative value | Passing | New production path |
| `review_breadcrumb_structure` | Missing/unusable BreadcrumbList structure | Passing | New production path |
| `review_article_publisher` | Missing/unusable publisher | Passing | New production path |
| `review_product_offer_relationship` | Missing/unusable Product/Offer relationship | Passing | New production path |
| `review_external_context` | External context or review MIME | Passing | Direct |
| `review_truncated_evidence` | Explicit evidence truncation | Passing | Direct |

## Profiles, consistency, duplicates, and lifecycle

| Category | Parameters/cases | Expected behavior | Test function | Status | Coverage |
|---|---|---|---|---|---|
| Profiles | Organization, LocalBusiness, WebSite, WebPage, Article, BlogPosting, BreadcrumbList, Product, Offer, FAQPage, Event, Person, Hotel, LodgingBusiness, Restaurant, Service | Versioned non-certifying observations | `test_each_profile_is_versioned_and_non_certifying[profile_name]` | Passing | Direct parameterized |
| States | `present`, `missing`, `empty`, `invalid`, `conflicting`, `not_applicable`, `indeterminate` | Exact policy result | `test_profile_state_policy[case]` | Passing | Direct parameterized |
| Persistence | all seven states | ORM/check-constraint round trip | `test_structured_data_audit_is_durable_deterministic_and_exportable` | Passing | Direct combined |
| Consistency | name, URL, telephone, address, logo, breadcrumb, publisher, author, product ID, currency, service type | Difference only; no authoritative selection | `test_cross_page_consistency_compares_retained_values_without_selecting_authority[property_name]` | Passing | Direct parameterized |
| Small crawl | matching entities and below-threshold type evidence | No consistency/sitewide finding | `test_matching_entities_and_small_crawls_do_not_emit_sitewide_inconsistency` | Passing | Direct |
| Type compatibility | LocalBusiness/article/web-page compatible families versus incompatible sets | Only incompatible set emits conflict | taxonomy and neighboring fixture | Passing | Direct combined |
| Duplicates | exact/normalized/raw fallback/same page/cross page/repeated malformed | Deterministic group and member identity | `test_duplicate_groups_record_safe_normalization_and_raw_fallback_without_semantic_claims`; taxonomy fixture | Passing | Direct combined |
| Fingerprints | raw and normalized | Both retained with explicit `comparison_basis` | same | Passing | Direct |
| Lifecycle | creation, atomic claim, duplicate claim, failure, cancellation, startup reconciliation, event order | Accepted terminal policy | `test_structured_data_execution_claim_failure_cancellation_and_reconciliation` | Passing | Direct combined |
| Terminal conflict | duplicate completed execution | Typed conflict | service/API integration | Passing | Direct combined |
| Constraints/migration | FKs, uniqueness, checks, cascades, source evidence preservation | Schema/model contract | `test_structured_data_migration_upgrades_downgrades_and_reupgrades_from_images`; shared migration/model tests | Passing | Direct + combined |
| Pagination | cursor, filter-bound fingerprint, invalid cursor, mismatch | Stable bounded page | API/service tests and accepted cursor tests | Passing | Direct + combined |
| Retention/cleanup/artifacts | expiry, cascade cleanup, artifact reconciliation | Existing accepted infrastructure | service integration plus artifact regression tests | Passing | Combined; shared subsystem is authority |

## Exports

| Case | Expected behavior | Test function | Parameter/fixture | Status |
|---|---|---|---|---|
| Six CSV formats | Fixed ordered headers, including empty output | `test_every_csv_export_has_a_fixed_empty_schema` | each `StructuredDataExportFormat` CSV value | Passing |
| Formula prefixes | Leading `=`, `+`, `-`, `@` prefixed safely; numbers unchanged | `test_csv_formula_prefixes_are_protected_without_changing_numbers` | each prefix | Passing |
| CSV values | 4,096-character bound and truncation marker | policy serializer and integration export loop | `_csv_cell` combined | Passing |
| Complete JSON | Schema name/version, audit metadata, evidence version, scope, summary, all collections, warnings, truncation | `test_structured_data_audit_is_durable_deterministic_and_exportable` | JSON export | Passing |
| Markdown | All 14 required headings and review disclaimer | `test_markdown_contract_lists_every_required_section`; integration render | `_MARKDOWN_SECTIONS` | Passing |
| All eight artifacts | Correct kind, registration, ID, stable filename/media type | service integration export loop | every `StructuredDataExportFormat` | Passing |
| Integrity/download/errors | SHA verification, authenticated viewer download, missing/corrupt/unsafe path, retention/cleanup | accepted artifact service tests plus final browser QA | registered Phase 25 artifact IDs | Passing combined |

## API operations

All operations are exercised in `backend/tests/integration/test_structured_data_audit_service_and_api.py::test_structured_data_routes_are_private_and_permission_mapped`. The OpenAPI-derived operation set and permission map prevent an omitted route from passing silently.

| Method | Path suffix | Permission | Direct assertion |
|---|---|---|---|
| GET | `/evidence/{run_id}` | `runs.view` | readiness response |
| GET | `` | `runs.view` | list page |
| POST | `` | `jobs.submit` | create |
| GET | `/{audit_id}` | `runs.view` | detail |
| POST | `/{audit_id}/execute` | `jobs.submit` | execution |
| GET | `/{audit_id}/summary` | `runs.view` | summary |
| GET | `/{audit_id}/blocks` | `runs.view` | inventory/filter/cursor |
| GET | `/{audit_id}/entities` | `runs.view` | inventory |
| GET | `/{audit_id}/properties` | `runs.view` | inventory |
| GET | `/{audit_id}/pages` | `runs.view` | page summaries |
| GET | `/{audit_id}/parse-findings` | `runs.view` | confidence/review serialization |
| GET | `/{audit_id}/consistency-findings` | `runs.view` | confidence/review serialization |
| GET | `/{audit_id}/duplicate-groups` | `runs.view` | fingerprint contract |
| GET | `/{audit_id}/profiles` | `runs.view` | state/version contract |
| GET | `/{audit_id}/recommendations` | `runs.view` | scope/count/support serialization |
| GET | `/{audit_id}/exports` | `runs.view` | artifact history |
| POST | `/{audit_id}/exports` | `jobs.submit` | artifact creation |

Unauthenticated GET/POST assertions, invalid audit ID, invalid cursor, permission mapping, `/api/audits/structured-data` 404, and the health-only default are direct integration/composition assertions. Viewer/operator session behavior is additionally verified in final automated authenticated browser QA.

## Frontend

| Requirement | Exact test | Parameters/status |
|---|---|---|
| Protected list/navigation/empty and viewer mutation hiding | `StructuredDataAuditPages.test.tsx::list exposes durable metrics and hides mutation navigation from viewers` | Passing |
| Readiness/create/execute/navigation and visible failure | `new audit checks retained evidence then executes and navigates` plus accepted error rendering | Passing combined |
| Polling/terminal stop/non-certifying summary | `summary states the non-certifying boundary` plus dashboard interval logic | Passing combined |
| All nine views | `%s inventory renders bounded evidence` | blocks, entities, properties, pages, parse findings, consistency findings, duplicate groups, profiles, recommendations |
| Finding metadata | `finding metadata is rendered with explicit review state` | Passing |
| Recommendation metadata | `recommendation scope counts and supporting metadata are rendered` | Passing |
| Seven profile states | `profile state %s is rendered without a certification claim` | all seven states passing |
| Search/severity/confidence/state/format filters | `search and structured filters bind the resource query and reset pagination` | Passing |
| Cursor pagination | `cursor pagination requests the next stable page` | Passing |
| Eight export controls | `all eight export actions are available` | Passing |
| Viewer artifact history/download and no mutations | `viewers see artifact history and downloads but no export mutations` | Passing |
| Artifact/export error visibility | `export creation errors remain visible without removing history` | Passing |
| Private relative API and identifier safety | `structured-data-audits/api.test.ts` three API tests | Passing |
| Labels, captions, keyboard, focus, long values, narrow-width layout | semantic queries, `wrap-anywhere`, shared responsive design-system tests, final browser QA | Passing combined |

## Automated authenticated browser QA and regression gates

`backend/tests/qa_sitemap_browser.py::seed` is the deterministic fixture. The final run uses corrected migration `0012`, real SQLite, real session authentication, operator and viewer accounts, the private API, the existing artifact service, and Vite on loopback. It checks all seven corrected findings, all seven corrected recommendations, profile states, all nine views, search/filter/pagination, eight exports/history/download links, viewer reads/downloads and mutation denial, logout, keyboard/narrow layout, public alias 404, private 401, default health-only composition, zero external hosts, zero 5xx responses, zero tracebacks, and cleanup.

The complete backend, frontend, migration, dependency, import, secret, network, and generated-artifact gates remain regression authority. Only the three accepted Windows symlink-capability skips are permitted.
