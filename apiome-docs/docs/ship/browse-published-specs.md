---
title: "Browse published specs"
description: "Find and read published versions, public or behind an API key."
sidebar_position: 4
tags: [browse, publish]
---

Browse is the read surface for **published** versions. Public versions are reachable without
authentication; private versions require an in-scope API key. A fresh tenant always has at least one
browsable spec — the seeded, published `petstore-sample` project.

---

## In the UI

- Open [Published](./published.mdx) at `/ade/dashboard/published` to see your tenant's published versions.
- The dedicated `apiome-browse` app renders the catalog and each spec's rendered OpenAPI, and
  searches across every published public specification (next section).

## Search the public catalog

The browse app's **Search** page (`/search`) searches the normalized model of every published public
version, not only names and descriptions: organizations, projects, version notes, tags, operations,
parameters, request bodies, responses, schemas and schema properties. Private and unpublished
versions never appear.

### Where to start a search

| From | How |
|---|---|
| Any page | Press <kbd>⌘</kbd><kbd>K</kbd> (<kbd>Ctrl</kbd><kbd>K</kbd>) or <kbd>/</kbd>, or click the search field in the top bar. A palette shows the best matches as you type; <kbd>↑</kbd><kbd>↓</kbd> move, <kbd>↵</kbd> opens, and the first row runs the full search. |
| Home | The hero search box, the **Try** examples, and the **Browse by** tiles — each tile is a search with a filter already applied. |
| `/search` | The search box, the operator chips under it, and the **Browse everything** tiles. |

### Query language

Words, phrases and filters go in one box. Every word must match; filters narrow further.

| Write | To get |
|---|---|
| `create order` | Items mentioning both words |
| `"payment intent"` | Items containing that phrase |
| `orders -deprecated` | Items about orders that do not mention *deprecated* |
| `type:operation` | Only one kind — `organization`, `project`, `version`, `tag`, `operation`, `parameter`, `request_body`, `response`, `schema`, `property` (aliases such as `endpoint` and `model` work) |
| `method:POST` | Operations with that HTTP method |
| `path:/orders` | Operations and their parameters, bodies and responses on paths containing `/orders` |
| `org:acme` · `project:payments` | Published by that organization, or in that project (slug or name) |
| `version:2.1` | In versions whose label contains `2.1` |
| `format:openapi` · `paradigm:rest` | Versions imported from that format or paradigm (the same vocabulary as the directory facets) |
| `tag:stable` | Versions carrying that tag |
| `after:2026-01` · `before:2026-07` | Published on or after, or before, a date (`YYYY`, `YYYY-MM` or `YYYY-MM-DD`) |

Repeating a filter ORs its values (`method:GET method:POST`). An unknown `key:value` is searched as
plain text.

An import records the version's format and paradigm. Versions that existed before Apiome recorded
them were tagged once, so the `format:` and `paradigm:` filters find them too:

| Older version | Format | Paradigm |
|---|---|---|
| Its source was kept when it was imported | The imported format (`openapi-3.1`, `swagger-2.0`, `asyncapi-3`, …) | That format's paradigm |
| An Arazzo file imported from a repository | `arazzo` | `rest` |
| Any other version (built in the designer, the `petstore-sample` project, older OpenAPI imports) | `openapi` | `rest` |

### Results page

- **Scope tabs** — *All*, *Operations*, *Schemas*, *Projects & orgs* and *MCP servers* (the public
  MCP catalog, searched with the same words), each with its count.
- **Filters rail** — latest versions only or every published version, kind, HTTP method,
  organization, paradigm, format and published-date range, with counts for the current results.
  Active filters show as removable chips above the tabs, whether they came from the rail or were
  typed as operators.
- **Results** — grouped by kind or flat; sorted by relevance, newest, oldest or name; 25 a page.
  Operation results show the method and path; operations and schemas open the version page at that
  item. The matched words are highlighted.
- **Top projects** — where the matches concentrate, with a link to each project.
- **Keyboard** — <kbd>/</kbd> focuses the box, <kbd>j</kbd>/<kbd>k</kbd> (or the arrows) move
  through the results, <kbd>↵</kbd> opens the selected one.
- **Share** — the URL carries the whole search (`q`, `scope`, `type`, `org`, `method`, `format`,
  `paradigm`, `after`, `before`, `sort`, `all`, `page`), so **Copy link** gives a colleague the same
  view.

By default a search covers each project's most recently published version. Choose **All published**
in the rail (or add `all=1` to the URL) to include older versions; the same item then appears once
per version.

### Search MCP servers, including the MCP Registry {#search-mcp-servers}

**Browse to `/mcp/search`** in the browse app (the **MCP Catalog** link in the navbar, then the
search box) to search the tools, resources and prompts of every published public MCP server. Results
are sorted by relevance while you search; choose **Top graded** under **Sort** to lead with the
best-graded servers.

To add servers from the [MCP Registry](https://registry.modelcontextprotocol.io), **tick Include MCP
Registry** next to **Sort**. The page then searches the registry for servers whose names match your
words and lists them after the catalog results:

- **Provenance badges.** Each result is labelled **Catalog** (a server published in Apiome) or
  **MCP Registry** (a server listed only in the registry). A registry server that is no longer active
  also shows its status, such as **deprecated**. Registry results show the server name
  (`io.github.acme/weather`), its host, version and transport, and open the server's website when it
  has one.
- **No duplicates.** A registry server that is already published in the catalog is shown once, as the
  catalog result, with an **In MCP Registry** badge. A server counts as the same when its registry
  name matches the one it was imported with, or when one of its remote URLs is the published
  server's URL (ignoring credentials, the query string and a trailing `/`). The note above the results
  says how many registry servers there are and how many were already in the catalog.
- **When the registry is down.** The catalog results still show. The note says the registry could
  not be reached.
- **Share.** The toggle is carried in the URL as `registry=1`.

Operators point the browse app at another registry with `MCP_REGISTRY_SEARCH_URL`, or set it to an
empty value to turn registry search off. Workspaces can run the same federated search over the REST
API — see [Search MCP servers with the registry](../bring-in/mcp-servers.mdx#search-your-catalog-and-the-registry-together).

## Agent manifests: agents.json and llms.txt {#agent-manifests}

Each organization's page in the browse app has two files for agents and crawlers, linked under the
header as **For agents: `agents.json` · `llms.txt`**:

| File | URL in the browse app | What it is |
|---|---|---|
| `agents.json` | `/tenant/{tenant_slug}/agents.json` | A site manifest in the [agents.txt](https://agents-txt.com) `agents.json` shape |
| `llms.txt` | `/tenant/{tenant_slug}/llms.txt` | A Markdown index in the [llms.txt](https://llmstxt.org) shape |

Both list the organization's **published, public** projects only — never a private or draft
version, even when you are signed in. Each project appears once, at its latest published version:

- **Every project** links to that version's page in the browse app, with its paradigm, format and
  version. In `agents.json` they are under `x-apiome-apis`; in `llms.txt`, under `## APIs`.
- **An agent** — a project imported from an A2A Agent Card, an MCP server manifest or an ACP agent
  manifest — is also listed at the address its own source declares, so an agent following the file
  reaches the agent itself:

  | Imported from | Listed under | Address |
  |---|---|---|
  | A2A Agent Card | `a2a` | The card at the agent's well-known address, `https://<agent host>/.well-known/agent-card.json` |
  | MCP server manifest | `mcp` | The server's URL (a server that only runs locally, over stdio, has none) |
  | ACP agent manifest | `acp` | The ACP server's URL |

  In `llms.txt` they are under `## Agents`. An agent whose source names no web address is listed by
  its version page only.

`llms.txt` also links the matching `agents.json` under `## Optional`. Both files can be imported
back as an [Agentic-web site manifest](../bring-in/agents-manifest-import.md). Clients may reuse
them for five minutes.

The browse app builds both files with the REST API, from its server rather than your browser. If the
API's public address is not reachable from that server (inside a container network, for example), set
`APIOME_REST_INTERNAL_BASE_URL` on the browse app to the address that is, such as
`http://rest:8000/v1`.

Next to them, **xRegistry** links the organization's read-only
[xRegistry](./serve-an-xregistry.md): the same public projects as schemas and CloudEvents message
definitions, for xRegistry tools.

## Interactive Swagger UI for a published spec

Every published version has its own hosted Swagger UI:

```
GET /v1/swagger/{tenant_slug}/{project_slug}/{version_slug}
```

Open that URL in a browser (e.g. `http://localhost:8000/v1/swagger/acme-corp/petstore-sample/1.0.0`)
to get a fully interactive API reference for that spec. This is distinct from `/docs`, which
documents the Apiome REST API itself — see [API reference](../reference/api-reference.md).

## With the REST API

```http
GET /v1/browse/tenants/{tenant_slug}/projects                              # public projects
GET /v1/browse/tenants/{tenant_slug}/projects/{project_slug}/versions      # published versions
GET /v1/browse/tenants/{tenant_slug}/agents.json?site_url=…                # the agents.json
GET /v1/browse/tenants/{tenant_slug}/llms.txt?site_url=…                   # the llms.txt
```

`site_url` is the browse app's address (for example `https://browse.apiome.dev`), which the links in
the two manifests start with. Without it, the server's `APIOME_PUBLIC_BROWSE_URL` setting is used;
without either, the links start at `/tenant/…`. A `site_url` that is not an `http`/`https` address,
or has a query, is refused with `422`; an unknown organization is `404`.

These browse routes serve public content without authentication.

## With the CLI

```bash
apiome projects list                    # projects you can see
apiome versions list --project-id <id>  # versions in a project
```

### Open a page in the browse app

`apiome browse open` takes you from the terminal to the rendered page, as `gh repo view --web`
does for a repository:

```bash
apiome browse open acme-corp                                  # the tenant's public projects
apiome browse open acme-corp/payments-api                     # a project and its versions
apiome browse open acme-corp/payments-api/2.1.0               # one version
apiome browse open 'acme-corp/payments-api/compare?v1=2.0.0&v2=2.1.0'   # two versions side by side
```

```text
→ Opening https://browse.apiome.dev/tenant/acme-corp/payments-api/2.1.0 …
```

The path goes under `/tenant/` in the browse app, and anything after the version is kept, so any
browse page can be opened; quote it when it has a `?`. A path starting with `/` is taken from the
browse app's root instead (`apiome browse open /mcp/search`).

| Flag | What it does |
|---|---|
| `--print-url` | Print the URL and open nothing. Use it in CI or over SSH, where there is no display. |
| `--browser NAME` | Use this browser instead of the default — `firefox`, `chrome`, `safari`, or any name Python's `webbrowser` module knows. An unknown name exits 2. |

**Where the browse app is.** The CLI uses the first of these that is set:

1. the `APIOME_BROWSE_URL` environment variable;
2. `url` in the `[browse]` section of the config file (`~/.config/apiome/config.toml`):

   ```toml
   [browse]
   url = "https://specs.example.com"
   ```

3. the REST base URL (`--base-url` / `APIOME_BASE_URL`) with `api.` changed to `browse.`, so
   `https://api.apiome.dev` gives `https://browse.apiome.dev`. A local API (`localhost`,
   `127.0.0.1`) gives the browse dev server on port **3001**.

If none applies, the command exits 2 and says what to set. If no browser can be launched, it exits
1; run it again with `--print-url`.

## Verify

The version you published in [Publish a version](./publish-a-version.md) appears in the published
list and renders in its Swagger UI.

## Related

- [Export a spec](./export-a-spec.md) — download the raw OpenAPI document
- [Compare published versions](./compare-published-versions.md) — what changed between two of them
- [MCP quick-start](../reference/mcp-quickstart.md) — query the same published specs from an MCP host
