# Structured-Data Audit

Phase 25 is a deterministic review workflow over evidence retained during the accepted crawl. The HTML parser records bounded JSON-LD scripts, Microdata item scopes, and a conservative RDFa subset. It never evaluates scripts, loads remote contexts, follows entity references, or performs an additional fetch.

The durable analysis inventories blocks, entities, properties, references, pages, duplicates, syntax findings, cross-page consistency findings, profile observations, and recommendations. Stable IDs and normalized fingerprints make reruns deterministic. Evidence is bounded by block count, raw characters, traversal depth, property count, reference count, and ordinary page-evidence retention.

Parser diagnostics distinguish orphan Microdata properties, unusable `itemid` values, unresolved `itemref` references, asserted properties without values, malformed RDFa prefix declarations, and RDFa patterns outside the supported subset. The supported RDFa prefix form is one or more `name:` plus absolute HTTP(S) IRI pairs. `inlist` semantics are retained as an unsupported-pattern review observation; the audit does not perform namespace or RDF graph reasoning.

An entity-type conflict requires the same retained stable identifier and incompatible type families. LocalBusiness subtypes, Article subtypes, and WebPage subtypes are compatible combinations. Unknown/custom types are not invalid merely because they are unfamiliar. Structural whitespace, keyword, or unusable URL-like type values can be classified as malformed. No finding chooses an authoritative type or business value.

## Profiles and vocabulary

The recognized vocabulary is an allowlist for review classification, not a semantic validator. Versioned profiles cover Organization, LocalBusiness and its listed subtypes, WebSite, WebPage, Article and BlogPosting, BreadcrumbList, Product and Offer, FAQPage, Event, Person, Hotel and LodgingBusiness, Restaurant, and Service. Observation states are `present`, `missing`, `empty`, `invalid`, `conflicting`, `not_applicable`, or `indeterminate`. A profile observation never certifies eligibility, ranking, search-engine acceptance, or standards conformance.

`not_applicable` is used only when an explicit conditional profile rule does not apply; it is not a substitute for missing evidence. `indeterminate` represents retained structured values that cannot safely be reduced to a scalar or resolved relationship. URL, date, price, and currency rules can produce `invalid`; conflicting singleton values can produce `conflicting`. Not every state logically applies to every required profile property.

## Lifecycle, access, and exports

Audits move through accepted, claimed, inventory, entity, profile, consistency, recommendation, and terminal states. Derived rows and lifecycle events are database-backed and retention cleanup cascades from the audit. The only route prefix is `/api/internal/v1/audits/structured-data`. GET operations require `runs.view`; creation, execution, and export creation require `jobs.submit`.

Eight formats are supported: structured-data inventory CSV, entity inventory CSV, property findings CSV, duplicate groups CSV, page summaries CSV, recommendations CSV, complete JSON, and Markdown. Exports are bounded by the configured row limit and remain behind authenticated routes.

All CSVs use fixed ordered schemas, including empty exports. Cells are bounded and strings beginning with `=`, `+`, `-`, or `@` are prefixed with an apostrophe to prevent spreadsheet formula interpretation. JSON uses schema `musimack-structured-data-audit` version `1.0` and includes audit/evidence identity, warnings, collection caps, omitted counts, and truncation state. Markdown contains the fixed executive, scope, readiness, distribution, finding, duplicate, profile, recommendation, limitation, and human-review sections.

Findings expose confidence and whether human review is required. Recommendations additionally expose scope, occurrence and affected-page counts, supporting finding IDs, and bounded structured evidence IDs. These references never duplicate full raw scripts. Recommendations never generate production JSON-LD, select authoritative conflicting facts, or mutate live pages.

## Explicit exclusions

Phase 25 does not fetch Schema.org or external contexts, execute JavaScript, emulate a browser DOM, validate Google/Bing rich results, infer content not present in retained evidence, edit a site, or promise SEO outcomes. Malformed or truncated evidence produces explainable findings instead of best-effort execution.
