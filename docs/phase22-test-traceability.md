# Phase 22 test traceability

| Requirement | Direct automated coverage |
| --- | --- |
| Parser-authoritative occurrences, duplicates, fragments, rel/nofollow, schemes | `backend/tests/unit/test_link_audit_domain.py::test_link_evidence_projection_keeps_occurrences_fragments_rel_and_schemes` |
| Broken-target taxonomy | `test_broken_link_classification_matrix` |
| Redirect precedence and loop | `test_redirect_precedence_preserves_loop_and_broken_destination_reasons` |
| Versioned filter-bound cursor | `test_cursor_is_versioned_filter_bound_and_deterministic`; private API cursor test |
| Durable network-free execution, aggregation, filters, chains, recommendations | `backend/tests/integration/test_link_audit_service.py::test_link_audit_executes_from_durable_evidence_without_network` |
| Artifact exports, idempotence, restart | `test_exports_are_artifacts_idempotent_and_survive_restart` |
| Missing evidence and bounds | `test_missing_or_nonterminal_evidence_is_rejected` |
| Migration, schema, offline SQL, downgrade/re-upgrade | `backend/tests/integration/test_persistence_migrations.py` Phase 22 assertions |
| Private namespace, auth, permissions, all operations, old route | `test_private_api_routes_auth_pagination_filters_and_old_route_absence` |
| Protected frontend navigation and creation | `frontend/src/app/App.test.tsx` link-audit assertions |
| API contracts, safe identifiers, filters, inventories, exports | `frontend/src/link-audits/api.test.ts` |
| Evidence gate, dashboard, filters, accessible tables | `frontend/src/pages/LinkAuditPages.test.tsx` |

Manual coverage uses [link-audit-browser-qa.md](link-audit-browser-qa.md) and does not replace automated evidence.
