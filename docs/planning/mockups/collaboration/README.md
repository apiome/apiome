# Collaboration mockups

Static, browser-openable design mockups for the
[Collaboration feature roadmap](../../../../docs/FUTURE_FEATURE_ROADMAP_COLLABORATION.md).

These files cover the full roadmap surface area across all four epics:
Real-Time Multiplayer Editing (Epic 1), Comments & Discussions (Epic 2),
Review & Approval Workflows (Epic 3), and Team Management & Activity (Epic 4).
They are visual references — no API calls, no auth, no WebSocket, no build step.

## Open

Either open the files directly:

```
open objectified-ui/public/mockups/collaboration/index.html
```

Or, with the Next.js dev server running, browse to:

```
http://localhost:3000/mockups/collaboration/index.html
```

## Files

| File                    | Maps to roadmap issue                                                                  |
| ----------------------- | -------------------------------------------------------------------------------------- |
| `index.html`            | Mockup hub linking to all screens, grouped by epic                                     |
| `workspace.html`        | 1.1 Live cursors · 1.2 Presence · 1.3 CRDT (Yjs) sync · 1.4 Draft mode &amp; undo/redo |
| `comments.html`         | 2.1 Inline threads · 2.4 Rich editor &amp; reactions (markdown, code, @mentions)       |
| `canvas-pins.html`      | 2.2 Canvas comment pins · 2.3 @Mentions &amp; notification routing                     |
| `change-requests.html`  | 3.1 Change request creation, lifecycle, list &amp; detail                              |
| `diff-viewer.html`      | 3.2 Side-by-side diff (split / unified / canvas) · 3.3 Review tools &amp; verdicts     |
| `approvals.html`        | 3.4 Approval workflow policies, merge gates, admin override                            |
| `teams.html`            | 4.1 Project teams, team-based permissions &amp; permission resolver                    |
| `activity.html`         | 4.2 Activity feed (project / team / personal / watching) with burst grouping           |
| `notifications.html`    | 4.3 Notification center, routing, channels, quiet hours                                |
| `integrations.html`     | 4.4 Slack &amp; Microsoft Teams bi-directional bridge, slash commands, identity link   |

## Design system

Mockups intentionally mirror the live `objectified-ui` shell and align with the
sibling `mockups/academy`, `mockups/analytics`, `mockups/architect`,
`mockups/automation`, and `mockups/code-gen` sets:

- **Typography**: Inter (400/500/600/700), JetBrains Mono for class names,
  field paths, channel names, IDs, timestamps, and quantitative stats
- **Accent**: indigo-500 / 600 (Radix `accentColor="indigo"`)
- **Gray scale**: slate (Radix `grayColor="slate"`)
- **Layout**: 260 px gradient sidebar, 48 px top platform bar, panel cards
  (`bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700`)
- **Icons**: Lucide (CDN), matching the live `lucide-react` icon set
- **Theme**: class-based dark mode toggle, persisted to `localStorage` under
  `collab-mockup-theme`. Honors `prefers-color-scheme` on first load.

## Collaboration-specific visual language

Beyond the shared shell, the Collaboration mockups introduce a few conventions
that the production build is expected to honor:

- **Presence avatars**: 28 px circular avatars in deterministic per-user colours
  (indigo, blue, emerald, purple, rose, amber, cyan, fuchsia). Stacks use
  `-space-x-2` with a `ring-2 ring-white dark:ring-gray-800` halo.
- **Live cursors**: solid coloured caret + matching pill label
  (`Alice ▎`, `Bob ▎`) drawn in absolute coordinates over the canvas.
- **CRDT health**: small status pill in the workspace header — `connected` /
  `degraded` / `offline` (emerald / amber / rose) plus latency in milliseconds.
- **Diff colours**: emerald for added lines/elements, rose for removed,
  amber for modified — used identically in `diff-viewer.html`, `activity.html`,
  and the change-request stat chips.
- **Role badges**: monochrome uppercase pills — Owner = rose, Editor = amber,
  Commenter = blue, Viewer = emerald, Team Admin = rose. These appear in the
  teams table, member lists, and the permission resolver.
- **CR status badges**: Open = blue, In review = amber, Approved = emerald,
  Changes requested = rose, Merged = purple, Closed = gray.
- **Comment threads**: left border-accent boxes (`border-l-4 border-indigo-400`)
  with markdown content; reactions render as small pill counters with the emoji.
- **Pins on canvas**: numbered circular markers in indigo with an outer
  `ring-4 ring-white dark:ring-gray-900` so they read against any node fill.
- **Timeline rails**: 1 px vertical gradient line with 20 px dots per event;
  used in `activity.html` and the change-request lifecycle in
  `change-requests.html`.

## Conventions matched from production code

Shared layout tokens come from `app/components/ade/dashboard/dashboardScreenClasses.ts`
and `app/components/ade/dashboard/DashboardSideNav.tsx`:

- Section headers in the sidebar use `text-[0.65rem]` uppercase with a 1×1 indigo dot
- Panels use `bg-gray-50 dark:bg-gray-900` for header bars
- Active nav items use a 10 % indigo fill + 1 px border + indigo text + a small
  dot indicator
- Page headers follow the `<h2>` + lucide icon + subtitle pattern from
  `dashboard/page.tsx`
- Notification badge in the top bar mirrors the live unread count chip

## What's intentionally faked

- All projects, schemas, change requests, comments, pins, teams, members,
  activity events, notifications, and integration deliveries are hard-coded
- Dropdowns, toggles, radio groups, search inputs, and tabs are visual only
- The workspace canvas and remote cursors are static SVG/HTML — there is no
  WebSocket, no Yjs document, no diff algorithm running
- The diff viewer renders pre-rendered "before" / "after" snippets — no real
  AST diff is performed
- The approval policy editor stores nothing; toggling the rules is cosmetic
- The Slack preview pane is a styled `div` mocking Slack's message blocks; the
  delivery-health sparkline is a fixed gradient
- The theme toggle and the preference-row toggles are the only working JS (plus
  Lucide icon hydration)

## Out of scope (not included)

These belong to later phases of the roadmap and were excluded from the mockup
set in favour of the screens above:

- 1.5 Voice / video huddles — surfaces as an additional pill in the workspace
  presence stack and a separate huddle drawer
- 2.5 Threaded video / Loom embeds in comments — surface as an additional
  attachment type in the rich editor in `comments.html`
- 3.5 Required CI / status checks (lint, codegen-build, contract-tests) before
  merge — would render as additional rows in the merge-preview panel of
  `approvals.html`
- 4.5 Audit log export &amp; SIEM forwarding (SOC 2) — extends `activity.html` with
  an additional export drawer
- 4.6 Granular per-class &amp; per-field permissions — extend the permission
  resolver in `teams.html` with a third resolution layer
- 4.7 SCIM / SAML JIT provisioning — admin-area screens, not part of the
  collaboration surface
