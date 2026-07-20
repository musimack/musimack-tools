# Accessibility review

## Coverage

The review covered sign-in, overview, primary/mobile navigation, jobs, history, artifacts, settings,
website-migration QA, permission denial, loading, and empty states. It used the trusted local HTTPS
environment at 1440x900, 1280x720, 1024x768, 768x1024, 390x844, and 360x800, plus existing frontend
component and route tests.

## Results

- Keyboard and focus: the skip link is first in document structure, interactive elements use native
  controls, the mobile menu reports expanded state, and the design system supplies a visible 3px
  focus treatment. No keyboard-only workflow depends on pointer coordinates.
- Structure: each reviewed application page had one main landmark, a single page-level heading, a
  labelled primary navigation landmark, and a consistent heading hierarchy. System pages preserve a
  clear heading and recovery link.
- Forms and errors: reviewed inputs have programmatic labels; required/invalid state and bounded
  messages are rendered without exposing credentials. Loading uses status semantics and controls
  have accessible names.
- Tables and dense content: table components use header cells and place horizontal overflow inside
  their own responsive container. Empty collections use named headings and explanatory text rather
  than blank tables.
- Dialogs and focus: existing dialog components use dialog semantics, labelled titles, Escape/close
  behavior, initial focus, and focus return under component tests. No clipped dialog or mobile-menu
  overlap was observed in reviewed states.
- Color and motion: state text/icons accompany color, focus is not color-only, design tokens preserve
  legible foreground/background pairs, and reduced-motion media rules disable nonessential motion.
- Responsive/zoom proxy: no reviewed page produced page-level horizontal overflow or hid a primary
  action at the six required viewports. Mobile navigation remained reachable and content was not
  covered by sticky UI.

## Limitations and blocking status

No blocking accessibility barrier was found for the internal release candidate. Exhaustive testing
with every screen reader/browser pair, browser restart, populated very-large tables, and an external
scanner was outside this dependency-free, local-only phase. This is recorded as KL-005 and must be
reassessed before materially expanding the audience or UI complexity.
