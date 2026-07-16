# 0050: Frontend design system and accessibility

Status: Accepted for `seo-toolkit-frontend-design-system-v1`.

## Decision

Use small semantic React primitives and CSS custom-property tokens for color, space, type, radius,
and elevation. Provide a responsive private-workspace shell, consistent page headers, cards,
buttons, statuses, empty states, and system-message pages without adopting a utility framework or
third-party component library. Preserve semantic landmarks, labels, visible focus, keyboard access,
reduced-motion behavior, readable contrast, and a skip link.

## Consequences

The interface has a coherent, dependency-light visual foundation that can grow through reviewed
primitives. Desktop and narrow layouts share one semantic structure. Automated component tests
cover behavior and accessible names; full cross-browser and assistive-technology validation remains
a release responsibility.
