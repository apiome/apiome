# Repository Store mockups

Static, browser-openable design mockups for the **Repository Store** feature —
a Postgres-backed registry of source-code repositories that Apiome users
can browse, scan, and selectively import specifications from.

These files are visual references only — no API calls, no auth, no Docker
runtime, no real Git/GitHub/GitLab traffic, no build step.

## Open

Either open the files directly:

```
open apiome-ui/public/mockups/repositories/index.html
```

Or, with the Next.js dev server running, browse to:

```
http://localhost:3000/mockups/repositories/index.html
```

## Files

All pages share the **projects-mockup** chrome: the fixed top breadcrumb bar,
the persistent left sidebar (Workspace card + Catalog / Versioning / Settings
nav with **Repositories** active), and the same theme key
(`repositories-mockup-theme`). The per-repository screens are consolidated
into a single **`repository.html`** with in-page tabs (Overview / Files /
Imports / Settings), mirroring the projects-mockup `project.html` pattern.

| File                       | Purpose                                                                                                                  |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `index.html`               | Mockup hub linking to all repository-store screens                                                                       |
| `repositories.html`        | Projects-style card grid of registered repos (linked account + public URL) with KPI band and filter bar                  |
| `repository.html`          | Single-repo detail page with header (provider/branch/score-strip) and tabs: **Overview**, **Files**, **Imports**, **Settings** |
| `add-repository.html`      | Add-repository wizard — pick from linked accounts (GitHub/GitLab/Bitbucket) or paste a public URL                        |
| `file-detail.html`         | Drill-down from the **Files** tab — Preview / Raw / Diff / **Visualize** views, detected metadata, importable verdict, suggested target |
| `import-mapping.html`      | Drill-down from `file-detail.html` — map an importable file to an existing project, or create a new one, then import     |

> The **Files** tab on `repository.html` carries everything that the previous
> standalone `browse.html` did: comma-separated glob input, regex filter,
> importable-type preset dropdown, and the file table with detected-kind pills
> + confidence badges. The **Imports** tab carries everything that the previous
> standalone `imports.html` did. Those two files have been removed.

## Feature concept (read this before implementing)

The **Repository Store** is a long-lived, Postgres-backed registry of source
code repositories that the tenant has connected to Apiome. It is _not_ a
clone of the source code, and it is _not_ an in-memory cache. Every artifact
described below MUST be persisted to Postgres — no in-memory stores, no
per-process caches that would survive a restart silently. Background
refresh/scan workers update the same Postgres tables.

### Why does it exist?

Today, Apiome can import a single file (OpenAPI, Arazzo, JSON Schema,
etc.) one upload at a time. The Repository Store inverts that flow:

1. **Connect once.** A user connects a repository — either through one of their
   Linked Accounts (GitHub, GitLab, Bitbucket) or by pasting a public Git URL.
2. **Scan & catalogue.** Apiome walks the repository tree and stores a
   row per file (path, size, sha, ext, last-modified, branch, commit) in
   Postgres. A lightweight ancillary scan classifies each file _by filename
   only_ (ext + basename heuristics) into a candidate importer kind.
3. **Browse & filter.** The user picks a repository, then narrows the file
   list with a comma-separated glob (`**/openapi*.yaml, **/arazzo/*.yaml`),
   a regex, or a preset from the "Importable file types" dropdown.
4. **Inspect.** Clicking a file fetches its contents on demand (still no
   in-memory cache; the bytes are streamed from the source provider and the
   parsed metadata is persisted in Postgres for re-use).
5. **Decide importability.** A deeper sniff opens the file, looks at its top
   keys (`openapi:`, `swagger:`, `$schema`, `arazzo:`, `asyncapi:`,
   `info.version`, etc.) and returns a verdict — **Importable as
   `<kind>`**, or **Not importable** with reasons.
6. **Map to a project.** The user maps the file to an existing project, or
   creates a brand-new project seeded from the spec's metadata
   (`info.title`, `info.description`, tags, contact, license, …).
7. **Import.** Importing creates a new project _version_ named after the
   `info.version` in the spec — the same flow Apiome uses today when a
   user imports a file directly into a version. The file/path/sha is recorded
   in `repository_imports` so we never re-import the same sha twice
   accidentally, and we can show a project's "imported from" provenance.

### Future scope (not in this mockup)

- Webhook-driven re-scan when the repository's default branch changes
- Per-branch tracking — same file across `main`, `release/2025-04`, `dev`,
  with auto-imports producing new patch/minor versions per branch policy
- Pull-request previews — a draft project version per PR, dropped on close
- Cross-repository dependency resolution (one OpenAPI `$ref`'s another
  living in a sibling repo)
- AI-assisted "what kind of file is this?" sniffing for ambiguous files
  (e.g., `schema.json` could be JSON Schema, AVRO, or arbitrary config)

These will get their own mockups in later iterations.

## Data model expectations (Postgres only)

The implementation MUST use Postgres for all of the following — no in-memory
state, no Redis, no JSON-on-disk:

- `repository` — one row per registered repo. Columns include `id (uuid)`,
  `tenant_id`, `name`, `provider` (`github` / `gitlab` / `bitbucket` /
  `public_url`), `linked_account_id` (nullable, FK to a tenant's linked
  account), `clone_url`, `default_branch`, `visibility`
  (`public` / `private`), `status` (`pending` / `scanning` / `ready` /
  `error` / `archived`), `last_scanned_at`, `total_files`,
  `total_bytes`, `created_at`, `updated_at`.
- `repository_branch` — one row per tracked branch. `id`, `repository_id`,
  `branch`, `head_sha`, `last_scanned_at`. (Already partially present in
  the existing `apiome.repository_branch` table — extend, do not duplicate.)
- `repository_file` — one row per `(branch, path)` discovered during scan.
  `id`, `repository_id`, `branch_id`, `path`, `name`, `ext`,
  `size_bytes`, `blob_sha`, `last_commit_sha`, `last_commit_at`,
  `detected_kind` (nullable enum — see "Detected kinds" below),
  `detected_confidence` (`filename_only` / `content_sniffed`),
  `importable` (boolean, nullable until sniffed), `import_blocked_reason`
  (nullable text). Index on `(repository_id, branch_id, path)` and on
  `(repository_id, detected_kind)` for filter perf.
- `repository_file_content_cache` — optional, opt-in. `file_id`,
  `fetched_at`, `bytes` (`bytea`), `parse_error` (nullable). Use only when
  the user has explicitly inspected the file. Cache invalidation is by
  `blob_sha` change, not TTL. Never hold file contents in process memory
  beyond the request that produced them.
- `repository_import` — one row per file we successfully imported. `id`,
  `repository_file_id`, `project_id`, `project_version_id`,
  `spec_version` (string from `info.version`), `imported_by_user_id`,
  `imported_at`, `import_run_id` (FK back into the existing
  `import_run` / `imported_files` tables — wire into the existing import
  audit trail rather than parallel-tracking it).
- `repository_scan` — one row per scan run. `id`, `repository_id`,
  `branch_id`, `started_at`, `finished_at`, `status` (`running` /
  `succeeded` / `failed`), `files_seen`, `files_added`,
  `files_changed`, `files_removed`, `error_message`.

All write paths go through `apiome-rest`. All reads in the UI go
through the same REST API; there is no client-side state that persists
beyond a single page session.

## Detected kinds (filename-only heuristics)

The first-pass scan classifies files by filename / extension only:

| Extension / pattern                                 | Detected kind          |
| --------------------------------------------------- | ---------------------- |
| `*.yaml`, `*.yml`                                   | `yaml-candidate`       |
| `*.json`                                            | `json-candidate`       |
| `openapi*.{yaml,yml,json}`, `swagger*.{yaml,yml,json}` | `openapi-candidate`    |
| `arazzo*.{yaml,yml,json}`, `*.arazzo.{yaml,yml}`    | `arazzo-candidate`     |
| `asyncapi*.{yaml,yml,json}`                         | `asyncapi-candidate`   |
| `*.{proto}`                                         | `protobuf-candidate`   |
| `*.{avsc}`                                          | `avro-candidate`       |
| `*.graphql`, `*.gql`                                | `graphql-candidate`    |
| `*.dbml`                                            | `dbml-candidate`       |
| `schema.prisma`                                     | `prisma-candidate`     |
| `*.sql`, `*.ddl`                                    | `sql-ddl-candidate`    |
| `postman_collection.json`, `*.postman.json`         | `postman-candidate`    |
| anything else with no match                         | `null` (uncategorised) |

The `-candidate` suffix is intentional — filename matches are _suggestions_,
not commitments. A second pass (only when the user opens the file) sniffs
the contents and may either promote `openapi-candidate` → `openapi` (with
a concrete version like `3.1.0`) or demote it to `not-importable` with a
reason.

## Preset filter dropdown

The browse screen exposes a "Importable file types" dropdown with these
presets (each preset is a comma-separated glob list under the hood):

- **All importable** — union of every glob below
- **OpenAPI** — `**/openapi*.yaml, **/openapi*.yml, **/openapi*.json, **/swagger*.yaml, **/swagger*.yml, **/swagger*.json`
- **Arazzo** — `**/arazzo*.yaml, **/arazzo*.yml, **/*.arazzo.yaml, **/*.arazzo.yml`
- **AsyncAPI** — `**/asyncapi*.yaml, **/asyncapi*.yml, **/asyncapi*.json`
- **JSON Schema** — `**/*.schema.json, **/schemas/**/*.json`
- **GraphQL** — `**/*.graphql, **/*.gql`
- **Protobuf** — `**/*.proto`
- **Avro** — `**/*.avsc`
- **Postman** — `**/*.postman_collection.json, **/postman_collection.json`
- **SQL DDL** — `**/*.sql, **/*.ddl`
- **Custom…** — opens an inline editor for free-form globs

The free-text glob field accepts comma-separated patterns and combines
them with the dropdown selection (logical OR). The regex field is a
mutually-exclusive alternative input — picking a regex overrides the
glob filter for that view.

## Status pills

Reuse the platform pill styles. The repository-specific values:

- **Repository status**: `Pending` = gray, `Scanning` = indigo (pulsing dot),
  `Ready` = emerald, `Error` = rose, `Archived` = slate.
- **File detection confidence**: `Filename only` = gray (dotted ring),
  `Content sniffed` = emerald (solid ring).
- **Importable verdict**: `Importable` = emerald, `Needs review` = amber,
  `Not importable` = slate.
- **Source provider**: GitHub = neutral with `github` icon, GitLab = orange,
  Bitbucket = blue, Public URL = indigo with `link` icon.

## Design system

Mockups intentionally mirror the live `apiome-ui` shell and align with
the sibling mockup sets (`mockups/import`, `mockups/git`, `mockups/browser`,
`mockups/connect`):

- **Typography**: Inter (400/500/600/700), JetBrains Mono for SHAs, paths,
  branch names, byte counts, durations
- **Accent**: indigo-500 / 600 (Radix `accentColor="indigo"`)
- **Gray scale**: slate (Radix `grayColor="slate"`)
- **Layout**: 280 px gradient sidebar, 48 px top platform bar, panel cards
  (`bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700`)
- **Icons**: Lucide (CDN), matching the live `lucide-react` icon set —
  `folder-git-2` is the Repository Store product mark
- **Theme**: class-based dark-mode toggle, persisted to `localStorage` under
  `repositories-mockup-theme`. Honors `prefers-color-scheme` on first load.

## Conventions matched from production code

- Section headers in the sidebar use `text-[0.65rem]` uppercase with a 1×1
  indigo dot (`DashboardSideNav.tsx`)
- Active nav items use a 10 % indigo fill + 1 px border + indigo text + a
  small dot indicator
- Page headers follow the `<h2>` + lucide icon + subtitle pattern from
  `dashboard/page.tsx`
- File / path / SHA columns use the `mono` class (JetBrains Mono)
- All status pills follow the `text-[10px] uppercase tracking-wider px-2
  py-0.5 rounded` pattern shared with `mockups/import`

## What's intentionally faked

- All repositories, branches, file lists, SHAs, sizes, scan stats,
  importable verdicts, project mappings, and import history are hard-coded
- The "Scan now" / "Re-scan" / "Import" / "Map to project" buttons are inert
- File contents shown in `file-detail.html` are pre-rendered fixtures
- The **Visualize** tab on `file-detail.html` is a static SVG + absolutely-
  positioned div facsimile of a React Flow canvas (no real layout engine,
  no zoom/pan, no draggable nodes). When implemented for real it should use
  `@xyflow/react` (already a dependency of `apiome-ui` for the editor),
  hydrate nodes/edges from the parsed spec server-side via the existing
  importer pipeline, and reuse the shared node theme tokens (emerald = reuse,
  indigo = update, purple = nested type, amber = new) so the preview matches
  the post-import editor visualization 1-for-1.
- The file-tree breadcrumb does not actually paginate or virtualize
- The theme toggle and Lucide icon hydration are the only working JS

## Implementation guardrails (for the LLM that picks this up next)

1. **Postgres only.** No `Map`, no `Set`, no module-scoped caches in
   `apiome-rest` for repository file listings, scan queues, or import
   verdicts. If you find yourself reaching for one, write a Postgres table
   instead.
2. **Reuse existing tables.** `apiome.repository`, `apiome.repository_branch`,
   and the existing import-audit tables already exist. Extend them,
   don't shadow them.
3. **Reuse the existing importer.** The "Import" action on
   `import-mapping.html` MUST call the same code path that today's
   "Import OpenAPI into version" button calls. Do not fork a new
   importer.
4. **Reuse Linked Accounts.** Do not invent a new credential store —
   pull GitHub / GitLab / Bitbucket tokens from the tenant's existing
   Linked Accounts records.
5. **Project version on import.** When importing, create a project version
   named after `info.version` from the spec, mirroring the existing
   "import into a new version" flow. If the version already exists,
   surface the existing conflict-resolution UX instead of silently
   overwriting.
6. **Audit everything.** Every scan, every file open, every import, every
   project mapping must produce a `workflow_audit` row attributed to the
   acting user.
7. **No background scanning without a queue.** Scans run as proper
   background jobs (existing worker infra), not as fire-and-forget
   threads inside a request handler.
8. **Build incrementally.** This mockup is intentionally a starting point.
   The user has signaled that the design will iterate. Do not assume the
   mockup is final — re-read this README and the latest mockup HTML
   before generating implementation code.
