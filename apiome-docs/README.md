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
| `yarn docs:check` | Page rules (below), then the production build — what CI runs |
| `yarn workspace apiome-docs test` | Unit tests for the page rules and components |
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
shows up as soon as it is saved in one. A group can nest a sub-category the same way — `ship/mocks/`
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

Five pages are written by `apiome-rest` generators — edit the generator, not the page:

| Page | Regenerate with (from `apiome-rest/`) |
| --- | --- |
| `bring-in/supported-formats.md` | `uv run python scripts/generate_supported_formats_doc.py` |
| `build/lint-rules.md`, `govern/mcp-*-rules.md` | `uv run python scripts/generate_lint_rule_docs.py` |
| the count tokens in `bring-in/import-a-spec.md`, `ship/export-a-spec.md` | `uv run python scripts/generate_format_counts.py` |

The `apiome-rest` test suite fails when any of them is stale.

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
| `<Screenshot id alt caption?/>` | A product screenshot by manifest id. A placeholder until the screenshot pipeline lands (DOCS-1.3, #5620). Put it on its own line. | `<Screenshot id="projects-list" alt="The Projects list"/>` |
| `<Route path/>` | A badge naming the product route a page describes | `<Route path="/ade/dashboard/versions"/>` |
| `<Kbd keys/>` | A key or chord; `Mod` reads “Ctrl / ⌘”, `Plus` is the + key | `<Kbd keys="Mod+K"/>` |

### Release notes

Add a post to `release-notes/` named `YYYY-MM-DD-<slug>.mdx` with `title`, `description` and
`authors: [apiome]`, and put `{/* truncate */}` after the summary paragraph.

## What the gate checks

`yarn docs:check` fails when:

- a page has no `title` or `description`, or the description is over 14 words;
- a folder under `docs/` has no `_category_.json` (with a `label`) or no `index.mdx`;
- any internal link, Markdown link or anchor is broken (`onBrokenLinks`, `onBrokenAnchors` and
  `onBrokenMarkdownLinks` are all `throw`).

DOCS-1.13 (#5630) extends it with orphan-page and screenshot checks.

## Theme

`src/css/custom.css` maps the Hive tokens (`docs/mockups/assets/hive.css`) onto Infima: navy is the
ink (headings, primary buttons), azure the accent (links, focus, active items), and honey is
ornament only — the hairline under the navbar. Inter and JetBrains Mono are bundled from npm
(`src/fonts.ts`). The bee mark (`static/img/bee-logo.png`, from `apiome-ui/public`) is the logo and
favicon. Dark mode follows the operating system and can be toggled from the navbar. Search is local
(`@easyops-cn/docusaurus-search-local`) and is built with the site.

## Deploy

`.github/workflows/apiome-docs.yml` runs the tests, type-check and `yarn docs:check` on every pull
request that touches `apiome-docs/**` or `docs/**`, and deploys `apiome-docs/build` to GitHub Pages
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

The `image` job in `apiome-docs.yml` builds and smoke-tests the image on every pull request, and on
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
