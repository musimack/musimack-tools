# ADR 0075: Layer URL governance and snapshot effective settings

## Status

Proposed for CSA-01 product-owner review.

## Context

Discovery admission, metadata scoring, and sitemap recommendation answer different questions.
Treating one exclusion as all three loses evidence and makes historical results irreproducible.
Defaults, presets, profiles, and audit overrides also need deterministic ownership without weakening
accepted safety boundaries.

## Decision

Use three independently evaluated decisions: discovery, metadata scoring, and sitemap. Protected
security boundaries always precede product rules. Merge settings as global default, explicitly
accepted versioned preset, administrator-managed versioned site profile, then per-audit override.
Evidence-derived decisions follow policy and remain separately attributable.

Submission records an immutable effective-settings and rule snapshot, including disabled inherited
rule IDs. Higher sources override only by explicit stable rule identity. Within one source, priority,
specificity, and stable rule ID provide ordering; unresolved same-layer conflicts become visible
review/indeterminate results. User sitemap policy contributes evidence rather than overwriting the
generated recommendation.

## Consequences

- Excluded pages may retain useful status, link, robots, canonical, and sitemap evidence.
- Operators can adjust one audit but cannot create reusable profiles.
- Historical audits remain interpretable after defaults or presets change.
- CSA-02 must implement bounded rule semantics; CSA-03 must retain decisions and snapshots.
- The rule engine cannot use “most restrictive wins” as a universal shortcut.

## Rejected alternatives

- One exclusion flag: conflates populations and loses evidence.
- Silent preset detection/application: produces unreviewed behavior.
- Textual shadowing of inherited rules: creates accidental overrides.
- User policy as the final sitemap fact: hides observed evidence and analysis provenance.
