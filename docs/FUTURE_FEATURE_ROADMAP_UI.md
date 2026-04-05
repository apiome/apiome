# Objectified: UI Enhancements - Feature Roadmap

> User interface enhancements delivering full workspace customization, WCAG 2.1 AA accessibility compliance, and guided onboarding—ensuring Objectified is usable by everyone and approachable for newcomers.
>
> **Revenue Model**: Core platform feature, accessibility compliance in all tiers
>
> **Tech Stack**: NextJS App Router, Radix UI primitives, CSS custom properties (theming), driver.js (guided tours), REST/OpenAPI 3.1, PostgreSQL
>
> **Last Updated**: April 2, 2026

---

## MVP Definition

- Theme engine with light/dark/system modes using CSS custom properties
- Customizable toolbar with drag-and-drop panel reordering
- Keyboard shortcut editor with conflict detection
- Workspace layout save/restore per user
- Full keyboard navigation across all interactive elements
- ARIA labels, roles, and focus indicators on every component
- High contrast mode and reduced motion option
- Welcome tour for new users with driver.js step-by-step walkthrough
- Quick start templates with sample project and schema import wizard
- REST API for preference and layout persistence (OpenAPI 3.1 documented)

---

## Epic 1: Theme & Workspace Customization

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 1.1 (#1332) | Theme Engine & CSS Custom Properties | Token-based theming with light/dark/system modes and custom palette support | `enhancement`, `mvp`, `ui`, `ai-generated` | Yes |
| 1.2 (#1338) | Customizable Toolbar & Panel Layout | Drag-and-drop toolbar ordering, sidebar toggling, and panel resizing | `enhancement`, `mvp`, `ui`, `ai-generated` | Yes |
| 1.3 (#1343) | Keyboard Shortcut Manager | User-configurable keyboard shortcuts with conflict detection and reset | `enhancement`, `mvp`, `ui`, `ai-generated`, `rest` | Yes |
| 1.4 (#1347) | Workspace Layout Persistence | Save, restore, and switch between named workspace layouts | `enhancement`, `mvp`, `ui`, `ai-generated`, `rest` | No |
| 1.5 (#1349) | Preference Import/Export & Team Settings | Export user preferences as JSON, import across accounts, and apply team defaults | `enhancement`, `ui`, `ai-generated`, `rest` | No |

### Detailed Issue Descriptions

---

#### 1.1 (#1332) — Theme Engine & CSS Custom Properties

The theme engine provides a design-token architecture for Objectified's entire component library. Every color, spacing value, border radius, shadow, and typographic scale is exposed as a CSS custom property under the `--obj-*` namespace. A `ThemeProvider` React context wraps the application root, reading the user's stored preference and injecting the corresponding token set into `:root`. Switching themes applies instantly without a full-page reload because the browser re-cascades custom properties in real time.

Three built-in themes ship at launch: Light, Dark, and System (follows `prefers-color-scheme`). The settings page at `/app/(platform)/settings/appearance` renders a Radix `RadioGroup` for theme selection with live preview thumbnails. Below the selector, a "Custom Palette" section surfaces six primary token overrides (primary, secondary, accent, background, surface, text) using Radix `Popover` color pickers, giving users fine-grained control over their workspace look.

```
┌────────────────────────────────────────────────────────┐
│  Appearance Settings                                   │
├────────────────────────────────────────────────────────┤
│                                                        │
│  Theme                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐            │
│  │  ☀ Light │  │  ● Dark  │  │  ◐ System│            │
│  │  ░░░░░░  │  │  ▓▓▓▓▓▓  │  │  ░▓░▓░▓  │            │
│  │  ░░░░░░  │  │  ▓▓▓▓▓▓  │  │  ░▓░▓░▓  │            │
│  └──────────┘  └──────────┘  └──────────┘            │
│                                                        │
│  Custom Palette                                        │
│  Primary:    [■ #3B82F6]   Secondary:  [■ #6366F1]   │
│  Accent:     [■ #F59E0B]   Background: [■ #FFFFFF]   │
│  Surface:    [■ #F8FAFC]   Text:       [■ #0F172A]   │
│                                                        │
│                              [Reset to Defaults]       │
└────────────────────────────────────────────────────────┘
```

Token values are persisted via `PUT /api/v1/preferences/theme` with a JSON body containing the theme name and optional overrides. On page load, the server returns the user's theme in the initial session payload to prevent a flash of unstyled content. The `ThemeProvider` also emits a `theme-changed` custom event so third-party panels or embedded widgets can react.

**Acceptance Criteria**
- CSS custom properties under `--obj-*` namespace cover all color, spacing, radius, and typography tokens
- Light, Dark, and System modes are selectable with immediate preview (no page reload)
- Custom palette overrides persist via `PUT /api/v1/preferences/theme` and load on session init
- Radix `Popover` color pickers support hex, HSL, and RGB input
- `prefers-color-scheme` media query drives System mode, updating on OS-level change
- `theme-changed` custom event fires on every switch for widget integration
- Reset button restores all tokens to the selected base theme's defaults

**Part of Epic: Theme & Workspace Customization**

---

#### 1.2 (#1338) — Customizable Toolbar & Panel Layout

The workspace layout system turns Objectified's fixed chrome into a user-arrangeable surface. The top toolbar, left sidebar, right inspector panel, and bottom console are each rendered as discrete layout slots. Users drag slot handles to reorder toolbar items, resize panels by dragging their dividers, and toggle panel visibility via a Radix `DropdownMenu` accessible from a "Layout" button in the toolbar.

Panel state is captured as a `LayoutDescriptor` JSON object: an ordered array of panel IDs, each with `visible` (boolean), `width` or `height` (number), and `collapsed` (boolean). Dragging a panel handle updates the descriptor in React state and persists it on drop via `PATCH /api/v1/preferences/layout`. Minimum panel sizes are enforced (sidebar: 200px, inspector: 250px) to prevent panels from being resized to invisibility.

```
┌────────────────────────────────────────────────────────┐
│ ☰ [Schema ▾] [Objects ▾] [API ▾]  ...  [Layout ▾] ⚙ │
├──────────┬─────────────────────────┬───────────────────┤
│          │                         │                   │
│ Sidebar  │    Main Content Area    │  Inspector Panel  │
│ ◀━━━━━▶ │                         │  ◀━━━━━━━━━━━━▶  │
│          │                         │                   │
│  200px+  │      (flexible)         │     250px+        │
│          │                         │                   │
├──────────┴─────────────────────────┴───────────────────┤
│ Console / Output                              [▲ ▼ ✕] │
└────────────────────────────────────────────────────────┘
  ◀━━━━━▶ = drag handle for resize
```

The toolbar itself supports item reordering through drag-and-drop. Each toolbar button registers with a `ToolbarRegistry`, exposing its ID, label, icon, and default position. Users reorder by holding a modifier key (Alt) and dragging, or through a dedicated "Customize Toolbar" dialog that shows all available items with checkboxes for visibility and a sortable list for order.

**Acceptance Criteria**
- Sidebar, inspector, and console panels are resizable via drag handles with enforced minimums
- Panel visibility is toggled via Radix `DropdownMenu` under the Layout toolbar button
- Toolbar item order is customizable via Alt+drag or the "Customize Toolbar" Radix `Dialog`
- Layout descriptor JSON persists via `PATCH /api/v1/preferences/layout`
- Responsive breakpoints collapse panels to overlay mode on viewports under 768px
- Double-clicking a drag handle resets that panel to its default size
- Layout changes apply immediately without page reload

**Part of Epic: Theme & Workspace Customization**

---

#### 1.3 (#1343) — Keyboard Shortcut Manager

The Keyboard Shortcut Manager lets users rebind any action in Objectified to their preferred key combination. A `ShortcutRegistry` singleton collects every registered shortcut with its action ID, default binding, context (global, editor, modal), and human-readable description. The settings page at `/app/(platform)/settings/shortcuts` renders a searchable, grouped list of shortcuts using a Radix `Accordion` per context group.

Each shortcut row displays the action name, current binding rendered as `<kbd>` elements, and an "Edit" button. Clicking Edit enters a capture mode: the next key combination pressed is recorded and displayed. The system validates against conflicts—if the new binding collides with an existing shortcut in the same context, a Radix `AlertDialog` warns the user and offers to unbind the conflicting action. Users can also clear a binding entirely, removing the keyboard trigger for that action.

Shortcut overrides are stored via `PUT /api/v1/preferences/shortcuts` as a map of `{ actionId: keyCombo }`. Only overrides are persisted; the registry fills in defaults for anything not overridden. A "Reset All" button clears all overrides. The API also supports `GET /api/v1/preferences/shortcuts` for syncing across devices.

**Acceptance Criteria**
- All registered actions appear in the shortcuts list grouped by context (global, editor, modal)
- Search input filters shortcuts by action name or current key binding
- Capture mode records the next key combination and validates for conflicts within the same context
- Conflict detection shows a Radix `AlertDialog` with the conflicting action and offers resolution
- Overrides persist via `PUT /api/v1/preferences/shortcuts` as a partial map
- "Reset All" clears overrides and restores defaults with a confirmation dialog
- Modifier keys (Ctrl/Cmd, Alt, Shift) are normalized for cross-platform display

**Part of Epic: Theme & Workspace Customization**

---

#### 1.4 (#1347) — Workspace Layout Persistence

Workspace Layout Persistence extends the panel layout system (1.2) with named, switchable layout presets. Users save their current arrangement—panel sizes, visibility, toolbar order, and active sidebar tab—as a named layout. A Radix `Select` dropdown in the toolbar lets users switch between saved layouts instantly, and a "Manage Layouts" dialog supports renaming, duplicating, and deleting saved layouts.

Layouts are stored via `POST /api/v1/preferences/layouts` (create), `GET /api/v1/preferences/layouts` (list), `PUT /api/v1/preferences/layouts/{id}` (update), and `DELETE /api/v1/preferences/layouts/{id}` (remove). Each layout record contains a `name`, the full `LayoutDescriptor` JSON, and a `is_default` flag. The system supports up to 10 saved layouts per user.

A "Quick Switch" keyboard shortcut (default: `Ctrl+Shift+L`) opens a command-palette-style popup listing saved layouts with fuzzy search. Selecting a layout applies it immediately. When a user modifies their current layout, a subtle "unsaved changes" indicator appears next to the layout name, and an auto-save option (configurable) persists changes after 5 seconds of inactivity.

**Acceptance Criteria**
- Users can save the current layout as a named preset via a Radix `Dialog`
- Layout switcher renders as a Radix `Select` in the toolbar with instant apply on selection
- Quick Switch shortcut (`Ctrl+Shift+L`) opens a fuzzy-searchable layout list
- CRUD endpoints at `/api/v1/preferences/layouts` support create, list, update, delete
- Maximum of 10 saved layouts per user enforced at the API level
- "Unsaved changes" indicator appears when the active layout diverges from its saved state
- One layout can be marked as default and loads automatically on login

**Part of Epic: Theme & Workspace Customization**

---

#### 1.5 (#1349) — Preference Import/Export & Team Settings

Preference Import/Export enables portability of a user's full configuration—theme, shortcuts, layouts, and feature toggles—as a single JSON file. The export endpoint `GET /api/v1/preferences/export` returns a versioned JSON blob with all preference categories. The import endpoint `POST /api/v1/preferences/import` accepts the same format, validates the schema version, and applies changes with a merge strategy (imported values overwrite matching keys; unmatched local keys are preserved).

The import flow at `/app/(platform)/settings/preferences` uses a Radix `Dialog` with a file picker. After selecting a JSON file, a diff preview shows which values will change before the user confirms. Import validation rejects files with unknown schema versions or malformed data, surfacing specific errors.

Team-level settings allow organization admins to define default preferences applied to new members. The admin page at `/app/(platform)/admin/team-settings` mirrors the user settings UI but writes to a `team_preferences` table via `PUT /api/v1/admin/team-preferences`. When a new user joins the tenant, their initial preferences are seeded from team defaults. Existing users can opt to re-sync with team defaults at any time via a "Reset to Team Defaults" button.

**Acceptance Criteria**
- Export endpoint returns versioned JSON containing theme, shortcuts, layouts, and feature toggles
- Import endpoint validates schema version and applies merge strategy with diff preview
- Malformed or incompatible import files surface specific validation errors in the dialog
- Team-level defaults are configurable by admins at `/api/v1/admin/team-preferences`
- New tenant members automatically receive team default preferences on account creation
- "Reset to Team Defaults" button overwrites user preferences with team values after confirmation
- Export file is human-readable JSON with inline comments describing each section

**Part of Epic: Theme & Workspace Customization**

---

## Epic 2: WCAG 2.1 AA Accessibility

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 2.1 (#1375) | Keyboard Navigation & Focus Management | Full keyboard operability with visible focus indicators and skip links | `enhancement`, `mvp`, `ui`, `ai-generated` | Yes |
| 2.2 (#1380) | Screen Reader Support & ARIA Implementation | Semantic HTML, ARIA labels, live regions, and screen reader optimizations | `enhancement`, `mvp`, `ui`, `ai-generated` | Yes |
| 2.3 (#1386) | High Contrast & Reduced Motion Modes | Accessibility display modes for vision and vestibular sensitivities | `enhancement`, `mvp`, `ui`, `ai-generated`, `rest` | Yes |
| 2.4 (#1393) | Accessibility Audit Pipeline & Contrast Checker | Automated a11y testing in CI and an in-app contrast validation tool | `enhancement`, `ui`, `ai-generated` | Yes |

### Detailed Issue Descriptions

---

#### 2.1 (#1375) — Keyboard Navigation & Focus Management

Every interactive element in Objectified must be operable via keyboard alone. This issue establishes a focus management layer that handles tab ordering, focus trapping in modals and drawers, skip links for bypassing navigation, and visible focus indicators that meet the WCAG 2.1 AA 2.4.7 "Focus Visible" criterion. The focus ring uses a 2px solid outline with a 2px offset in the current theme's accent color, ensuring 3:1 contrast against adjacent colors.

Skip links are rendered at the top of every page as visually hidden anchors that become visible on focus. The standard skip link set includes "Skip to main content," "Skip to navigation," and "Skip to search." On complex pages with multiple landmark regions, additional skip links are generated dynamically based on the page's `<section>` elements with `aria-label` attributes.

Focus trapping follows the Radix UI `FocusTrap` pattern for all dialogs, dropdown menus, and popovers. When a modal opens, focus moves to the first focusable element inside it. Pressing `Tab` at the last element wraps to the first. Pressing `Escape` closes the modal and returns focus to the trigger element. For non-modal panels (sidebar, inspector), focus is managed but not trapped—users can tab out into the main content area.

A `useFocusReturn` hook tracks the element that triggered a context switch (opening a panel, navigating to a sub-page) and restores focus to it when the user returns. This prevents the common accessibility anti-pattern of focus jumping to the top of the page after closing an overlay.

**Acceptance Criteria**
- All interactive elements are reachable via `Tab` / `Shift+Tab` in logical DOM order
- Skip links ("Skip to main content," "Skip to navigation") are visually hidden until focused
- Focus ring is 2px solid with 2px offset, meeting 3:1 contrast ratio against adjacent colors
- Modal dialogs trap focus; `Escape` closes and returns focus to the trigger element
- `useFocusReturn` hook restores focus after overlay dismissal across the application
- Arrow key navigation is implemented for toolbars, menu bars, and tab lists per WAI-ARIA patterns
- Keyboard-only mode (toggled in settings) suppresses mouse hover effects and enlarges focus indicators

**Part of Epic: WCAG 2.1 AA Accessibility**

---

#### 2.2 (#1380) — Screen Reader Support & ARIA Implementation

This issue delivers comprehensive screen reader compatibility by auditing every component for semantic HTML, adding ARIA attributes where native semantics are insufficient, and implementing live regions for dynamic content updates. Every Radix UI primitive already provides baseline ARIA support; this work extends that to custom components, composite widgets, and data-heavy views like tables and tree views.

All images and icons require `alt` text or `aria-label`. Decorative icons use `aria-hidden="true"`. Interactive icon buttons use `aria-label` describing the action ("Close dialog," "Toggle sidebar"), not the icon glyph ("X," "Hamburger"). Status badges, progress bars, and loading indicators use `aria-live` regions so screen readers announce state changes without the user needing to navigate to them. Toast notifications use `role="status"` with `aria-live="polite"` for informational messages and `role="alert"` for errors.

```
Component ARIA Audit Checklist
──────────────────────────────────────────────────
Component            Required ARIA
──────────────────────────────────────────────────
DataTable            role="grid", aria-sort on headers,
                     aria-rowcount, aria-colcount
TreeView             role="tree", role="treeitem",
                     aria-expanded, aria-level
Toolbar              role="toolbar", aria-label,
                     roving tabindex
Breadcrumb           nav aria-label="Breadcrumb",
                     aria-current="page" on last item
Toasts               role="status" | role="alert",
                     aria-live="polite" | "assertive"
Progress             role="progressbar", aria-valuenow,
                     aria-valuemin, aria-valuemax
──────────────────────────────────────────────────
```

A screen reader testing protocol is documented and run against NVDA (Windows), VoiceOver (macOS/iOS), and TalkBack (Android) for every release. Automated axe-core checks run in CI to catch regressions, but manual testing remains the authority for screen reader flow quality.

**Acceptance Criteria**
- Every page has a single `<main>` landmark with descriptive `aria-label`
- All images have `alt` text; decorative icons use `aria-hidden="true"`
- Interactive icon buttons use `aria-label` describing the action, not the glyph
- Dynamic content updates use `aria-live` regions (`polite` for info, `assertive` for errors)
- Data tables implement `role="grid"` with sortable column headers using `aria-sort`
- Screen reader testing protocol covers NVDA, VoiceOver, and TalkBack with documented results
- No information is conveyed by color alone—text labels or icons accompany every color indicator

**Part of Epic: WCAG 2.1 AA Accessibility**

---

#### 2.3 (#1386) — High Contrast & Reduced Motion Modes

High Contrast mode overrides the active theme with a token set that guarantees a minimum 7:1 contrast ratio for all text and 3:1 for all UI components (exceeding WCAG AAA for text). Borders become solid 2px, shadows are removed, and interactive elements gain distinct outlines. The mode is toggled via a Radix `Switch` in accessibility settings at `/app/(platform)/settings/accessibility` and persisted via `PUT /api/v1/preferences/accessibility`.

Reduced Motion mode respects the `prefers-reduced-motion` media query and can also be toggled manually. When active, all CSS transitions are set to `0ms`, keyframe animations are replaced with instant state changes, and auto-playing media is paused. The scroll behavior switches from `smooth` to `auto`. This accommodates users with vestibular disorders who experience motion sickness from animated interfaces.

Font scaling allows users to increase the base font size up to 200% without breaking layout. The settings page provides a Radix `Slider` from 100% to 200% in 25% increments. All component dimensions use `rem` or `em` units tied to the root font size, ensuring proportional scaling. Layout containers use `min-height` rather than fixed `height` to accommodate text reflow at larger sizes.

**Acceptance Criteria**
- High Contrast mode achieves 7:1 contrast for text and 3:1 for UI components
- High Contrast is toggleable via Radix `Switch` and persists via `PUT /api/v1/preferences/accessibility`
- Reduced Motion mode disables all CSS transitions, animations, and smooth scrolling
- `prefers-reduced-motion` media query is honored automatically; manual toggle available in settings
- Font scaling slider supports 100%–200% in 25% increments without layout breakage
- All component dimensions use relative units (`rem`/`em`) to support proportional scaling
- Settings page renders a live preview section showing the effect of each accessibility toggle

**Part of Epic: WCAG 2.1 AA Accessibility**

---

#### 2.4 (#1393) — Accessibility Audit Pipeline & Contrast Checker

The accessibility audit pipeline integrates automated a11y testing into the CI/CD workflow. Every pull request runs axe-core via `@axe-core/playwright` against a representative set of pages (login, dashboard, schema editor, settings). Violations at the "critical" or "serious" level fail the build. Results are posted as a PR comment summarizing pass/fail counts and linking to detailed violation reports.

An in-app contrast checker tool is available in the developer toolbar at `/app/(platform)/dev-tools/contrast`. Users enter foreground and background hex values, and the tool calculates the WCAG contrast ratio, displaying pass/fail for AA and AAA levels at normal and large text sizes. The checker also accepts a URL to a live page and overlays contrast violation markers on elements that fail the configured threshold.

```
┌────────────────────────────────────────────────┐
│  Contrast Checker                              │
├────────────────────────────────────────────────┤
│                                                │
│  Foreground: [#0F172A]  Background: [#F8FAFC] │
│                                                │
│  Contrast Ratio: 17.4:1                        │
│                                                │
│  AA Normal Text (4.5:1)    ✓ Pass              │
│  AA Large Text  (3:1)     ✓ Pass              │
│  AAA Normal Text (7:1)    ✓ Pass              │
│  AAA Large Text  (4.5:1)  ✓ Pass              │
│                                                │
│  [Scan Current Page]                           │
└────────────────────────────────────────────────┘
```

A nightly scheduled audit runs the full axe-core suite against all application routes, generating a trend report stored in PostgreSQL. The accessibility dashboard at `/app/(platform)/admin/accessibility` shows violation trends over time, current violation count by severity, and a list of pages with outstanding issues. This enables proactive regression tracking beyond per-PR checks.

**Acceptance Criteria**
- axe-core runs in CI on every PR against login, dashboard, schema editor, and settings pages
- Critical and serious violations fail the PR build; moderate violations are reported as warnings
- PR comment summarizes pass/fail counts with links to detailed violation output
- In-app contrast checker calculates WCAG ratio and shows AA/AAA pass/fail for entered colors
- "Scan Current Page" overlays violation markers on failing elements with fix suggestions
- Nightly audit generates trend data; accessibility dashboard shows violation counts over time
- Audit results are stored in PostgreSQL with page URL, violation rule, severity, and timestamp

**Part of Epic: WCAG 2.1 AA Accessibility**

---

## Epic 3: Onboarding & Guided Tutorials

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 3.1 (#1416) | Welcome Tour & Feature Discovery | driver.js guided walkthrough for first-time users with step-by-step highlights | `enhancement`, `mvp`, `ui`, `ai-generated` | Yes |
| 3.2 (#1421) | Interactive Tutorial Engine | Step-by-step in-app tutorials with validation, contextual help, and video embeds | `enhancement`, `mvp`, `ui`, `ai-generated`, `rest` | No |
| 3.3 (#1428) | Quick Start Templates & Import Wizard | Sample projects, pre-built schemas, and a guided import flow for new workspaces | `enhancement`, `mvp`, `ui`, `ai-generated`, `rest` | Yes |
| 3.4 (#1433) | Achievement & Learning Progress System | Badges and checklists rewarding feature exploration and tutorial completion | `enhancement`, `ui`, `ai-generated`, `rest` | No |

### Detailed Issue Descriptions

---

#### 3.1 (#1416) — Welcome Tour & Feature Discovery

The Welcome Tour activates on a user's first login (tracked via a `has_completed_tour` flag on the user profile). It uses driver.js to render a multi-step overlay that highlights key UI regions: the sidebar navigation, the schema editor, the API explorer, and the settings panel. Each step includes a title, a 1-2 sentence description, and a "Next" / "Skip Tour" button pair. The tour completes by pointing to the help menu and the Quick Start section.

Feature discovery prompts surface contextually when a user encounters a feature for the first time. For example, the first time a user opens the schema editor, a subtle Radix `Popover` tooltip appears explaining keyboard shortcuts for that context. Discovery prompts are tracked per feature per user via a `feature_discoveries` table, ensuring each prompt fires only once. Users can disable discovery prompts entirely in settings.

```
┌──────────────────────────────────────────────────────────┐
│                                                          │
│         Step 2 of 5: Schema Editor                       │
│    ┌──────────────────────────────────────────────┐      │
│    │ ╔══════════════════════════════════════════╗  │      │
│    │ ║  This is the Schema Editor.              ║  │      │
│    │ ║  Define your data models, set            ║  │      │
│    │ ║  validations, and generate APIs          ║  │      │
│    │ ║  from a single source of truth.          ║  │      │
│    │ ║                                          ║  │      │
│    │ ║  [◀ Back]              [Next ▶] [Skip]   ║  │      │
│    │ ╚══════════════════════════════════════════╝  │      │
│    │  ▲ (highlighted region)                      │      │
│    └──────────────────────────────────────────────┘      │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

Tour definitions are stored in a `tour_definitions` table with step arrays (JSON), enabling admins to update tour content without code deploys. The REST endpoint `POST /api/v1/onboarding/tour/complete` marks the tour as finished. `GET /api/v1/onboarding/tour/status` returns the user's current tour state, including which step they left off on if they dismissed early, supporting tour resumption.

**Acceptance Criteria**
- Welcome tour activates automatically on first login and is dismissible at any step
- driver.js highlights each target element with a popover description and step counter
- Tour state persists via `POST /api/v1/onboarding/tour/complete` and `GET /api/v1/onboarding/tour/status`
- Feature discovery prompts fire once per feature per user via contextual Radix `Popover`
- Discovery prompts can be globally disabled via user settings
- Tour definitions are stored in the database and editable by admins without code changes
- Tour resumes from the last incomplete step if the user dismissed partway through

**Part of Epic: Onboarding & Guided Tutorials**

---

#### 3.2 (#1421) — Interactive Tutorial Engine

The Interactive Tutorial Engine extends the tour system into multi-step guided exercises that teach users by doing. Each tutorial is a sequence of steps where the user performs an action (click a button, fill a field, navigate to a page) and the engine validates the action before advancing. This learn-by-doing approach has dramatically higher retention than passive documentation.

Tutorial definitions are stored in a `tutorials` table with step arrays in JSONB. Each step has a `type` (highlight, action, input, navigation), a `target` CSS selector, an `instruction` string, and optional `validation` criteria (element visible, value matches, URL matches). The tutorial runner renders a persistent bottom bar showing progress, the current instruction, and contextual help. Video embeds (hosted or YouTube iframes) can be attached to any step for supplementary visual guidance.

The tutorial catalog page at `/app/(platform)/learn/tutorials` lists available tutorials using Radix `Card` components with estimated completion time, difficulty badge, and completion status. Tutorials are tagged by feature area (schemas, API, settings) and filterable. REST endpoints include `GET /api/v1/onboarding/tutorials` (catalog), `GET /api/v1/onboarding/tutorials/{id}` (detail with steps), and `POST /api/v1/onboarding/tutorials/{id}/progress` (record step completion).

**Acceptance Criteria**
- Tutorial steps validate user actions (clicks, input, navigation) before advancing
- Step types include highlight, action (click target), input (enter value), and navigation (visit URL)
- Persistent bottom bar shows current step instruction, progress counter, and skip option
- Video embeds can be attached to any tutorial step for supplementary guidance
- Tutorial catalog page lists tutorials with completion status, estimated time, and difficulty
- Progress persists via `POST /api/v1/onboarding/tutorials/{id}/progress` per user per step
- Contextual help tooltips appear on the target element for each step

**Part of Epic: Onboarding & Guided Tutorials**

---

#### 3.3 (#1428) — Quick Start Templates & Import Wizard

Quick Start Templates provide pre-built sample projects that give new users a populated workspace to explore immediately. Templates cover common use cases: "E-commerce API" (product, order, customer schemas), "Blog Platform" (post, author, comment schemas), and "SaaS Starter" (user, organization, subscription schemas). Each template includes schemas, sample data, and pre-configured API endpoints.

The Quick Start page at `/app/(platform)/onboarding/quick-start` renders template cards with a preview of included schemas and an "Apply Template" button. Applying a template creates a new project populated with the template's schemas, sample records, and configuration. Templates are stored in a `project_templates` table with `schema_snapshot` (JSONB), `sample_data` (JSONB), and `config` (JSONB) columns. REST endpoints: `GET /api/v1/onboarding/templates` (list) and `POST /api/v1/onboarding/templates/{id}/apply` (create project from template).

The Import Wizard at `/app/(platform)/onboarding/import` guides users through importing existing data into Objectified. A four-step flow uses Radix `Tabs` for navigation: (1) Select Source—file upload (JSON, CSV, SQL dump) or connect to an external database, (2) Schema Detection—auto-infer schemas from the imported data with a preview table, (3) Mapping—adjust detected field names and types using editable Radix `Table` rows, (4) Confirm & Import—review summary and execute the import with a progress bar.

**Acceptance Criteria**
- At least 3 sample project templates are available (E-commerce, Blog, SaaS Starter)
- "Apply Template" creates a fully populated project with schemas, sample data, and API config
- Template catalog endpoint `GET /api/v1/onboarding/templates` returns templates with preview metadata
- Import Wizard supports JSON, CSV, and SQL dump file uploads with auto-schema detection
- Schema detection preview shows inferred field names and types in an editable table
- Import progress is tracked with a Radix `Progress` bar and per-record error reporting
- Setup checklist on the dashboard tracks completion of key onboarding steps (create project, define schema, test API)

**Part of Epic: Onboarding & Guided Tutorials**

---

#### 3.4 (#1433) — Achievement & Learning Progress System

The Achievement System gamifies onboarding by awarding badges when users complete key milestones during their initial experience and beyond. Achievements include "First Schema" (create a schema), "API Explorer" (make a test API call), "Customizer" (change a theme setting), "Keyboard Ninja" (set a custom shortcut), and "Tutorial Graduate" (complete all tutorials). Each achievement has an icon, name, description, and unlock criteria stored in an `achievements` table.

Achievement evaluation runs asynchronously after tracked events (schema creation, API call, settings change). A lightweight event bus publishes domain events, and an achievement evaluator subscribes, checking unlock criteria against the user's cumulative actions. Unlocked achievements trigger a Radix `Toast` notification with the badge icon and name, and a celebratory animation (respecting reduced motion preferences).

The user's achievement profile at `/app/(platform)/profile/achievements` displays earned and locked badges in a grid. Earned badges show the unlock date; locked badges show a progress hint (e.g., "Complete 2 more tutorials"). A getting-started checklist widget on the dashboard tracks critical onboarding steps—creating a project, defining a schema, testing an API endpoint—and collapses once all items are checked.

**Acceptance Criteria**
- At least 5 built-in achievements covering schema, API, settings, shortcuts, and tutorial milestones
- Achievement unlock criteria stored in the `achievements` table as evaluable JSON conditions
- Event-driven evaluation triggers asynchronously after tracked domain events
- Unlock notification renders as a Radix `Toast` with badge icon and animation (motion-safe)
- Profile page shows earned badges with dates and locked badges with progress hints
- Getting-started checklist widget on dashboard tracks and auto-checks onboarding steps
- `GET /api/v1/onboarding/achievements` returns earned and available achievements for the user

**Part of Epic: Onboarding & Guided Tutorials**

---

## Parallel Work Guide

**Epic 1 — Theme & Workspace Customization:**
Issues 1.1 (Theme Engine), 1.2 (Toolbar & Panel Layout), and 1.3 (Keyboard Shortcut Manager) can be developed in parallel as they operate on independent UI systems and API endpoints. Issue 1.4 (Layout Persistence) depends on 1.2 for the layout descriptor format. Issue 1.5 (Import/Export & Team Settings) depends on 1.1, 1.3, and 1.4, since it exports all preference categories.

**Epic 2 — WCAG 2.1 AA Accessibility:**
All four issues (2.1 through 2.4) can be developed in parallel. Keyboard navigation (2.1), screen reader support (2.2), high contrast and reduced motion modes (2.3), and the audit pipeline (2.4) address independent accessibility concerns. Issue 2.4's CI pipeline should be integrated early so other issues benefit from automated regression checks.

**Epic 3 — Onboarding & Guided Tutorials:**
Issues 3.1 (Welcome Tour) and 3.3 (Quick Start Templates) can be developed in parallel as they address independent onboarding paths. Issue 3.2 (Tutorial Engine) depends on 3.1 for the driver.js integration pattern and tour infrastructure. Issue 3.4 (Achievements) depends on 3.2 for tutorial completion events that trigger badge unlocks.

**Cross-Epic Parallelism:** All three epics can begin simultaneously. Epic 2 (Accessibility) is entirely independent and should start immediately to establish the a11y audit pipeline (2.4) early. Epic 1 (Theme & Customization) and Epic 3 (Onboarding) are independent of each other. Issue 2.3 (High Contrast) should coordinate with 1.1 (Theme Engine) to share the CSS custom property infrastructure. Issue 3.1 (Welcome Tour) can reference final UI from Epics 1 and 2 but does not block on them—tour step targets are CSS selectors that can be updated later.
