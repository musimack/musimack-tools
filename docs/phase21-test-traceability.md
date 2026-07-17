# Phase 21 test traceability

Every row names the test that directly asserts the requirement. Parameterized cases are shown in
parentheses rather than being inferred from incidental coverage.

| Requirement category | Required test case | Test file | Exact test function | Status |
| --- | --- | --- | --- | --- |
| Discovery | Explicit sitemap discovery | `backend/tests/integration/test_sitemap_audit_service_and_api.py` | `test_audit_fetches_explicit_url_and_compares_durable_evidence` | Covered |
| Discovery | Robots directives and case/spacing variants | same | `test_discovery_preserves_explicit_robots_common_order_and_deduplicates` (`Sitemap:`, `SITEMAP:`) | Covered |
| Discovery | Common locations | same | `test_discovery_preserves_explicit_robots_common_order_and_deduplicates` (`/sitemap.xml`, `/sitemap_index.xml`, `/wp-sitemap.xml`) | Covered |
| Discovery | Candidate ordering and deduplication | same | `test_discovery_preserves_explicit_robots_common_order_and_deduplicates` | Covered |
| Fetch safety | Unsafe addresses | `backend/tests/unit/test_safety.py` | `test_mixed_safe_and_unsafe_answers_are_rejected` | Covered |
| Fetch safety | Unsafe redirects | `backend/tests/unit/test_redirect_fetching.py` | `test_redirect_to_unsafe_hostname_is_blocked`; `test_redirect_resolving_to_unsafe_address_is_blocked` | Covered |
| Fetch safety | Scope failures | `backend/tests/integration/test_sitemap_audit_service_and_api.py` | `test_invalid_or_out_of_scope_explicit_url_fails_before_sitemap_fetch` | Covered |
| Fetch safety | Response size limits | `backend/tests/unit/test_sitemap_audit_domain.py`; `backend/tests/unit/test_fetcher.py` | `test_response_and_index_child_limits_retain_bounded_evidence`; `test_declared_oversized_response_is_rejected_before_body_read` | Covered |
| Fetch safety | Timeouts | `backend/tests/unit/test_fetcher.py` | `test_timeout_types_map_to_stable_failures` (connect/read/write/pool) | Covered |
| XML security | DTD and entity rejection | `backend/tests/unit/test_sitemap_audit_domain.py` | `test_dangerous_xml_declarations_are_rejected` (`DOCTYPE`, mixed-case `ENTITY`) | Covered |
| XML formats | Gzip URL and gzip content | same | `test_gzip_url_and_magic_are_rejected` (`.gz`, gzip magic/content type) | Covered |
| XML formats | URL-set parsing | same | `test_valid_urlset_preserves_order_normalizes_and_deduplicates` | Covered |
| XML formats | Sitemap-index parsing | same | `test_index_namespace_and_child_order_are_retained` | Covered |
| XML formats | Namespace variants | same | `test_namespace_variants_are_warnings` (missing, nonstandard) | Covered |
| XML errors | Malformed XML | same | `test_malformed_unsupported_and_empty_documents_are_explicit` (`INVALID_XML`) | Covered |
| XML errors | Missing and invalid locations | same | `test_invalid_locations_remain_inspectable` (missing, empty, relative, unsupported scheme, out of scope) | Covered |
| XML identity | Duplicate normalized URLs | same | `test_valid_urlset_preserves_order_normalizes_and_deduplicates` | Covered |
| XML errors | Empty documents | same | `test_malformed_unsupported_and_empty_documents_are_explicit` (`EMPTY_URL_SET`, `EMPTY_SITEMAP_INDEX`) | Covered |
| Recursion | Nested indexes | `backend/tests/integration/test_sitemap_audit_service_and_api.py` | `test_nested_index_expands_once_and_preserves_parent_child_inventory` | Covered |
| Limits | All parser and recursive limits | `backend/tests/unit/test_sitemap_audit_domain.py`; `backend/tests/integration/test_sitemap_audit_service_and_api.py` | `test_parser_enforces_url_and_child_limits_with_partial_evidence`; `test_response_and_index_child_limits_retain_bounded_evidence`; `test_recursive_document_depth_and_total_url_limits_are_durable` (documents, depth, total URLs) | Covered |
| Recursion | Direct and indirect loops | `backend/tests/integration/test_sitemap_audit_service_and_api.py` | `test_index_loop_and_partial_child_failure_reach_durable_terminal_states` (self-loop, A→B→A) | Covered |
| Recursion | Redirect aliases | same | `test_redirect_aliases_are_fetched_once_per_final_identity` | Covered |
| Recursion | Partial child failure | same | `test_index_loop_and_partial_child_failure_reach_durable_terminal_states` | Covered |
| Comparison | Every comparison state and action | `backend/tests/unit/test_sitemap_audit_domain.py` | `test_comparison_covers_add_remove_review_and_unchanged_with_precedence`; `test_sitemap_only_evidence_remains_unverified` | Covered |
| Comparison | Comparison precedence | same | `test_specific_evidence_precedes_generic_availability` (failed+redirect, partial+noindex, partial+canonical, unavailable indexability+valid evidence) | Covered |
| Comparison | Redirect destination behavior | same | `test_specific_evidence_precedes_generic_availability` (`failed-redirect`) | Covered |
| Comparison | Canonical target behavior | same | `test_specific_evidence_precedes_generic_availability` (`partial-canonical`) | Covered |
| Comparison | Invalid raw entries | same | `test_invalid_locations_remain_inspectable` | Covered |
| Persistence | Constraints and lifecycle events | `backend/tests/integration/test_persistence_migrations.py`; `backend/tests/integration/test_sitemap_audit_service_and_api.py` | `test_sitemap_audit_migration_downgrades_only_phase_21_tables`; `test_duplicate_execution_is_atomically_rejected_and_lifecycle_is_observable` | Covered |
| Persistence | Atomic completion | `backend/tests/integration/test_sitemap_audit_service_and_api.py` | `test_duplicate_execution_is_atomically_rejected_and_lifecycle_is_observable` | Covered |
| Persistence | Partial persistence | same | `test_index_loop_and_partial_child_failure_reach_durable_terminal_states` | Covered |
| Query | Cursor pagination | `backend/tests/unit/test_sitemap_audit_domain.py`; `backend/tests/integration/test_sitemap_audit_service_and_api.py` | `test_cursor_is_filter_bound_and_versioned`; `test_audit_fetches_explicit_url_and_compares_durable_evidence` (offset pages) | Covered |
| Query | Filter combinations | `backend/tests/integration/test_sitemap_audit_service_and_api.py` | `test_audit_fetches_explicit_url_and_compares_durable_evidence` (action+URL) | Covered |
| Retention | Retention and cleanup | same | `test_retention_cleanup_is_bounded_and_cascades_normalized_evidence` | Covered |
| Export | CSV formula injection | `backend/tests/unit/test_sitemap_audit_domain.py` | `test_exports_defend_csv_formulas_and_keep_json_markdown_contracts` | Covered |
| Export | JSON schema and ordering | same | `test_exports_defend_csv_formulas_and_keep_json_markdown_contracts` | Covered |
| Export | Markdown sections | same | `test_exports_defend_csv_formulas_and_keep_json_markdown_contracts` | Covered |
| Artifact | Integrity and authorization | `backend/tests/integration/test_sitemap_audit_service_and_api.py`; `backend/tests/integration/test_artifact_storage.py` | `test_exports_register_and_verify_all_formats`; `test_changed_missing_and_oversize_files_are_not_downloaded`; `test_production_adds_exactly_three_private_artifact_routes` | Covered |
| API | Authentication and permissions | `backend/tests/integration/test_sitemap_audit_service_and_api.py` | `test_routes_are_private_coherent_and_permission_mapped` | Covered |
| API | All 12 operations | same | `test_all_twelve_private_api_operations_execute_with_authorization` | Covered |
| API | Old-route absence | same | `test_routes_are_private_coherent_and_permission_mapped` | Covered |
| Composition | Health-only default | `backend/tests/integration/test_production_security.py` | `test_default_application_remains_health_only_and_secret_free` | Covered |
| Composition | Every optional route composition | `backend/tests/integration/test_history_service_and_api.py`; `backend/tests/integration/test_metadata_audit_service_and_api.py`; `backend/tests/integration/test_sitemap_audit_service_and_api.py` | `test_exact_route_matrix_for_default_and_optional_private_features`; `test_routes_are_private_and_add_exactly_ten_operations_on_nine_paths`; `test_routes_are_private_coherent_and_permission_mapped` | Covered |
| Lifecycle | Duplicate and terminal execution | `backend/tests/integration/test_sitemap_audit_service_and_api.py` | `test_duplicate_execution_is_atomically_rejected_and_lifecycle_is_observable`; `test_accept_and_execute_are_separate_durable_requests` | Covered |
| Lifecycle | Failure, cancellation/restart interruption, durable transitions | same | `test_execution_failure_and_restart_interruption_are_terminal`; `test_duplicate_execution_is_atomically_rejected_and_lifecycle_is_observable` | Covered |
| Scope | Exact host, subdomains, approved hosts | same | `test_audit_reuses_every_accepted_durable_scope_mode` (all three `ScopeMode` values) | Covered |
| Scope | Unreadable historical snapshot | same | `test_unreadable_historical_scope_snapshot_fails_without_exact_host_fallback` | Covered |
| Authentication | SQLite foreign-key-safe bootstrap | `backend/tests/integration/test_authentication_service_and_api.py` | `test_bootstrap_orders_user_before_credential_with_sqlite_foreign_keys` | Covered |
| Frontend routing | Protected routing and permission behavior | `frontend/src/app/App.test.tsx` | `protects sitemap creation while allowing retained-audit navigation`; `allows an operator to open the explicit sitemap creation route` | Covered |
| Frontend navigation | Sitemap navigation | same | `shows only navigation allowed by the principal permissions` | Covered |
| Frontend list | List and empty state | `frontend/src/pages/SitemapAuditPages.test.tsx` | `list renders both the empty state and retained audit navigation` | Covered |
| Frontend creation | Creation, validation, discovery options, gzip notice | same | `creation exposes accessible discovery controls and the gzip limitation` | Covered |
| Frontend lifecycle | Execute without awaiting; polling termination | same | `execution starts without blocking navigation or waiting for its response`; `terminal lifecycle stops polling` | Covered |
| Frontend summary | Counts and every action view | same | `dashboard shows every action, filters, pagination, status, and exports` | Covered |
| Frontend query | Filtering and pagination | same | `dashboard shows every action, filters, pagination, status, and exports` | Covered |
| Frontend inventory | Document, entry, and finding inventories | same | `renders retained %s inventory with accessible table labels` (`documents`, `entries`, `findings`) | Covered |
| Frontend exports | Export success and artifact errors | same | `dashboard shows every action, filters, pagination, status, and exports`; `artifact export errors remain bounded and preserve audit evidence` | Covered |
| Frontend authentication | Authentication expiration | `frontend/src/sitemap-audits/api.test.ts` | `surfaces authentication expiration from every private read` | Covered |
| Frontend responsive/accessibility | Responsive navigation, labels, live status | `frontend/src/app/App.test.tsx`; `frontend/src/pages/SitemapAuditPages.test.tsx` | `supports the responsive navigation disclosure`; `creation exposes accessible discovery controls and the gzip limitation`; `dashboard shows every action, filters, pagination, status, and exports` | Covered |

The browser fixture itself is exercised manually with the exact procedure in
[`sitemap-audit-browser-qa.md`](sitemap-audit-browser-qa.md); the automated route, authentication,
persistence, artifact, and UI tests above cover its constituent authorities.
