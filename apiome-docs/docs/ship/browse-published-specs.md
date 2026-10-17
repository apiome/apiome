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
- The dedicated `apiome-browse` app renders the catalog and each spec's rendered OpenAPI.

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
```

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
