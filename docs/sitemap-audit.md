# Existing sitemap audit reference

Phase 21 is implemented for review and is not accepted until product-owner review. The workflow is private, opt-in, durable, and read-only with respect to audited websites.

## Discovery, parsing, and limits

Candidate order is explicit URL, valid case-insensitive `Sitemap:` robots directives in document order, `/sitemap.xml`, `/sitemap_index.xml`, `/wp-sitemap.xml`, then valid child references in parent order. URLs use accepted normalization and scope checks. Fetches use accepted DNS, SSRF, redirect, timeout, and byte boundaries. Redirect aliases and repeated index references are not fetched twice.

Standard sitemap `urlset` and `sitemapindex` roots are supported. Missing or nonstandard namespaces and imperfect XML content types are warnings when the XML is otherwise safe. HTML responses, malformed XML, unsupported roots, DTDs, and entity declarations are rejected. Default limits are 5,000,000 response bytes, 50,000 URL-set entries, 50,000 index children, 100 documents, index depth 3, 250,000 unique URL entries, page size 50/maximum 200, export rows 100,000, and retention 180 days. Gzip decompression and specialized image, video, and news semantics are not supported.

## Validation taxonomy

- `invalid_xml`: the XML is malformed or cannot be safely parsed.
- `doctype_forbidden`: a DOCTYPE declaration was found.
- `entity_declaration_forbidden`: an entity declaration was found.
- `invalid_namespace`: the standard sitemap namespace is missing or unsupported.
- `unsupported_root_element`: the root is not `urlset` or `sitemapindex`.
- `missing_location`: a member has no `loc` child.
- `empty_location`: a `loc` value is empty after trimming.
- `invalid_location`: a location cannot be normalized as an absolute URL.
- `unsupported_scheme`: a location does not use HTTP or HTTPS.
- `out_of_scope_location`: a location is outside the selected crawl scope.
- `duplicate_location`: the normalized location repeats within its document.
- `unexpected_content_type`: content-type evidence is HTML or not XML-like.
- `response_too_large`: the response exceeds the configured byte boundary.
- `url_count_limit_exceeded`: a URL set exceeds its entry limit.
- `child_count_limit_exceeded`: an index exceeds its child limit.
- `total_url_limit_exceeded`: the audit exceeds its total unique-URL limit.
- `sitemap_document_limit_exceeded`: the audit reaches its document limit.
- `maximum_depth_exceeded`: a child reference exceeds index depth.
- `child_fetch_failed`: a child sitemap could not be safely retrieved.
- `sitemap_index_loop`: an index references an already visited sitemap.
- `empty_url_set`: a URL set contains no URL members.
- `empty_sitemap_index`: an index contains no sitemap members.
- `gzip_not_supported`: the path, content type, or magic bytes identify gzip.
- `fetch_failed`: a root sitemap fetch failed.
- `http_error`: a sitemap response has an unacceptable HTTP status.
- `redirect_alias_duplicate`: the normalized final document was already processed.
- `robots_sitemap_invalid`: a robots Sitemap directive is invalid.

## Comparison policy

The engine compares the sorted union of valid, nonduplicate sitemap URLs and selected-run page evidence. Sitemap inventory is joined to the SHA-256 normalized-URL identity used by durable page evidence. Accepted recommendation values are `include`, `exclude`, `review`, and `indeterminate`.

States are `in_sitemap_and_eligible`, `in_sitemap_but_excluded`, `missing_from_sitemap`, `redirected_sitemap_url`, `noindex_sitemap_url`, `canonicalized_sitemap_url`, `non_html_sitemap_url`, and `sitemap_only_unverified`. Actions are `add`, `remove`, `review`, and `unchanged`.

Reason codes are:

- `eligible_already_present`: eligible evidence is already represented.
- `eligible_missing_from_sitemap`: eligible evidence should be added.
- `recommendation_exclude`: accepted evidence recommends exclusion.
- `recommendation_review`: accepted evidence requires review.
- `recommendation_indeterminate`: evidence cannot support a firm recommendation.
- `redirected_url`: the sitemap URL redirects.
- `noindex_url`: indexability evidence contains noindex.
- `canonical_points_elsewhere`: canonical evidence targets another URL.
- `non_html_content`: durable evidence is not HTML.
- `not_observed_in_selected_crawl`: a sitemap URL has no selected-run evidence.
- `crawl_evidence_failed`: the selected crawl attempt failed.
- `invalid_sitemap_location`: raw sitemap location evidence is invalid.
- `out_of_scope_sitemap_location`: raw location evidence is out of scope.
- `redirect_target_requires_review`: redirect-target eligibility is ambiguous.
- `canonical_target_requires_review`: canonical-target eligibility is ambiguous.

Precedence is invalid or out-of-scope raw-location findings, then specific retained page evidence:
redirect, noindex, conflicting canonical, and known non-HTML content. Generic failed or unavailable
crawl evidence follows those specific signals, then exclusion, review/indeterminate, eligible
included, and sitemap-only evidence. Invalid raw locations remain findings because accepted
comparison-state names describe normalized URL identities. Every union identity yields exactly one
comparison record, so action totals equal comparison totals.

## Persistence, API, exports, and retention

Migration `0008_sitemap_audit` adds `sitemap_audits`, `sitemap_audit_documents`, `sitemap_audit_entries`, `sitemap_audit_findings`, `sitemap_audit_comparisons`, `sitemap_audit_exports`, and `sitemap_audit_events`. Parent/child relationships, provenance, redirect evidence, hashes, counts, states, reason codes, and versions are retained. Raw XML is not retained. Cascades remove normalized children when an audit expires; bounded cleanup selects by `retention_until`.

The only namespace is `/api/internal/v1/audits/sitemaps`. Viewer-compatible reads use `runs.view`; discovery, execution, and export creation use `jobs.submit`. Cursor tokens bind resource kind, ordering, filter fingerprint, and offset. CSV is UTF-8 with a BOM and formula-injection defense; JSON and Markdown are versioned. All export files use existing artifact hashing, integrity, safe-path, retention, download, missing-file, and corruption behavior.

Execution is a synchronous authenticated request, while the browser navigates immediately and
polls through a separate request context. Admission is an atomic accepted-to-discovering claim, so
duplicate and terminal execution requests are rejected. Each lifecycle transition commits in its
own short transaction. Request cancellation and ordinary execution failures are terminalized, and
service startup marks any process-interrupted nonterminal audit failed; result durability does not
make execution resumable.

Sitemap discovery and parsing reconstruct the accepted crawl scope mode and approved-host set from
the durable run configuration snapshot. Exact-host, subdomain-inclusive, and approved-host crawls
therefore retain their original host semantics. A historical run whose required snapshot is absent
or unreadable fails with `sitemap_audit_scope_unavailable` instead of silently becoming exact-host.

For a loopback-only authenticated human review procedure, see
[`sitemap-audit-browser-qa.md`](sitemap-audit-browser-qa.md).

The frontend provides list, discovery/create, dashboard, Add/Remove/Review/Unchanged filtering, URL and reason filtering, pagination, root/child inventory, entry inventory, findings, and three exports. Authentication expiry and permission denial use the existing centralized client and protected-route behavior.
