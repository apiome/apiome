# apiome-docs — the Apiome documentation site

The user documentation for Apiome, built with [Docusaurus 3](https://docusaurus.io/) (classic
preset, TypeScript). Published at **<https://apiome.github.io/apiome/>**.

## Run it

From the repository root:

| Command | What it does |
| --- | --- |
| `yarn docs:dev` | Dev server with live reload at <http://localhost:3200/apiome/> |
| `yarn docs:build` | Production build into `apiome-docs/build/` |
| `yarn docs:serve` | Serve the production build at <http://localhost:3200/apiome/> |
| `yarn docs:check` | Page and screenshot rules (below), then the production build — what CI runs |
| `yarn docs:screenshots` | Recapture the product screenshots in `screens.json` (see [Screenshots](#screenshots)) |
| `yarn workspace apiome-docs test` | Unit tests for the page rules and components |
| `yarn workspace apiome-docs test:e2e` | Browser tests for `<Screenshot/>` against the built site (`yarn docs:build` first) |
| `yarn workspace apiome-docs typecheck` | Type-check the config and components |

`yarn build` (turbo) builds the site with every other workspace.

## Write a page

Pages live in `docs/`, one folder per sidebar group — the same jobs, in the same order, as the
product's navigation rail:

| Group | Folder | URL |
| --- | --- | --- |
| Getting started | `docs/getting-started/` | `/` |
| Build | `docs/build/` | `/build` |
| Bring in | `docs/bring-in/` | `/bring-in` |
| Ship | `docs/ship/` | `/ship` |
| Govern | `docs/govern/` | `/govern` |
| Workspace & account | `docs/workspace/` | `/workspace` |
| Admin & tools | `docs/admin/` | `/admin` |
| Reference | `docs/reference/` | `/reference` |
| Release notes | `release-notes/` (blog) | `/release-notes` |

Each group folder holds a `_category_.json` (label, position) and an `index.mdx` landing page that
lists the group's pages (`<DocCardList />`). The sidebar is generated from the folders, so a new page
shows up as soon as it is saved in one. A group can nest a sub-category the same way — `reference/mock-runtime/`
has a `_category_.json` with a generated index.

The guides that used to live in `docs/guide/` were moved here (DOCS-1.2, #5619);
[`docs/guide/README.md`](../docs/guide/README.md) maps each old file to its page, and `apiome-ui`'s
`LEGACY_GUIDE_ROUTES` sends old `docs/guide/…` links to the same place.

### `.md` or `.mdx`

`markdown.format` is `detect`: a `.md` page is **CommonMark** and a `.mdx` page is **MDX**. Use `.mdx`
when a page needs a component (`<Screenshot/>`, `<Route/>`, `<Kbd/>`). Plain `.md` keeps inline HTML
comments such as the format-count tokens (`51<!--format-count:importable-->`) working, but drops raw
HTML — so mark an anchor as a heading id (`### Apache Arrow {#format-arrow}`), never `<a id>`.

### Generated pages

These pages are written by generators — edit the generator (or its source), not the page:

| Page | Regenerate with |
| --- | --- |
| `bring-in/supported-formats.md` | `cd apiome-rest && uv run python scripts/generate_supported_formats_doc.py` |
| `build/lint-rules.md`, `govern/mcp-*-rules.md` | `cd apiome-rest && uv run python scripts/generate_lint_rule_docs.py` |
| the count tokens in `bring-in/import-a-spec.md`, `ship/export-a-spec.md` | `cd apiome-rest && uv run python scripts/generate_format_counts.py` |
| `reference/rest/**` — a page per OpenAPI tag | `cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py` |
| `reference/cli/**` — a page per command, exit codes | `cd apiome-cli && uv run python scripts/generate_cli_reference_docs.py` |
| `reference/mcp/**` — tools, resources, prompts | `cd apiome-mcp && uv run python scripts/generate_mcp_reference_docs.py` |
| `reference/ci/diff-action.md`, `mock-action.md` — the actions' READMEs | `yarn workspace apiome-docs sync:action-pages` |

Each owning project's test suite fails when its pages are stale, the `reference` job in
`.github/workflows/apiome-docs.yml` runs every generator with `--check`, and `yarn docs:check` fails
when `apiome-rest/openapi.yaml` changed without regenerating `reference/rest/` (the index records the
document's SHA-256 as `openapi_sha256`). Pages written by a generator carry `generated:` in their front
matter, and the in-app guide search does not need a catalog entry for them.

1. Add `docs/<group>/<page>.md` (or `.mdx`, see below).
2. Give it front matter:

   ```mdx
   ---
   title: Cut a version
   description: Freeze a project's current state as a numbered, immutable version.
   sidebar_position: 3
   tags: [versions]
   ---
   ```

   `title` and `description` are required; the description is **14 words or fewer**. Do not repeat
   the title as a `#` heading — the site renders it from the front matter.
3. Write steps with bold UI nouns (“**click New version**”) and quote buttons as they read in the
   product.
4. Link other pages with relative paths or site URLs (`[Ship](/ship)`) — never to `.html` files.

### Components

These are available in every `.mdx` page without an import:

| Component | Use | Example |
| --- | --- | --- |
| `<Screenshot id alt caption?/>` | A product screenshot by manifest id: light or dark with the site theme, lazy-loaded, linked to the full-size image, with a route badge. `alt` is required. Put it on its own line. | `<Screenshot id="catalog" alt="The Catalog page"/>` |
| `<Route path/>` | A badge naming the product route a page describes | `<Route path="/ade/dashboard/versions"/>` |
| `<Kbd keys/>` | A key or chord; `Mod` reads “Ctrl / ⌘”, `Plus` is the + key | `<Kbd keys="Mod+K"/>` |
| `<Flag name on?/>` | A badge marking a feature-flagged surface, naming the flag and whether shipped builds have it on | `<Flag name="FEATURE_GITLIKE"/>` |
| `<Legacy/>` | The callout for a surface that predates the Hive redesign (scheduled under #5272). Required on any page that shows a `legacy`-tagged screenshot. | `<Legacy />` |

### Release notes

Add a post to `release-notes/` named `YYYY-MM-DD-<slug>.mdx` with `title`, `description` and
`authors: [apiome]`, and put `{/* truncate */}` after the summary paragraph.

The per-release posts are generated (DOCS-1.12, #5629) by `scripts/gen-release-notes.ts` at the
repository root, which merges the REST changelog (`apiome-rest/CHANGELOG.md`) with the app's What's
new (`apiome-ui/public/WHATS_NEW.md`) and links every `#1234` to its issue. Do not edit them by hand:

| Post | How it is made |
| --- | --- |
| `release-notes/unreleased.md` — everything after the last closed RC | Regenerated before every `start`, `build` and `check` (`yarn workspace apiome-docs release-notes`); git-ignored, so the site always matches `main` |
| `release-notes/rc<N>.md` — one per closed RC | Pushing a tag `RC<N>` runs `.github/workflows/apiome-release-notes.yml`, which calls `node scripts/gen-release-notes.ts --close RC<N>` and opens a pull request with the post |

`release-notes/releases.json` records each closed RC: the REST versions it carries (`restAfter` <
version ≤ `restThrough`), the git ref its What's new is read at (`whatsNewRef`) and its milestone.
`--close` appends the entry; `node scripts/gen-release-notes.ts --release RC4` re-renders an existing
post (it reads What's new from git, so it needs the full history).

## Screenshots

Every product screenshot is an entry in `screens.json`, captured by `scripts/screenshots.ts`
(Playwright) into `static/img/screens/<id>.<theme>.png` in light and dark at 1440 × 900 — never by
hand. The site's [Contribute to the docs](docs/admin/contribute-to-the-docs.mdx) page documents the
manifest fields and the recipe; in short:

```bash
yarn docs:screenshots -- --id catalog --start-ui      # one entry, starting apiome-ui on :3300
yarn docs:screenshots -- --start-ui --boot            # everything, from the golden-path stack
```

- **Golden-path** entries open the real route signed in as `ada@example.com` against
  `scripts/golden_path/run.sh`; **signed-out** entries open their route with no session (the sign-in
  page); **fixture** entries (and golden-path entries' `fallback`) mount a
  dump from `apiome-ui/e2e/fixtures/` into `/login`, so they need no database.
- Appearance is pinned with `apiome-ui/e2e/support/a11y.ts` (theme, density, font scale, no motion),
  the clock is fixed, and `mask` selectors are painted over, so reruns are byte-identical.
- Set `DOCS_CHROMIUM_PATH` when Playwright's browser is not installed (`yarn playwright install chromium`).
- `.github/workflows/apiome-docs-screenshots.yml` recaptures everything every Monday and opens a pull
  request when an image changed. Entries tagged `legacy` (`"tags": ["legacy"]`, the admin console
  and tools, which predate the Hive redesign) are listed in that pull request when their images
  changed — a sign the redesign (#5272) has landed and the page needs rewriting.

## What the gate checks

`yarn docs:check` runs `scripts/check-docs.mjs` (every rule in `scripts/lib/gate.mjs`), then the
production build. It fails when:

- a page has no `title` or `description`, or the description is over 14 words;
- a folder under `docs/` has no `_category_.json` (with a `label`) or no `index.mdx`;
- a page is an **orphan** — in no sidebar: directly in `docs/` outside every group folder, outside
  every folder and id `sidebars.ts` lists, or hidden by `unlisted: true`, `draft: true` or
  `displayed_sidebar: null`;
- an **internal link** is broken: a relative link to a `.md` / `.mdx` file that does not exist, or a
  site path (`/ship/export-a-spec`) that no page, category landing page, release-notes post or
  `static/` file serves. The build then checks anchors too (`onBrokenLinks`, `onBrokenAnchors` and
  `onBrokenMarkdownLinks` are all `throw`);
- `screens.json` is invalid, or an entry lacks the image for a theme it declares;
- a page uses `<Screenshot id/>` with an id that is not in the manifest or lacks a light or dark
  image (examples in code blocks are ignored), or without `alt` text;
- a page shows a screenshot tagged `legacy` in `screens.json` without the `<Legacy/>` callout;
- a screenshot is **stale**: its image was last committed before the last two closed releases
  (`release-notes/releases.json`) and its route's source changed after it (`git log`). The source is
  the route's folder under `apiome-ui/src/app/`, or the entry's `sources` list when the screen is
  drawn somewhere else (a dialog, a shared component). The rule needs git history; without it (the
  Docker build) it is skipped;
- `docs/reference/rest/` was generated from an older `apiome-rest/openapi.yaml`.

Each failure has a fixture site under `test/fixtures/gate/` that the tests run the gate over, so a
rule that stops firing fails `yarn workspace apiome-docs test`.

## Theme

`src/css/custom.css` maps the Hive tokens (`docs/mockups/assets/hive.css`) onto Infima: navy is the
ink (headings, primary buttons), azure the accent (links, focus, active items), and honey is
ornament only — the hairline under the navbar. Inter and JetBrains Mono are bundled from npm
(`src/fonts.ts`). The bee mark (`static/img/bee-logo.png`, from `apiome-ui/public`) is the logo and
favicon. Dark mode follows the operating system and can be toggled from the navbar. Search is local
(`@easyops-cn/docusaurus-search-local`) and is built with the site.

## Deploy

`.github/workflows/apiome-docs.yml` runs the tests, type-check and `yarn docs:check` on **every**
pull request (DOCS-1.13), and deploys `apiome-docs/build` to GitHub Pages
on every push to `main`. The repository's **Settings → Pages → Source** must be set to
“GitHub Actions” once.

### Docker image

`apiome-docs/Dockerfile` builds the site (running `yarn docs:check`) and serves it with nginx on
port 8080 as a non-root user. Build it from the repository root:

```bash
docker build -f apiome-docs/Dockerfile -t apiome-docs .
docker run --rm -p 3200:8080 apiome-docs   # http://localhost:3200/
```

The image is built for `/` (`DOCS_BASE_URL=/`); pass `--build-arg DOCS_URL=https://docs.example.com`
to set the public origin used in canonical links and the sitemap. `GET /healthz` answers `ok`.

The `image` job in `apiome-docs.yml` builds and smoke-tests the image on pull requests that change its
inputs (the site, the guides, the release-notes sources, the lockfile), and on
`main` pushes it to `$DOCKER_REGISTRY/apiome-docs` tagged with the `package.json` version, `latest`
and the commit SHA. Set the `DOCS_IMAGE_URL` repository variable to the image's public origin.

### Base URL and trailing slashes

| Setting | Default | Override |
| --- | --- | --- |
| `url` | `https://apiome.github.io` | `DOCS_URL` |
| `baseUrl` | `/apiome/` (the GitHub Pages project path) | `DOCS_BASE_URL` (must start and end with `/`) |
| `trailingSlash` | `false` — pages are emitted as `page.html`, which GitHub Pages serves at `/page` | edit `docusaurus.config.ts` |

To serve the site from a custom domain, build with `DOCS_URL=https://docs.example.com DOCS_BASE_URL=/`
and add a `static/CNAME` file.
