# ADR 0070: persist parser-owned image evidence before image analysis

Status: accepted for Phase 24 implementation review.

The existing HTML parser is the sole image-discovery authority. Its bounded occurrence projection is committed in the same terminal page-evidence transaction as pages and links. The image audit consumes those immutable records, groups normalized resources once, prefers retained response evidence, and delegates optional network verification only to the accepted safe-fetch adapter. This avoids a second parser, crawler, raw HTTP client, and browser-supplied inventory.

Data URLs retain metadata and a short fingerprint, never payloads. Responsive candidates are inventoried without browser layout selection. CSS stylesheet extraction, intrinsic dimension parsing, binary/perceptual duplicate detection, recognition, OCR, generated alt text, and mutation are excluded. The private workflow, lifecycle, persistence, filters, cursor binding, exports, authorization, retention, and restart reconciliation follow established audit authorities.
