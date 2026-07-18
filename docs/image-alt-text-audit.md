# Phase 24 image and alt-text audit

Phase 24 is a private, human-review workflow over one terminal crawl. The backend, not the browser, supplies page, scope, and image occurrence evidence. The accepted parser records `img`, `picture` source candidates, a four-attribute lazy-load allowlist, alt presence and raw value, dimensions, loading/decoding/fetch priority, link context, and explicit decorative evidence. Attribute values are bounded. Full data URL payloads and raw HTML are not persisted.

## Resource and analysis policy

Resources are deduplicated by normalized identity. Existing page/fetch evidence wins; otherwise an authorized internal image may be checked only through `SafeFetchImageVerifier`, an adapter over the existing safe single-URL fetcher. Missing evidence remains `unverified_image`, never an invented 404. External and out-of-scope images are not fetched by default. Accepted image MIME types include JPEG, PNG, GIF, WebP, SVG, AVIF, and icon types. HTML, JSON, missing, or unknown content types are review evidence.

Alternative text preserves missing, empty, whitespace-only, and explicit decorative distinctions. Linked missing/empty alternatives receive higher priority. Generic, filename-like, URL-like, overlong, repeated, and inconsistent values are deterministic review states. Empty `alt` is not automatically defective. Dimensions and loading are conservative HTML-attribute evidence; the audit does not claim layout shift, viewport position, or Core Web Vitals impact.

Recommendations name actions and reasons but never invent replacement alt text. Binary hashing, perceptual duplicates, OCR, embeddings, external AI, browser candidate selection, full CSS parsing, and live-site mutation are excluded.

## Persistence, API, and exports

Revision `0011_image_alt_text_audit` follows `0010_internal_link_analysis`. It adds `crawl_image_evidence` and nine audit concept tables with foreign keys, uniqueness, nonnegative checks, deterministic ordering indexes, cascades, terminal timestamps, and restart reconciliation. Running states interrupted by restart become terminal failures; source evidence deletion cascades occurrence authority and dependent audit analyses.

The opt-in API exists only at `/api/internal/v1/audits/images`. Reads require `runs.view`; creation, execution, and export generation require `jobs.submit`. Filter-bound cursors reject changed filters. Viewer users may inspect completed results and use separately authorized artifact downloads but cannot mutate audits.

Exports are image inventory, alt findings, broken/redirecting resources, duplicate groups, page summaries, and recommendations CSV plus complete JSON and Markdown. CSV output is UTF-8, stably ordered, quoted by the standard writer, and defends spreadsheet formula prefixes. Existing artifact storage provides atomic writes, safe names, SHA-256, authorization, retention, verification, cleanup, and reconciliation.

## Retention and limitations

Audit rows cascade from an audit; occurrence analyses retain explicit foreign keys to source page and image evidence. Artifact references use `SET NULL` so missing or cleaned artifacts are reported without corrupting analysis history. Current intrinsic dimensions are unavailable unless future accepted bounded evidence supplies them. Human review remains required for decorative intent, loading behavior, duplicates, and all proposed content changes.
