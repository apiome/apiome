# Objectified: Browse - Feature Roadmap

> A public-facing viewer for published OpenAPI, Arazzo, and JSON Schema specifications. Browse enables teams to share, compare, and consume API contracts without a login — supporting tenant → project → version navigation, side-by-side diff, Monaco-based spec viewing, and embedded widgets for external documentation portals.
>
> **Revenue Model**: Browse is included in all Objectified tiers; advanced features (embed widget, private spec auth, white-label domain, analytics dashboard) are gated at Pro/Enterprise; API contract hosting fees apply at scale.
>
> **Tech Stack**: NextJS App Router, Monaco Editor, Radix UI, PostgreSQL (read-replica), OpenAPI 3.1, Playwright (E2E), Prometheus, Docker multi-stage builds

---

## MVP Definition

- Fragment deep links (`#/paths/~1users`) scroll/jump to the correct spec section on load
- Open Graph meta tags on version and compare pages for rich Slack/social previews
- Collapsible outline/tree panel listing paths, schemas, and top-level keys with click-to-scroll
- "Go to path/schema" quick-jump input (keyboard shortcut `Ctrl+G`)
- Inline spec validation errors shown in the Monaco gutter with a dedicated Lint tab
- Breaking changes flagged and visually highlighted in the diff view (removed path, removed required field)
- Shortcut help modal (`?` key) listing all keyboard shortcuts with their current key bindings
- Global keyboard shortcuts: `Ctrl+K` quick search, `Ctrl+F` search in spec, `Esc` close modals

---

## Epic 1 (#2110): Discovery & Navigation

### Summary Table

| #    | Title                                     | Description                                                                            | Labels                                      | MVP | Parallel |
|------|-------------------------------------------|----------------------------------------------------------------------------------------|---------------------------------------------|-----|----------|
| 1.1 (#2111) | Fragment Deep Links & Canonical URLs      | Hash-based scroll/jump to spec sections; stable canonical URL redirects                | `enhancement`, `mvp`, `browser`             | Yes | No       |
| 1.2 (#2112) | Open Graph Meta Tags & QR Code            | Rich social previews (OG title/desc/image) on version and compare pages; QR generator | `enhancement`, `mvp`, `browser`             | Yes | Yes      |
| 1.3 (#2113) | Related Specs ("Referenced by")           | Surface cross-spec $ref relationships within the same tenant                           | `enhancement`, `browser`                    | No  | Yes      |
| 1.4 (#2114) | Browse by Tag / Category                  | Filter and group tenant/project pages by tag; tag-based discovery index                | `enhancement`, `browser`                    | No  | Yes      |
| 1.5 (#2115) | Sitemap, Index & RSS/Atom Feeds           | Machine-readable sitemap of public specs; per-tenant RSS/Atom feeds for new versions   | `enhancement`, `browser`, `rest`            | No  | Yes      |

### Detailed Issue Descriptions

#### 1.1 (#2111) — Fragment Deep Links & Canonical URLs

The spec viewer must respond to `#`-based URL fragments to scroll and focus the relevant node in the Monaco editor or outline tree when the page loads or when the fragment changes. Fragment format follows the JSON Pointer spec: `#/paths/~1users/get`, `#/components/schemas/User`. The outline panel updates its active node to reflect the current fragment as the user scrolls.

Canonical URL handling ensures old slugs (e.g. before a project rename) permanently redirect (HTTP 301) to the current canonical form: `/{tenant}/{project}/{version}`. All generated share links use canonical paths, preventing dead links in bookmarks or documentation portals.

```
URL: /acme/payments-api/v2.1.0#/paths/~1charges/post

On load:
  ┌─────────────────────────────────────────────────────┐
  │ Outline Panel         │ Monaco Editor                │
  │ ▶ paths               │                              │
  │   ▶ /charges    ◀───  │  // scrolled & highlighted   │
  │     ● POST      ◀─── ─┤  POST /charges               │
  │   ▶ /refunds          │                              │
  └─────────────────────────────────────────────────────┘

Fragment update on scroll → pushState (debounced 300ms)
```

**Acceptance Criteria:**
- Page load with `#/paths/~1foo` scrolls Monaco editor to and highlights that path within 300ms
- Scrolling the editor updates the URL fragment (debounced, no history spam)
- Outline panel active item tracks current fragment
- Renamed project/tenant slugs return 301 to canonical URL
- Fragment links survive copy-paste and external link click

**Tech Stack:** NextJS App Router route segments, `window.location.hash`, Monaco `revealLineInCenter`, `history.replaceState`

Part of Epic: Discovery & Navigation

---

#### 1.2 (#2112) — Open Graph Meta Tags & QR Code

Every version page and compare page must emit correct `<meta>` tags so that link previews in Slack, X, LinkedIn, and messaging apps show the spec name, version, description, and a generated preview image. A simple share menu within the page exposes a QR code for the current URL.

The OG image is generated server-side (or via an edge function) as a 1200×630 PNG using `@vercel/og` or equivalent, rendering the tenant name, project name, version, and spec type badge.

```
<meta property="og:title"       content="Payments API v2.1.0 — Acme" />
<meta property="og:description" content="OpenAPI 3.1 · 24 paths · Published 2026-01-15" />
<meta property="og:image"       content="https://app/api/og?tenant=acme&project=payments-api&version=v2.1.0" />
<meta property="og:url"         content="https://app/acme/payments-api/v2.1.0" />
<meta name="twitter:card"       content="summary_large_image" />
```

**Acceptance Criteria:**
- All version pages include valid OG and Twitter card meta tags
- OG image endpoint returns 1200×630 PNG within 500ms
- Share menu includes "Copy link" and QR code (SVG, downloadable)
- Compare pages include both version identifiers in the OG title
- Meta tags pass Open Graph debugger validation

**Tech Stack:** NextJS `generateMetadata`, `@vercel/og` or `satori`, `qrcode` npm package

Part of Epic: Discovery & Navigation

---

#### 1.3 (#2113) — Related Specs ("Referenced by")

When a published spec contains `$ref` URIs pointing to another known published spec within the same tenant, the version detail page surfaces a "Referenced by" and "Depends on" section. Resolving external `$ref`s happens at publish time (stored in a `spec_dependency` table), so the browse UI performs a simple lookup rather than re-parsing at render time.

```
┌─────────────────────────────────────────────┐
│ Payments API v2.1.0                         │
├─────────────────────────────────────────────┤
│ Depends on:                                 │
│  • Common Types v1.0.0  (JSON Schema)  →    │
│                                             │
│ Referenced by:                              │
│  • Checkout API v3.0.0  (OpenAPI 3.1)  →    │
│  • Billing Portal v1.2.0 (Arazzo)      →    │
└─────────────────────────────────────────────┘
```

**Acceptance Criteria:**
- `spec_dependency` table populated at version publish time with resolved cross-spec refs
- Version page shows "Depends on" and "Referenced by" cards when dependencies exist
- Clicking a dependency card navigates to that version's browse page
- No real-time `$ref` resolution at browse time — all from pre-computed table
- Self-referential or circular refs handled without infinite loop

**Tech Stack:** PostgreSQL `spec_dependency` table, backend resolver at publish time, REST `GET /api/v1/versions/:id/dependencies`

Part of Epic: Discovery & Navigation

---

#### 1.4 (#2114) — Browse by Tag / Category

Project and version entities gain optional tags (stored in a `project_tag` junction table). The tenant home page and global discovery index support filtering and grouping by tag. Tag values are free-form strings normalized to lowercase, deduplicated at the tenant level.

**Acceptance Criteria:**
- Tenant admins can assign tags to projects via API and UI
- Tenant browse page shows tag filter chips; selecting a tag filters the project list
- Tag index page lists all tags across a tenant with project counts
- Tag slugs are URL-safe: `api-gateway`, `internal`, `v2`
- Tags are indexed in `project_tag(tag, tenant_id)` for efficient filtered queries

**Tech Stack:** PostgreSQL `project_tag` table, REST `GET /api/v1/tenants/:id/tags`, NextJS `useSearchParams` for filter state

Part of Epic: Discovery & Navigation

---

#### 1.5 (#2115) — Sitemap, Index & RSS/Atom Feeds

A machine-readable sitemap (`/sitemap.xml`) lists all public tenant/project/version URLs for search engine indexing. Per-tenant RSS and Atom feeds (`/{tenant}/feed.rss`, `/{tenant}/feed.atom`) emit new published versions ordered by publish date, enabling external tools (documentation portals, CI monitors) to subscribe to API contract updates.

**OpenAPI Endpoints:**
```
GET /api/v1/tenants/:slug/feed.rss
  → 200: application/rss+xml

GET /api/v1/tenants/:slug/feed.atom
  → 200: application/atom+xml

GET /sitemap.xml
  → 200: application/xml
```

**Acceptance Criteria:**
- Sitemap regenerated on version publish (or on a 5-minute cache schedule)
- RSS/Atom feeds include item per published version with title, link, description, pubDate
- Feeds respect tenant privacy settings (private tenants omitted from sitemap)
- Feed URLs are linked via `<link rel="alternate">` in tenant HTML pages

**Tech Stack:** NextJS route handlers, `feed` npm package, PostgreSQL read-replica for version queries

Part of Epic: Discovery & Navigation

---

## Epic 2 (#2116): Specification Viewing & Editor UX

### Summary Table

| #    | Title                                    | Description                                                                          | Labels                                      | MVP | Parallel |
|------|------------------------------------------|--------------------------------------------------------------------------------------|---------------------------------------------|-----|----------|
| 2.1 (#2117) | Outline / Tree Panel & Split View        | Collapsible tree of paths/schemas; split layout with outline left, Monaco right      | `enhancement`, `mvp`, `browser`             | Yes | No       |
| 2.2 (#2118) | Go-to-Path/Schema & In-spec Bookmarks    | Quick-jump input (Ctrl+G) and named bookmarks per user session                       | `enhancement`, `mvp`, `browser`             | Yes | Yes      |
| 2.3 (#2119) | Breadcrumb in Spec                       | Live breadcrumb showing current cursor location in the JSON/YAML structure           | `enhancement`, `browser`                    | No  | Yes      |
| 2.4 (#2120) | Paste-and-View & URL-to-Spec Playground  | Client-side spec viewer from pasted content or a remote URL (no save)               | `enhancement`, `browser`                    | No  | Yes      |
| 2.5 (#2121) | Inline Validation & Lint Panel           | Gutter markers for OpenAPI 3.x errors; dedicated Lint tab with jump-to links        | `enhancement`, `mvp`, `browser`             | Yes | No       |
| 2.6 (#2122) | Deprecated Surface & Required Marking    | Strikethrough/badge on deprecated ops/schemas; visual required vs optional in schema | `enhancement`, `browser`                    | No  | Yes      |
| 2.7 (#2123) | Examples Tab & "Copy as" Snippets        | List spec examples with copy; copy operation as cURL/fetch/axios template            | `enhancement`, `browser`                    | No  | Yes      |

### Detailed Issue Descriptions

#### 2.1 (#2117) — Outline / Tree Panel & Split View

A collapsible sidebar displays the spec as a navigable tree. For OpenAPI specs: top-level nodes are "Info", "Paths" (with each path and HTTP method as children), "Components" (with Schemas, Parameters, Responses, Security Schemes). For JSON Schema: top-level properties and `$defs`. For Arazzo: workflow steps.

Clicking any node scrolls the Monaco editor to that section and updates the URL fragment. The tree auto-expands the path group of the currently visible Monaco section. A split-view toggle shows the outline on the left (~25% width) and Monaco on the right.

```
┌──────────────────┬────────────────────────────────────┐
│ Outline          │ Monaco Editor                       │
├──────────────────┤                                     │
│ ▼ paths          │  paths:                             │
│   ▼ /charges     │    /charges:                        │
│     ● get        │      post:         ◀── cursor here  │
│     ● post  ◀──  │        summary: Create charge       │
│   ▶ /refunds     │        ...                          │
│ ▼ components     │                                     │
│   ▶ schemas      │                                     │
│   ▶ responses    │                                     │
└──────────────────┴────────────────────────────────────┘
```

**Acceptance Criteria:**
- Outline renders within 100ms of spec load for specs up to 5,000 lines
- Clicking a tree node scrolls Monaco and updates the URL fragment
- Tree tracks Monaco scroll position and auto-expands the active group
- Split-view layout persists across page navigations (localStorage)
- Outline is keyboard navigable (arrow keys to expand/collapse, Enter to jump)

**Tech Stack:** Monaco `onDidScrollChange`, recursive React tree component, `localStorage` for layout preference

Part of Epic: Specification Viewing & Editor UX

---

#### 2.2 (#2118) — Go-to-Path/Schema & In-spec Bookmarks

A quick-jump input (`Ctrl+G` or toolbar button) opens a fuzzy-search dropdown over all paths and schema names in the current spec. Typing `/users` narrows to path entries; typing `User` narrows to schema entries. Selecting an item scrolls Monaco and updates the URL fragment.

Bookmarks allow users to save named positions within a spec (stored in `sessionStorage` or `localStorage` keyed by `{tenant}/{project}/{version}`). A bookmark panel shows saved positions with rename and delete controls.

```
Ctrl+G → opens quick-jump:
┌─────────────────────────────────────────┐
│ > /users                                │
│  ─────────────────────────────          │
│  ● GET    /users          (paths)       │
│  ● POST   /users          (paths)       │
│  ● GET    /users/{id}     (paths)       │
│  ● Schema User            (components) │
└─────────────────────────────────────────┘
```

**Acceptance Criteria:**
- Quick-jump opens in <50ms and shows results as the user types (debounced 100ms)
- Fuzzy matching handles partial paths and schema name prefixes
- Results grouped by "Paths" and "Schemas"
- Bookmarks persist in `localStorage` per version; maximum 20 bookmarks per version
- Bookmark panel accessible from outline panel header

**Tech Stack:** `fuse.js` for fuzzy matching, `localStorage`, Radix UI Popover for quick-jump UI

Part of Epic: Specification Viewing & Editor UX

---

#### 2.5 (#2121) — Inline Validation & Lint Panel

When a published spec is viewed, run OpenAPI 3.x validation client-side using `@stoplight/spectral-core` (or `@readme/openapi-parser`). Validation errors and warnings appear as gutter icons in Monaco (red circle = error, yellow triangle = warning). Hovering a gutter icon shows the rule name and message.

A dedicated "Lint" tab beneath the editor lists all issues in a table with columns: Severity, Line, Rule, Message. Clicking a row jumps Monaco to that line.

```
Lint Tab:
┌────────────┬──────┬──────────────────────────┬──────────────────────────────┐
│ Severity   │ Line │ Rule                     │ Message                      │
├────────────┼──────┼──────────────────────────┼──────────────────────────────┤
│ ● error    │  42  │ oas3-schema              │ must have required property  │
│ ▲ warning  │  87  │ operation-operationId    │ Operation must have operationId│
│ ▲ warning  │ 142  │ info-contact             │ Info object must have contact │
└────────────┴──────┴──────────────────────────┴──────────────────────────────┘
```

**Acceptance Criteria:**
- Validation runs in a Web Worker to avoid blocking the main thread
- Gutter markers appear within 500ms of spec load for specs up to 10,000 lines
- Lint tab shows total error and warning counts in the tab label
- Clicking any row in the Lint tab scrolls Monaco to that line
- Lint results cleared and re-run if spec content changes (future edit mode)

**Tech Stack:** `@stoplight/spectral-core` in a Web Worker, Monaco `editor.createModel` with `deltaDecorations` for gutter markers

Part of Epic: Specification Viewing & Editor UX

---

#### 2.3 (#2119) — Breadcrumb in Spec

A breadcrumb bar below the outline panel header (or above the Monaco editor) shows the JSON/YAML path of the Monaco cursor position, updating as the cursor moves (debounced 200ms). Example: `paths → /users → post → responses → 200 → content`.

**Acceptance Criteria:**
- Breadcrumb updates within 200ms of cursor movement
- Clicking a breadcrumb segment scrolls Monaco to that level's opening key
- Breadcrumb handles deeply nested paths (truncates middle with `…` if > 6 segments)
- Works for OpenAPI, Arazzo, and JSON Schema specs

**Tech Stack:** Monaco `onDidChangeCursorPosition`, YAML path resolution at cursor offset

Part of Epic: Specification Viewing & Editor UX

---

#### 2.4 (#2120) — Paste-and-View & URL-to-Spec Playground

A "Playground" mode (accessible via toolbar button or `/browse/playground`) lets users paste raw JSON or YAML into a textarea or load a spec from a URL they provide. The content is rendered in the same Monaco viewer with outline, validation, and diff — entirely client-side, with nothing persisted.

URL-to-spec fetches the remote URL via a server-side proxy to handle CORS and validate the content type before streaming to the client.

**OpenAPI Endpoints:**
```
POST /api/v1/browse/proxy-fetch
  Body: { url: string }
  → 200: { content: string, content_type: string }
  → 400: { error: "Invalid URL or content type" }
```

**Acceptance Criteria:**
- Paste area accepts JSON and YAML; format auto-detected
- Playground state stored in URL (base64-encoded if small; sessionStorage if large)
- URL proxy validates that the response Content-Type is JSON or YAML before returning
- All playground processing is client-side; no spec content stored server-side
- "Share playground" copies a URL that restores the same spec view

**Tech Stack:** NextJS API route for proxy, `js-yaml` for YAML parsing, `btoa`/`atob` for URL encoding

Part of Epic: Specification Viewing & Editor UX

---

#### 2.6 (#2122) — Deprecated Surface & Required Marking

Operations marked `deprecated: true` in an OpenAPI spec receive a visual badge (⚠ Deprecated) in the outline tree and a strikethrough style in the path list. Schema properties in the rendered schema view are visually grouped: required properties shown first with a bold label, optional properties shown with a muted label and "(optional)" suffix.

**Acceptance Criteria:**
- Deprecated operations show ⚠ badge in outline and path list
- Schema viewer renders required properties before optional in each object
- Required properties display bold label; optional display muted "(optional)" annotation
- Deprecated schemas in `components/schemas` are similarly badged in the outline
- No change to the raw spec content — display-layer only

Part of Epic: Specification Viewing & Editor UX

---

#### 2.7 (#2123) — Examples Tab & "Copy as" Snippets

An "Examples" tab lists all examples declared in the spec (inline `example`, `examples` map, `x-examples` extension) with their path context (e.g. `POST /charges → 200 response → application/json`). Each example is displayed in a syntax-highlighted code block with a one-click copy button.

A "Copy as" menu on each operation card offers: cURL, `fetch` (TypeScript), `axios` (JavaScript), Python `requests`. Templates are generated from the operation's parameters, request body schema, and server URL.

**Acceptance Criteria:**
- Examples tab shows all examples with source path context
- Copy button copies the raw example JSON/YAML to clipboard with toast confirmation
- "Copy as cURL" generates a valid curl command with all required headers and body
- "Copy as fetch" generates typed TypeScript using the operation's operationId as the function name
- Template generation handles path parameters, query parameters, and request body

**Tech Stack:** Client-side template engine, `navigator.clipboard.writeText`, Radix UI DropdownMenu for "Copy as" options

Part of Epic: Specification Viewing & Editor UX

---

## Epic 3 (#2124): Version Comparison & Diff

### Summary Table

| #    | Title                                   | Description                                                                              | Labels                                      | MVP | Parallel |
|------|-----------------------------------------|------------------------------------------------------------------------------------------|---------------------------------------------|-----|----------|
| 3.1 (#2125) | Compare with Previous & Three-way View  | One-click "compare with previous"; support comparing 3+ versions in a single view        | `enhancement`, `browser`                    | No  | No       |
| 3.2 (#2126) | Section-scoped & Semantic Diff          | Filter diff to Paths/Schemas/Security; group changes by OpenAPI construct               | `enhancement`, `browser`                    | No  | Yes      |
| 3.3 (#2127) | Breaking-change Highlight               | Flag and visually mark breaking changes (removed path, removed required field) in diff   | `enhancement`, `mvp`, `browser`             | Yes | Yes      |
| 3.4 (#2128) | Diff Report Export & Change Navigation  | Export diff as PDF/Markdown; next/previous change buttons and keyboard shortcuts         | `enhancement`, `browser`                    | No  | Yes      |
| 3.5 (#2129) | Changelog View & Version Timeline       | Human-readable changelog from diffs; visual timeline with hover preview                  | `enhancement`, `browser`                    | No  | No       |

### Detailed Issue Descriptions

#### 3.3 (#2127) — Breaking-change Highlight

Parse both sides of a diff and classify each change as breaking or non-breaking using established OpenAPI breaking-change rules. Breaking changes are highlighted in the diff view with a red "⚠ Breaking" badge and a dedicated "Breaking Changes" summary panel above the diff.

Breaking change rules (non-exhaustive):
- Path removed
- HTTP method removed from existing path
- Required request body property added
- Required path/query parameter added
- Response property type changed
- Response status code removed
- `enum` value removed

```
Breaking Changes Summary (3 found):
┌──────────────────────────────────────────────────────────┐
│ ⚠ DELETE /users/{id} — path removed                     │
│ ⚠ POST /charges — required field `currency` added       │
│ ⚠ GET /users — query param `status` now required        │
└──────────────────────────────────────────────────────────┘

In diff view:
- [breaking] DELETE /users/{id}            ← red badge
+ POST /charges:
+   requestBody:
+     required: true
+     content: ...
```

**Acceptance Criteria:**
- Breaking change detection runs client-side using a rule engine against the parsed diff AST
- Summary panel lists all breaking changes with a one-click jump to the diff location
- Each breaking change line in the diff view has a red "⚠ Breaking" inline badge
- Non-breaking additions/changes use standard green/yellow diff colors
- Breaking change count shown in the page title and compare summary card

**Tech Stack:** `openapi-diff` or custom rule engine, client-side diff AST parser, Monaco diff editor decorations

Part of Epic: Version Comparison & Diff

---

#### 3.1 (#2125) — Compare with Previous & Three-way View

The version detail page gains a "Compare with previous" button that immediately navigates to the diff view pre-populated with the immediately preceding version. Version selection dropdowns support choosing any two (or three) published versions of the same project.

Three-way compare renders three Monaco panels side-by-side with the base version in the center and the two comparison targets flanking it. Changes from base→left and base→right are highlighted in separate colors.

**Acceptance Criteria:**
- "Compare with previous" button appears only when a prior version exists
- Two-version compare is the default; three-version toggle adds a third panel
- Version selectors list all published versions with their publish dates
- URL encodes all selected versions: `?from=v1.0.0&to=v2.0.0` (or `&with=v1.5.0` for three-way)
- Three-way view scrolls all three panels in sync

Part of Epic: Version Comparison & Diff

---

#### 3.2 (#2126) — Section-scoped & Semantic Diff

A filter bar above the diff view allows narrowing to: "All", "Paths", "Schemas", "Security", "Info". Selecting "Paths" hides all diff hunks that do not belong to the `paths` top-level key. Semantic grouping collapses multiple raw diff lines into a single logical change entry (e.g. "Path /users: 3 properties changed").

**Acceptance Criteria:**
- Filter chips render above the diff; toggling a chip hides/shows relevant hunks instantly (no re-fetch)
- Semantic grouping summarized in a "Changes summary" collapsible above the raw diff
- Filter state is preserved in the URL query string
- Line count badge updates as filters are applied

Part of Epic: Version Comparison & Diff

---

#### 3.4 (#2128) — Diff Report Export & Change Navigation

A "Export report" button in the compare view generates a structured summary of changes in Markdown or PDF format. The report includes: project name, compared versions, change count, breaking changes list, and a grouped diff summary (added/removed/changed paths and schemas).

Next/previous change navigation: `]` jumps to the next diff hunk; `[` jumps to the previous diff hunk. A floating hunk counter (`3 / 17 changes`) tracks position.

**Acceptance Criteria:**
- Markdown export is a valid `.md` file downloadable from the browser
- PDF export renders cleanly with page breaks between epics
- `]` / `[` keyboard shortcuts navigate between diff hunks; wraps at boundaries
- Hunk counter updates on navigation and on filter change
- Export includes breaking-change annotations from issue 3.3

**Tech Stack:** `jsPDF` or `@react-pdf/renderer` for PDF, `download` attribute for Markdown, Monaco diff navigator API

Part of Epic: Version Comparison & Diff

---

#### 3.5 (#2129) — Changelog View & Version Timeline

A "Changelog" tab on the project page displays a human-readable list of changes between each consecutive version pair, ordered newest-first. Each entry shows: version number, publish date, added/removed/changed endpoints count, and a breaking-change badge if any.

A visual timeline on the same page renders versions as nodes on a horizontal axis. Hovering a version node shows a mini-preview of the top 3 changes (diff summary tooltip).

```
v3.0.0  ──●──────────────────────────── 2026-03-01
           │ +2 paths  ⚠ 1 breaking
v2.1.0  ───●──────────────────────────── 2026-01-15
           │ +5 paths  ~3 schemas
v2.0.0  ───●──────────────────────────── 2025-11-20
```

**Acceptance Criteria:**
- Changelog pre-computed at publish time and stored in a `version_changelog` table (not re-diffed on page load)
- Timeline renders up to 50 versions; scrollable horizontally for larger histories
- Clicking a timeline node navigates to the version detail page
- Changelog entries link to the full diff view for that version pair
- Breaking changes in the changelog are badged with ⚠ and a count

**Tech Stack:** PostgreSQL `version_changelog` table, populated by background job at publish time, React SVG or `recharts` for timeline

Part of Epic: Version Comparison & Diff

---

## Epic 4 (#2130): Export, Share & Embed

### Summary Table

| #    | Title                                     | Description                                                                       | Labels                                      | MVP | Parallel |
|------|-------------------------------------------|-----------------------------------------------------------------------------------|---------------------------------------------|-----|----------|
| 4.1 (#2131) | Single Operation/Schema Snippet Export    | Export one path or component as a standalone JSON/YAML file                       | `enhancement`, `browser`                    | No  | Yes      |
| 4.2 (#2132) | HTML Doc Export                           | Download a static HTML doc (Redoc/Swagger-style) for the current spec             | `enhancement`, `browser`                    | No  | Yes      |
| 4.3 (#2133) | PDF & Markdown Export                     | Full spec or diff report as PDF; spec summary as Markdown                         | `enhancement`, `browser`                    | No  | Yes      |
| 4.4 (#2134) | Shareable View Link & Embed Widget        | Revocable "view only" tokens; iframe embed script with domain allowlist           | `enhancement`, `browser`, `rest`            | No  | No       |
| 4.5 (#2135) | Developer Workflow Links                  | "Generate client" link (OpenAPI Generator); "View source" link from metadata      | `enhancement`, `browser`                    | No  | Yes      |

### Detailed Issue Descriptions

#### 4.4 (#2134) — Shareable View Link & Embed Widget

A "Share" menu on every version page allows generating a short-lived or permanent "view only" link backed by a signed token. Token expiry is configurable (1 hour / 1 day / 7 days / never). Revoking a token invalidates the link immediately.

The embed widget is a lightweight JavaScript snippet (`<script src="/embed.js">`) that renders the spec viewer inside an `<iframe>` on any external site. Tenant admins configure an allowed-domain allowlist; embed requests from unlisted origins receive a 403. Widget supports `theme` and `height` configuration attributes.

```html
<!-- Embed example -->
<div id="spec-viewer"
     data-tenant="acme"
     data-project="payments-api"
     data-version="v2.1.0"
     data-theme="dark"
     data-height="800px">
</div>
<script src="https://app.objectified.io/embed.js" async></script>
```

**OpenAPI Endpoints:**
```
POST /api/v1/share-links
  Body: { version_id, expires_in_seconds? }
  → 201: { token, url, expires_at }

DELETE /api/v1/share-links/:token
  → 204

GET /api/v1/embed/config?tenant=:slug
  → 200: { allowed_origins: string[], theme: string }
```

**Acceptance Criteria:**
- Share link token is a 32-byte random hex string stored in `share_link` table
- Expired or revoked tokens return 410 Gone with a user-friendly message
- Embed widget renders in an isolated iframe; parent page styles cannot bleed in
- Domain allowlist enforcement happens server-side (checked against `Origin` header)
- Widget supports `data-theme` (light/dark) and `data-height` attributes

**Tech Stack:** PostgreSQL `share_link` table, `crypto.randomBytes(32)`, NextJS middleware for origin check, `postMessage` for iframe resize

Part of Epic: Export, Share & Embed

---

#### 4.1 (#2131) — Single Operation/Schema Snippet Export

A context menu on each path or schema node (in the outline or viewer) offers "Export as JSON" and "Export as YAML". The exported snippet is a valid self-contained JSON/YAML fragment including the operation or schema object with its directly referenced components inlined or appended in a `components` block.

**Acceptance Criteria:**
- Exported JSON/YAML is valid and parseable in isolation
- Referenced schemas are included in a `components/schemas` block if not inline
- Export triggers a browser file download with a sensible filename (e.g. `post-charges.yaml`)
- Available for OpenAPI 3.x specs; gracefully disabled for Arazzo specs

Part of Epic: Export, Share & Embed

---

#### 4.2 (#2132) — HTML Doc Export

A "Download HTML Docs" button renders the full spec as a self-contained static HTML file using the Redoc rendering engine (or equivalent). The downloaded file works without internet access (all assets inlined) and matches the browse app's current theme.

**Acceptance Criteria:**
- Download triggers within 5 seconds for specs up to 500 paths
- Resulting HTML file opens correctly in Chrome, Firefox, and Safari without a web server
- All CSS and JS assets are inlined (no CDN dependencies)
- File size under 5MB for typical specs

**Tech Stack:** `redoc` npm package, `redoc-try-it-out` optional, server-side rendering via NextJS API route

Part of Epic: Export, Share & Embed

---

#### 4.3 (#2133) — PDF & Markdown Export

PDF export generates a structured document with: cover page (spec name, version, tenant), table of contents, endpoint reference, and schema reference. Markdown export generates a summary: spec title, description, path list with method and summary, and schema property list.

**Acceptance Criteria:**
- PDF renders with proper page breaks between path groups
- PDF includes clickable internal links in the table of contents
- Markdown export is GitHub-flavored Markdown and renders cleanly on GitHub
- Both exports complete within 10 seconds for specs up to 200 paths

**Tech Stack:** `@react-pdf/renderer` for PDF, handlebars template for Markdown

Part of Epic: Export, Share & Embed

---

#### 4.5 (#2135) — Developer Workflow Links

If a version's metadata includes a `source_repo_url` field, a "View source" link appears in the version header. An "OpenAPI Generator" button pre-fills the [openapi-generator.tech](https://openapi-generator.tech) online tool with the spec's public URL, letting users immediately generate client SDKs.

**Acceptance Criteria:**
- "View source" link appears only when `source_repo_url` is set in version metadata
- "Generate client" button opens openapi-generator.tech with `inputSpec` query param pre-filled
- Links open in a new tab with `rel="noopener noreferrer"`
- Links are omitted for private specs or specs with share-link access

Part of Epic: Export, Share & Embed

---

## Epic 5 (#2136): Search & Filters

### Summary Table

| #    | Title                                   | Description                                                                            | Labels                                      | MVP | Parallel |
|------|-----------------------------------------|----------------------------------------------------------------------------------------|---------------------------------------------|-----|----------|
| 5.1 (#2137) | Search Within Spec Content              | Full-text search inside the current spec (paths, descriptions, schema names)           | `enhancement`, `browser`                    | No  | No       |
| 5.2 (#2138) | Search Suggestions, Autocomplete & History | Autocomplete on tenant/project names; recent search history with clear option        | `enhancement`, `browser`                    | No  | Yes      |
| 5.3 (#2139) | Result Highlighting & Advanced Filters  | Highlight matched terms in result cards; filter by date range, tenant, spec type       | `enhancement`, `browser`                    | No  | Yes      |
| 5.4 (#2140) | Debounced Search & Result Caching       | Debounce input; cache recent results in memory/sessionStorage with short TTL           | `enhancement`, `browser`                    | No  | Yes      |

### Detailed Issue Descriptions

#### 5.1 (#2137) — Search Within Spec Content

`Ctrl+F` within the spec viewer opens an in-spec search bar (above Monaco). The search runs against path strings, operation summaries, descriptions, schema names, and property names. Results are highlighted in Monaco using decorations; a counter shows `N of M matches`. `Enter` / `Shift+Enter` cycle through matches.

**Acceptance Criteria:**
- In-spec search activates in <50ms on `Ctrl+F`
- Results highlighted in Monaco with yellow background decoration
- Match counter shown in search bar (e.g. "4 of 23")
- Enter/Shift+Enter cycle through matches; Escape closes the bar and clears highlights
- Search is case-insensitive by default with an optional case-sensitive toggle

**Tech Stack:** Monaco `editor.getModel().findMatches`, `editor.deltaDecorations` for highlights

Part of Epic: Search & Filters

---

#### 5.2 (#2138) — Search Suggestions, Autocomplete & History

The global search bar (header) shows autocomplete suggestions as the user types: tenant names, project names, and recently viewed specs. Suggestions are fetched from `GET /api/v1/search/suggestions?q=` with a 200ms debounce. A "Recent searches" dropdown lists the last 10 queries stored in `localStorage`; a "Clear history" button removes them.

**OpenAPI Endpoints:**
```
GET /api/v1/search/suggestions?q=:term&limit=8
  → 200: { tenants: [...], projects: [...], versions: [...] }
```

**Acceptance Criteria:**
- Suggestions appear within 300ms of typing (after debounce)
- Up to 8 suggestions split across tenants, projects, and versions
- Arrow keys navigate suggestions; Enter selects; Escape closes
- Recent searches stored in `localStorage` keyed by `browse_search_history`; max 10 entries
- Suggestions endpoint is rate-limited to 60 req/min per IP

Part of Epic: Search & Filters

---

#### 5.3 (#2139) — Result Highlighting & Advanced Filters

Matched terms in search result cards are highlighted with a `<mark>` element styled with the theme's accent color. An advanced filter panel (collapsible) adds: spec type (`openapi` / `arazzo` / `json-schema`), publish date range, and tenant selector for admin views.

**Acceptance Criteria:**
- Match highlight uses `<mark>` tag for semantic correctness; styled with accent color
- Filters apply immediately (no extra button); results update with a loading skeleton
- Filter state encoded in URL search params for shareable filtered views
- Date range picker uses ISO 8601 format in the URL: `?from=2026-01-01&to=2026-03-31`

Part of Epic: Search & Filters

---

#### 5.4 (#2140) — Debounced Search & Result Caching

Search input is debounced at 300ms before firing a request. Results for recent identical queries are cached in a `Map` (keyed by query string) with a 30-second TTL, avoiding redundant API calls on repeated or back-navigated searches.

**Acceptance Criteria:**
- No API call fires until 300ms after the user stops typing
- Cache hit returns results immediately without a loading spinner
- Cache evicts entries older than 30 seconds; maximum 20 entries in memory
- Cache is per-tab (not persisted to storage)

Part of Epic: Search & Filters

---

## Epic 6 (#2141): Performance & Reliability

### Summary Table

| #    | Title                                     | Description                                                                          | Labels                                      | MVP | Parallel |
|------|-------------------------------------------|--------------------------------------------------------------------------------------|---------------------------------------------|-----|----------|
| 6.1 (#2142) | Prefetch on Hover & Skeleton Loaders      | Preload adjacent version/project on link hover; skeleton UIs while data loads       | `enhancement`, `browser`                    | No  | Yes      |
| 6.2 (#2143) | Request Deduplication & Retry with Backoff| Deduplicate same-spec fetches across tabs; retry failed calls with exponential backoff| `enhancement`, `browser`                    | No  | Yes      |
| 6.3 (#2144) | Service Worker & Offline Support          | Cache spec list and recent specs for offline access; offline indicator banner        | `enhancement`, `browser`                    | No  | No       |
| 6.4 (#2145) | Virtual Scrolling & Bundle Optimization   | Virtualize large spec views; lazy-load Monaco; code-split compare and embed views    | `enhancement`, `browser`                    | No  | Yes      |

### Detailed Issue Descriptions

#### 6.3 (#2144) — Service Worker & Offline Support

A Workbox-based service worker caches: the tenant/project list (network-first, 1-minute TTL), recently opened spec versions (cache-first, 24-hour TTL, max 5 entries), and all static assets (cache-first, immutable). When the app detects it is offline, a banner appears at the top of the page: "You are offline — showing cached content. Some actions are unavailable."

Actions disabled offline: search (requires live API), export (requires server-side generation), share link creation. These show a tooltip: "Not available offline."

**Acceptance Criteria:**
- Tenant/project list loads from cache within 100ms when offline
- Recently viewed specs (up to 5) render fully from cache when offline
- Offline banner appears within 2 seconds of connectivity loss
- Service worker updates silently in the background; user prompted to refresh only when a new version is available
- Cache storage does not exceed 50MB; oldest entries evicted when limit approached

**Tech Stack:** `workbox-webpack-plugin` (or Next.js custom service worker), `navigator.onLine`, Cache API

Part of Epic: Performance & Reliability

---

#### 6.1 (#2142) — Prefetch on Hover & Skeleton Loaders

When the user hovers a version or project link for more than 150ms, prefetch the target page's data using `router.prefetch` (NextJS) or a background `fetch`. Skeleton loaders replace content areas during initial load: tenant page shows placeholder project cards; version page shows Monaco skeleton with blinking lines.

**Acceptance Criteria:**
- Prefetch fires after 150ms hover (not on mobile)
- Skeleton loaders match the dimensions of the actual content to prevent layout shift
- Skeleton uses CSS animation (shimmer) that respects `prefers-reduced-motion`
- No duplicate prefetch for the same URL within a 10-second window

Part of Epic: Performance & Reliability

---

#### 6.2 (#2143) — Request Deduplication & Retry with Backoff

If the same spec URL is fetched concurrently (e.g. user opens two tabs or a component re-mounts), the second request shares the in-flight Promise from the first rather than issuing a duplicate network call. Failed requests retry up to 3 times with exponential backoff (1s, 2s, 4s). After 3 failures, a "Retry" button appears in the UI.

**Acceptance Criteria:**
- In-flight deduplication keyed on full request URL; deduplicated requests attach to the same Promise
- Retry counter shown as a progress state (e.g. "Retrying… attempt 2 of 3")
- After 3 failures, a visible "Retry" button replaces the loading state
- Backoff jitter of ±20% added to each retry interval to prevent thundering herd
- Network errors (not 4xx client errors) trigger retry; 404/401 fail immediately

Part of Epic: Performance & Reliability

---

#### 6.4 (#2145) — Virtual Scrolling & Bundle Optimization

For specs with more than 2,000 lines, Monaco is initialized in virtual-scroll mode (only rendering visible lines). The compare view, embed widget, and Playground are lazy-loaded via dynamic imports. Monaco itself is loaded only when the spec viewer route is mounted, keeping the initial bundle under 150KB gzipped.

**Acceptance Criteria:**
- Initial page load JS bundle ≤ 150KB gzipped (measured via Lighthouse)
- Monaco loaded only on spec viewer mount; no Monaco code in the global bundle
- Compare view chunk loads on first navigation to `/compare`; cached thereafter
- Spec viewer remains smooth (60fps scroll) for specs up to 10,000 lines

**Tech Stack:** `next/dynamic` with `ssr: false`, Monaco `editor.createModel` lazy init, `@tanstack/react-virtual` for outline tree if needed

Part of Epic: Performance & Reliability

---

## Epic 7 (#2146): Accessibility & Localization

### Summary Table

| #    | Title                                   | Description                                                                             | Labels                                      | MVP | Parallel |
|------|-----------------------------------------|-----------------------------------------------------------------------------------------|---------------------------------------------|-----|----------|
| 7.1 (#2172) | Screen Reader Announcements & Keyboard Navigation | `aria-live` regions for diff/sort changes; full keyboard nav for spec viewer   | `enhancement`, `browser`, `a11y`            | No  | No       |
| 7.2 (#2173) | Focus Management & ARIA Labels          | Visible focus rings; focus trap in modals; ARIA labels on all dynamic regions           | `enhancement`, `browser`, `a11y`            | No  | Yes      |
| 7.3 (#2174) | High Contrast & Reduced Motion          | Optional high-contrast theme toggle; `prefers-reduced-motion` support                   | `enhancement`, `browser`, `a11y`            | No  | Yes      |
| 7.4 (#2147) | i18n & RTL Support                      | Translate all UI strings; language selector; RTL layout for right-to-left languages     | `enhancement`, `browser`                    | No  | No       |

### Detailed Issue Descriptions

#### 7.1 (#2172) — Screen Reader Announcements & Keyboard Navigation

An `aria-live="polite"` region announces: diff view filter changes ("Showing paths only — 12 changes"), table sort direction changes ("Sorted by version descending"), and major view transitions ("Compare view loaded"). The spec viewer (Monaco) is fully keyboard-navigable: `Tab` moves focus into the editor, arrow keys navigate, `Escape` returns focus to the outline panel.

**Acceptance Criteria:**
- All `aria-live` announcements are non-disruptive (polite, not assertive) for filter/sort changes
- `Tab` order follows visual layout: breadcrumb → outline → Monaco → Lint tab → footer
- All interactive elements reachable and operable without a mouse
- axe-core CI scan passes with zero critical violations on all key routes

**Tech Stack:** `aria-live` region component, Radix UI's built-in accessibility primitives, axe-core in Playwright CI

Part of Epic: Accessibility & Localization

---

#### 7.2 (#2173) — Focus Management & ARIA Labels

Modals (share link, QR code, playground) trap focus within while open, returning focus to the trigger element on close. All icon-only buttons have `aria-label`. Dynamic regions (search results, lint list, diff hunks) have `aria-label` or `aria-labelledby` pointing to their heading.

**Acceptance Criteria:**
- `Tab` cannot escape an open modal until it is dismissed
- Focus returns to the triggering button/element when any modal closes
- All buttons with icon-only labels have `aria-label` or `title`
- Lint table has `role="table"` with proper `aria-label="Validation issues"`

Part of Epic: Accessibility & Localization

---

#### 7.3 (#2174) — High Contrast & Reduced Motion

A "High contrast" toggle in the theme selector applies a CSS class that overrides all colors to pure black/white with high-contrast borders. The preference persists in `localStorage`. All CSS transitions and animations check `@media (prefers-reduced-motion: reduce)` and disable or shorten themselves.

**Acceptance Criteria:**
- High contrast mode achieves WCAG AA contrast ratio (≥4.5:1) for all text
- `prefers-reduced-motion` disables skeleton shimmer, hover animations, and timeline transitions
- High contrast preference stored in `localStorage` and applied before first paint (in `<head>` script to avoid flash)

Part of Epic: Accessibility & Localization

---

#### 7.4 (#2147) — i18n & RTL Support

All UI strings (not spec content) are externalized into JSON locale files under `locales/`. A language selector in the settings drawer or footer allows switching languages; the preference is stored in a cookie (`NEXT_LOCALE`). RTL layout is applied via `dir="rtl"` on the `<html>` element; CSS uses logical properties (`margin-inline-start` instead of `margin-left`) throughout.

**Acceptance Criteria:**
- All UI strings in locale JSON; no hardcoded English in JSX (verified by `i18n-ally` or equivalent lint rule)
- Language change takes effect without a full page reload (client-side locale switch)
- RTL layout tested with Arabic locale; outline panel appears on the right, breadcrumb reads right-to-left
- Default language detected from `Accept-Language` header; overridden by cookie

**Tech Stack:** `next-intl`, `NEXT_LOCALE` cookie, CSS logical properties

Part of Epic: Accessibility & Localization

---

## Epic 8 (#2148): Security & Compliance

### Summary Table

| #    | Title                                     | Description                                                                          | Labels                                       | MVP | Parallel |
|------|-------------------------------------------|--------------------------------------------------------------------------------------|----------------------------------------------|-----|----------|
| 8.1 (#2149) | Optional Auth for Private Specs           | OAuth2/OIDC or API key login to access private specs in browse                       | `enhancement`, `browser`, `security`, `rest` | No  | No       |
| 8.2 (#2150) | Session Timeout & Secure Storage          | Configurable session lifetime; httpOnly cookies; "Stay signed in" option             | `enhancement`, `browser`, `security`         | No  | Yes      |
| 8.3 (#2151) | CSP, Security Headers & Rate Limiting     | Content-Security-Policy, X-Frame-Options; rate limit search and spec fetch per IP    | `enhancement`, `browser`, `security`         | No  | Yes      |
| 8.4 (#2152) | Safe Errors, Audit Events & Data Retention | Generic client errors with error IDs; view/download audit log for private specs      | `enhancement`, `browser`, `security`, `rest` | No  | Yes      |

### Detailed Issue Descriptions

#### 8.1 (#2149) — Optional Auth for Private Specs

Tenants can mark individual projects as "private". Accessing a private project's browse pages requires authentication. Browse supports two auth methods: OAuth2/OIDC (redirects to the tenant's IdP) and API key (passed via a query param `?api_key=` or `Authorization: Bearer` header for programmatic access).

After login, the session token is stored in an httpOnly cookie (not localStorage). The browse app validates the token on each request server-side via `GET /api/v1/auth/me`.

**OpenAPI Endpoints:**
```
GET  /api/v1/auth/me
  → 200: { user_id, tenant_id, roles[] }
  → 401: { error: "Unauthenticated" }

POST /api/v1/auth/logout
  → 204
```

**Acceptance Criteria:**
- Accessing a private project without auth redirects to the login page with `?return_to=` param
- After login, user is redirected back to the original URL
- API key access works without a browser session (for CI/tool usage)
- Tenant admins configure allowed IdP OIDC URLs in tenant settings

**Tech Stack:** NextJS middleware for route protection, `iron-session` or `next-auth`, httpOnly cookies

Part of Epic: Security & Compliance

---

#### 8.3 (#2151) — CSP, Security Headers & Rate Limiting

All responses from the browse app include security headers. The Content-Security-Policy restricts scripts to `'self'` plus the Monaco CDN (if used externally), and blocks all external frame embedding except for explicitly configured embed domains. Rate limiting is applied at the edge: 60 search requests/min per IP, 200 spec fetch requests/min per IP.

```
Content-Security-Policy: default-src 'self'; script-src 'self' 'nonce-{nonce}'; frame-ancestors 'self' https://allowed-embed.example.com
X-Frame-Options: SAMEORIGIN
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), microphone=(), geolocation=()
```

**Acceptance Criteria:**
- All pages pass [securityheaders.com](https://securityheaders.com) scan with an A rating
- CSP violations are logged to the server (via `report-uri` or `report-to`)
- Rate limit exceeded returns 429 with `Retry-After` header
- Embed iframe allowlist applied via `frame-ancestors` CSP directive (not just `X-Frame-Options`)

**Tech Stack:** NextJS `headers()` in middleware, Vercel Edge Config or Redis for rate limit counters

Part of Epic: Security & Compliance

---

#### 8.2 (#2150) — Session Timeout & Secure Storage

Sessions for authenticated browse access expire after a configurable period (default: 8 hours idle, 30 days absolute). A "Stay signed in" checkbox at login sets the absolute expiry to 30 days; unchecked sets it to the browser session. Tokens are stored in httpOnly, SameSite=Strict cookies only — never in `localStorage` or `sessionStorage`.

**Acceptance Criteria:**
- Idle timeout resets on each authenticated page view
- Session cookie is `httpOnly`, `SameSite=Strict`, `Secure`
- Expired session redirects to login with `?reason=session_expired`
- "Stay signed in" stores a refresh token in a separate long-lived httpOnly cookie

Part of Epic: Security & Compliance

---

#### 8.4 (#2152) — Safe Errors, Audit Events & Data Retention

All server-side errors return generic messages to the client (e.g. "An error occurred. Reference: ERR-8a3f2c"). The full error including stack trace is logged server-side only. For private specs, every view and download event is logged to an `audit_event` table with: `user_id`, `tenant_id`, `version_id`, `action`, `ip_address_hash`, `timestamp`. Audit log data is retained for 90 days by default, configurable per tenant.

**OpenAPI Endpoints:**
```
GET /api/v1/tenants/:id/audit-events?from=&to=&action=
  → 200: { events: [{ id, user_id, action, version_id, timestamp }] }
```

**Acceptance Criteria:**
- Client never receives stack traces, internal URLs, or database error messages
- Each error response includes a unique `reference_id` that maps to the server log entry
- Audit events written within 1 second of the action (async write, non-blocking)
- Audit log query endpoint requires tenant admin role
- Audit entries older than the retention period are purged by a scheduled job

Part of Epic: Security & Compliance

---

## Epic 9 (#2153): Analytics & Observability

### Summary Table

| #    | Title                                     | Description                                                                           | Labels                                      | MVP | Parallel |
|------|-------------------------------------------|---------------------------------------------------------------------------------------|---------------------------------------------|-----|----------|
| 9.1 (#2154) | Anonymous Usage Metrics & Popular Specs   | Opt-in page view and feature usage metrics (no PII); "Most viewed" on tenant page    | `enhancement`, `browser`                    | No  | Yes      |
| 9.2 (#2155) | Admin / Tenant Analytics Dashboard        | View counts per project/version, top referrers, export as CSV (tenant admins only)   | `enhancement`, `browser`, `rest`            | No  | No       |
| 9.3 (#2156) | Health Check Page & Feature Flags         | `/health` endpoint; per-tenant and global feature flag system for gradual rollout     | `enhancement`, `browser`, `rest`            | No  | Yes      |
| 9.4 (#2157) | Client Error Reporting                    | Optional Sentry integration for JS errors with tenant/version context (no PII)        | `enhancement`, `browser`                    | No  | Yes      |

### Detailed Issue Descriptions

#### 9.3 (#2156) — Health Check Page & Feature Flags

`GET /api/v1/health` returns a JSON payload with the status of all dependencies: PostgreSQL read-replica, REST API, and (if applicable) Ollama. Used by load balancers and uptime monitors. A feature flag system allows toggling new browse features (e.g. "embed-widget", "three-way-compare") per tenant or globally without a deployment.

```json
GET /api/v1/health
{
  "status": "healthy",
  "checks": {
    "postgres": { "status": "ok", "latency_ms": 4 },
    "rest_api": { "status": "ok", "latency_ms": 12 }
  },
  "version": "1.4.2"
}
```

**Acceptance Criteria:**
- `/api/v1/health` returns 200 when all checks pass; 503 if any check fails
- Health check does not expose internal IP addresses or connection strings
- Feature flags stored in PostgreSQL `feature_flag` table with `(flag_name, tenant_id, enabled)` rows
- Feature flag reads are cached in memory for 60 seconds to avoid per-request DB queries
- Admin UI for toggling flags is in the main `objectified-ui` admin panel (out of browse scope)

**Tech Stack:** NextJS API route, PostgreSQL health query, in-memory LRU cache for feature flags

Part of Epic: Analytics & Observability

---

#### 9.1 (#2154) — Anonymous Usage Metrics & Popular Specs

Page view events (tenant page, project page, version view, compare view, export) are logged server-side without PII: no user ID, no IP address (only country from Geo header). Aggregated counts power a "Most viewed" section on the tenant home page showing the top 3 projects by view count in the last 30 days.

**Acceptance Criteria:**
- Analytics collection opt-out respected via `DNT` header or a cookie preference
- No PII in analytics events: only `tenant_id`, `project_id`, `version_id`, `action`, `country_code`, `timestamp`
- "Most viewed" section renders using pre-aggregated daily counts; no real-time query
- Analytics events are batch-written (every 30 seconds or 50 events, whichever comes first) to avoid per-request DB writes

Part of Epic: Analytics & Observability

---

#### 9.2 (#2155) — Admin / Tenant Analytics Dashboard

Tenant admins see a "Analytics" section within the browse app's tenant settings page. Charts show: daily view counts per project (line chart, 30-day window), top 5 projects by views (bar chart), top referrer domains (table). Data is exportable as CSV.

**OpenAPI Endpoints:**
```
GET /api/v1/tenants/:id/analytics/views?from=&to=&granularity=day
  → 200: { series: [{ date, project_id, views }] }

GET /api/v1/tenants/:id/analytics/referrers?limit=10
  → 200: { referrers: [{ domain, views }] }
```

**Acceptance Criteria:**
- Dashboard accessible only to users with `tenant:admin` role
- Charts render with `recharts` or `chart.js`; skeleton shown while loading
- CSV export contains all rows for the selected date range
- Referrer domains are normalized (strip subdomains, path, query)

Part of Epic: Analytics & Observability

---

#### 9.4 (#2157) — Client Error Reporting

When the `NEXT_PUBLIC_SENTRY_DSN` environment variable is set, the browse app initializes Sentry with a `beforeSend` filter that strips all PII from error payloads (emails, tokens, user IDs replaced with `[REDACTED]`). Each error event includes: `tenant` tag, `project` tag, `spec_type` tag. Performance tracing is disabled by default.

**Acceptance Criteria:**
- Sentry only initialized when `NEXT_PUBLIC_SENTRY_DSN` is set; no error if unset
- `beforeSend` filter passes tests covering common PII patterns (email, UUID, Bearer token)
- Browser console does not show raw Sentry DSN in non-dev builds
- Error reports include the browse app version string for triaging

**Tech Stack:** `@sentry/nextjs`, Sentry `beforeSend` filter, environment variable guard

Part of Epic: Analytics & Observability

---

## Epic 10 (#2158): Enterprise & White-Label

### Summary Table

| #    | Title                                     | Description                                                                          | Labels                                      | MVP | Parallel |
|------|-------------------------------------------|--------------------------------------------------------------------------------------|---------------------------------------------|-----|----------|
| 10.1 (#2159) | Custom Logo, Colors & Domain              | Tenant-specific logo, accent color, and custom domain (e.g. api-docs.acme.com)       | `enhancement`, `browser`                    | No  | Yes      |
| 10.2 (#2160) | Footer/Legal Links & Tenant Feature Toggles | Configurable footer links; enable/disable compare/export/embed per tenant          | `enhancement`, `browser`, `rest`            | No  | Yes      |
| 10.3 (#2161) | Usage Quotas & SLA Status Link            | Surface "near limit" warnings for heavy tenants; SLA/status page link in footer      | `enhancement`, `browser`, `rest`            | No  | Yes      |

### Detailed Issue Descriptions

#### 10.1 (#2159) — Custom Logo, Colors & Domain

Tenant admins upload a logo (PNG/SVG, max 256KB) and optionally set a primary accent color (hex code). The browse app fetches these at runtime from `GET /api/v1/tenants/:slug/branding` and applies them via CSS custom properties. Custom domain support routes a tenant-specific domain to the same browse deployment using a `HOST` header lookup.

```
GET /api/v1/tenants/:slug/branding
{
  "logo_url": "https://cdn.objectified.io/tenants/acme/logo.svg",
  "accent_color": "#1a56db",
  "custom_domain": "api-docs.acme.com",
  "footer_links": [
    { "label": "Terms", "url": "https://acme.com/terms" }
  ]
}
```

**Acceptance Criteria:**
- Logo replaces the default Objectified wordmark in navbar and footer
- Accent color applied as `--color-brand` CSS variable; affects buttons, links, active states
- Custom domain resolves to the browse app with the correct tenant context (via HOST header)
- Logo upload validates file type (PNG/SVG) and size (≤256KB) before storing
- Branding response cached at edge for 5 minutes

**Tech Stack:** S3 for logo storage, CSS `var()`, NextJS middleware for custom domain resolution

Part of Epic: Enterprise & White-Label

---

#### 10.2 (#2160) — Footer/Legal Links & Tenant Feature Toggles

Tenant branding configuration includes a `footer_links` array (label + URL, max 8 links). These render in the browse app footer, replacing or augmenting the default links. Feature toggles in the same config object allow disabling: `compare_view`, `export_pdf`, `embed_widget`, `deep_links`. Disabled features are hidden from the UI rather than showing an error.

**Acceptance Criteria:**
- Footer links render in the order specified; max 8 enforced at the API level
- All footer links open in a new tab with `rel="noopener noreferrer"`
- Disabled features are completely absent from the DOM (not just visually hidden)
- Feature toggle changes take effect within 5 minutes (branding cache TTL)

Part of Epic: Enterprise & White-Label

---

#### 10.3 (#2161) — Usage Quotas & SLA Status Link

If the backend reports that a tenant is within 10% of their published version quota or monthly view quota, the browse app shows a dismissable warning banner (tenant admins only): "You are approaching your plan limit — 450 of 500 published versions used." A link to the pricing/upgrade page is included. An optional `status_page_url` in branding config adds a "Status" link to the footer.

**Acceptance Criteria:**
- Quota warning shown only to authenticated tenant admins; hidden from public visitors
- Warning dismissed per session (sessionStorage); re-shown on next session if still near limit
- `status_page_url` renders as a "Status" footer link if set; omitted if empty
- Quota data comes from `GET /api/v1/tenants/:id/quota` (existing endpoint); no new endpoint needed

Part of Epic: Enterprise & White-Label

---

## Epic 11 (#2162): Keyboard Shortcuts & Power Users

### Summary Table

| #    | Title                                       | Description                                                                          | Labels                                      | MVP | Parallel |
|------|---------------------------------------------|--------------------------------------------------------------------------------------|---------------------------------------------|-----|----------|
| 11.1 (#2163) | Shortcut Help Modal & Global Shortcuts      | `?` opens shortcut reference modal; `Ctrl+K` quick search; `Esc` close modals       | `enhancement`, `mvp`, `browser`             | Yes | No       |
| 11.2 (#2164) | Navigation & Editor Shortcuts               | `←`/`→` prev/next version; `Ctrl+G` go to path; `G L` go to line in editor         | `enhancement`, `browser`                    | No  | Yes      |
| 11.3 (#2165) | Copy/Download Shortcuts & Remapping         | `Ctrl+C` copy spec; `Ctrl+D` download; configurable shortcut remapping in settings  | `enhancement`, `browser`                    | No  | Yes      |

### Detailed Issue Descriptions

#### 11.1 (#2163) — Shortcut Help Modal & Global Shortcuts

Pressing `?` anywhere in the app (except when a text input is focused) opens a full-screen modal listing all keyboard shortcuts grouped by category: Navigation, Spec Viewer, Compare, Copy/Export, and General. The modal is keyboard-dismissible with `Escape`.

Global shortcuts active on all pages:
- `Ctrl+K` — open quick search
- `Ctrl+F` — focus in-spec search (spec viewer only)
- `Escape` — close any open modal or panel
- `?` — open shortcut help modal

**Acceptance Criteria:**
- `?` key opens the shortcut modal when focus is not in a text input or Monaco
- Modal renders all shortcuts in a two-column layout: key chord on left, description on right
- `Escape` closes the modal and returns focus to the previous element
- Shortcut modal is itself navigable via keyboard (Tab through sections)
- `Ctrl+K` focuses the global search bar and highlights its text

**Tech Stack:** Global `keydown` event listener with focus guard, Radix UI Dialog, shortcut registry singleton

Part of Epic: Keyboard Shortcuts & Power Users

---

#### 11.2 (#2164) — Navigation & Editor Shortcuts

On a version detail page, `←` navigates to the previous published version and `→` to the next (only when Monaco is not focused, to avoid interfering with cursor movement). `Ctrl+G` opens the go-to-path quick-jump (issue 2.2). In the Monaco editor, `Ctrl+Shift+G` or the Vim-style `G L` sequence opens "Go to line" (Monaco built-in).

**Acceptance Criteria:**
- `←`/`→` version navigation only fires when focus is outside Monaco and text inputs
- Navigation shows a loading indicator during page transition
- `Ctrl+G` shortcut works from any focus position outside Monaco
- Shortcuts do not conflict with browser defaults (e.g. `Ctrl+L` for address bar avoided)

Part of Epic: Keyboard Shortcuts & Power Users

---

#### 11.3 (#2165) — Copy/Download Shortcuts & Remapping

`Ctrl+Shift+C` copies the full raw spec to the clipboard (JSON or YAML based on the active format tab). `Ctrl+Shift+D` triggers the download of the spec file. Shortcut remapping: a "Shortcuts" section in the settings drawer lets users reassign any browse-specific shortcut; remappings are stored in `localStorage` and applied at app init.

**Acceptance Criteria:**
- `Ctrl+Shift+C` copies spec content and shows a toast: "Spec copied to clipboard"
- `Ctrl+Shift+D` triggers browser download with the correct filename and MIME type
- Shortcut remapping persisted in `localStorage` under `browse_shortcuts` key
- Remap UI shows the current binding, allows pressing a new key combination, and validates for conflicts
- Resetting shortcuts to defaults clears the `browse_shortcuts` key

Part of Epic: Keyboard Shortcuts & Power Users

---

## Epic 12 (#2166): Testing & Quality

### Summary Table

| #    | Title                                     | Description                                                                            | Labels                                      | MVP | Parallel |
|------|-------------------------------------------|----------------------------------------------------------------------------------------|---------------------------------------------|-----|----------|
| 12.1 (#2167) | E2E Test Suite (Playwright)               | Critical flow coverage: browse, search, spec view, compare, export                    | `enhancement`, `browser`, `testing`         | No  | No       |
| 12.2 (#2168) | Visual Regression & Accessibility Tests   | Percy/Playwright snapshot checks; axe-core CI scan on all key routes                  | `enhancement`, `browser`, `testing`         | No  | Yes      |
| 12.3 (#2169) | API Contract Tests                        | Assert REST API response shapes used by browse match their OpenAPI descriptions        | `enhancement`, `browser`, `testing`         | No  | Yes      |
| 12.4 (#2170) | Storybook, Contributing Guide & API Docs  | Component stories for all major browse components; contributor guide; TypeDoc          | `enhancement`, `browser`                    | No  | Yes      |

### Detailed Issue Descriptions

#### 12.1 (#2167) — E2E Test Suite (Playwright)

Playwright tests cover the critical happy paths:
1. Load tenant home → navigate to project → open version → confirm spec loads in Monaco
2. Search for a term → verify results appear → click result → confirm navigation
3. Open compare view → select two versions → confirm diff renders
4. Export spec as YAML → confirm download occurs
5. Open shortcut help modal with `?` → confirm all shortcut categories visible → `Escape` closes

Tests run in CI on each pull request against a seeded test tenant with known spec fixtures.

**Acceptance Criteria:**
- All 5 happy-path flows pass in CI (Chromium, Firefox, WebKit)
- Tests run in under 3 minutes total (parallel test sharding)
- Flaky tests tracked and fixed within 2 sprints of detection
- CI reports test video artifacts on failure

**Tech Stack:** Playwright, GitHub Actions, test fixtures with seeded PostgreSQL snapshot

Part of Epic: Testing & Quality

---

#### 12.2 (#2168) — Visual Regression & Accessibility Tests

Playwright screenshot tests capture each major route (tenant home, project page, version view, compare view, Playground) in light and dark themes. Screenshots are compared against baseline with a 0.1% pixel-diff threshold. axe-core is run on each route; any critical or serious violations fail the build.

**Acceptance Criteria:**
- Visual regression baselines committed to the repo and updated via a PR label (`update-snapshots`)
- axe-core reports zero critical or serious violations on all tested routes
- Both light and dark themes tested
- CI pipeline fails with a diff image artifact when visual regression exceeds threshold

**Tech Stack:** `@playwright/test` screenshot comparison, `axe-playwright` for accessibility scanning

Part of Epic: Testing & Quality

---

#### 12.3 (#2169) — API Contract Tests

Using the objectified-rest OpenAPI spec, `@schemathesis/schemathesis` or a custom assertion layer validates that the actual REST API responses received by browse match the declared response schemas. Tested against a staging environment or Docker Compose setup.

**Acceptance Criteria:**
- Contract tests cover all REST endpoints used by browse (list versions, get spec content, search, branding, health)
- Any schema mismatch causes the test to fail with a clear diff
- Tests run as part of the integration test suite, not the unit test suite

Part of Epic: Testing & Quality

---

#### 12.4 (#2170) — Storybook, Contributing Guide & API Docs

Storybook stories for: `Navbar`, `SpecViewer`, `DataTable`, `CompareViewer`, `OutlinePanel`, `SkeletonLoader`, and all theme variants. A `CONTRIBUTING.md` in `objectified-browse/` documents: local setup, environment variables, how to run tests, and PR conventions. TypeDoc generates documentation for all exported TypeScript utilities.

**Acceptance Criteria:**
- Storybook builds without errors in CI
- Each story covers at least: default state, loading state, empty state, error state
- `CONTRIBUTING.md` includes a "Getting started in 5 minutes" section with copy-paste commands
- TypeDoc output published to `/docs/api` as a static site (or linked from README)

**Tech Stack:** Storybook 8, TypeDoc, `@storybook/nextjs`

Part of Epic: Testing & Quality

---

## Epic 13 (#2171): Infrastructure & Deployment

### Summary Table

| #    | Title                                     | Description                                                                          | Labels                                       | MVP | Parallel |
|------|-------------------------------------------|--------------------------------------------------------------------------------------|----------------------------------------------|-----|----------|
| 13.1 (#2175) | Kubernetes Manifests & Helm Chart         | Sample Deployment/Service/Ingress YAMLs; parameterized Helm chart for browse         | `enhancement`, `browser`, `infrastructure`   | No  | Yes      |
| 13.2 (#2176) | Health Endpoints & Prometheus Metrics     | `/api/health` with dependency checks; `/metrics` with request duration and error rate | `enhancement`, `browser`, `infrastructure`, `rest` | No  | Yes      |
| 13.3 (#2177) | Structured Logging & Docker Optimization  | JSON logs with request ID and tenant context; optimized multi-stage Docker image      | `enhancement`, `browser`, `infrastructure`   | No  | Yes      |

### Detailed Issue Descriptions

#### 13.1 (#2175) — Kubernetes Manifests & Helm Chart

A `deploy/kubernetes/` directory contains sample manifests: `Deployment` (browse app, 2 replicas, resource limits), `Service` (ClusterIP), `Ingress` (nginx, with TLS annotation), and `ConfigMap` (env var template). A `deploy/helm/objectified-browse/` chart parameterizes: `image.tag`, `replicaCount`, `ingress.host`, `env.DATABASE_URL`, `env.REST_API_URL`, `env.NEXT_PUBLIC_APP_URL`.

**Acceptance Criteria:**
- Helm chart passes `helm lint` with zero errors
- `helm install` with default values produces a runnable browse deployment against a local cluster
- Deployment includes liveness probe (`/api/health`) and readiness probe (`/api/health`)
- Resource requests/limits set: 128Mi/256Mi memory, 100m/500m CPU
- Ingress template supports both nginx and traefik annotations via `ingress.className`

**Tech Stack:** Helm 3, Kubernetes 1.28+, nginx ingress controller

Part of Epic: Infrastructure & Deployment

---

#### 13.2 (#2176) — Health Endpoints & Prometheus Metrics

`GET /api/v1/health` (covered in Epic 9) is extended with a `/metrics` endpoint (Prometheus text format) exposing: `http_requests_total` (by route and status), `http_request_duration_seconds` (histogram), `browse_spec_load_errors_total`, `browse_search_requests_total`. The metrics endpoint is protected by a `METRICS_TOKEN` environment variable (Bearer token).

```
# HELP http_requests_total Total HTTP requests
# TYPE http_requests_total counter
http_requests_total{route="/[tenant]/[project]/[version]",status="200"} 1423
http_requests_total{route="/api/v1/search",status="200"} 874
```

**Acceptance Criteria:**
- `/metrics` returns valid Prometheus text format
- Access without `Authorization: Bearer $METRICS_TOKEN` returns 401
- Histogram buckets: 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10 seconds
- Metrics collected without introducing >1ms overhead per request

**Tech Stack:** `prom-client` npm package, NextJS API route for `/metrics`

Part of Epic: Infrastructure & Deployment

---

#### 13.3 (#2177) — Structured Logging & Docker Optimization

All server-side log output uses JSON format with fields: `timestamp` (ISO 8601), `level`, `request_id` (UUID, generated per request in middleware), `tenant_slug` (when available), `project_slug` (when available), `message`. No PII (user IDs, emails) in logs. The Docker image uses a multi-stage build: `node:22-alpine` builder stage → minimal `node:22-alpine` runtime stage; final image under 200MB.

**Acceptance Criteria:**
- All `console.log/warn/error` replaced with a structured logger (`pino` or similar)
- `request_id` header (`X-Request-ID`) is forwarded to downstream REST API calls for distributed tracing
- Docker image builds in under 3 minutes in CI
- Final image size under 200MB (verified with `docker image inspect`)
- No `node_modules` dev dependencies in the runtime layer

**Tech Stack:** `pino` logger, `pino-pretty` for local dev, Docker multi-stage build, `next build` standalone output mode

Part of Epic: Infrastructure & Deployment

---
