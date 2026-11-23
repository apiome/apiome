---
title: "API reference"
description: "Where the REST service's interactive reference lives and how to authenticate."
sidebar_position: 2
tags: [rest]
---

The Apiome REST API is a **FastAPI** application. Its reference is published two ways:

- **On this site** — the [REST API reference](./rest/index.mdx), generated from
  `apiome-rest/openapi.yaml`: a page per tag with every operation's parameters, request body and
  responses. It is regenerated whenever the OpenAPI document changes, and the site build fails if it
  was not.
- **On the running service** — the interactive Swagger UI and ReDoc below, which can also send
  requests.

The REST service listens on **`http://localhost:8000`** by default (the `rest` service in
`docker-compose.yml`).

| Reference | URL | What it is |
|---|---|---|
| **Swagger UI** | `http://localhost:8000/docs` | Interactive, try-it-out reference for every REST route |
| **ReDoc** | `http://localhost:8000/redoc` | Read-optimized rendering of the same spec |
| **OpenAPI document** | `http://localhost:8000/openapi.json` | The raw machine-readable schema |

> In production, substitute your deployed host for `localhost:8000` (e.g.
> `https://api.example.com/docs`). See the production deployment runbook, `docs/runbooks/PRODUCTION_DEPLOY.md`.

---

## Authenticating in Swagger UI

The schema declares two security schemes; click **Authorize** in `/docs` and supply either:

- **Bearer** — a JWT from the UI session (`Authorization: Bearer <token>`), or
- **ApiKey** — a workspace API key sent as the `X-API-Key` header (tenant-scoped access).

Create an API key in the UI under **Dashboard → API keys** (`/ade/dashboard/api-keys`).

## Pagination

Every list that grows with what a workspace stores is served one page at a time. All of them page
the same way.

| Parameter | What it does |
|---|---|
| `limit` | Page size. Each list documents its maximum; for most it is **200**. A larger value is refused with `422`. |
| `cursor` | Where the page starts. Send the previous page's `next_cursor` unchanged; omit it for the first page. |
| `include_total` | Set to `true` to also count the matching rows. Off by default, because counting reads every match. The count stops at 10,000. |
| `offset` | Deprecated. Still accepted where it existed before, up to 10,000. Use `cursor` instead. |

A page tells you whether another follows:

- **Object responses** carry `has_more` and `next_cursor` (`hasMore` and `nextCursor` on responses
  that use camelCase). `total` is `null` unless you sent `include_total=true`; a `total` of 10,000
  means "10,000 or more".
- **Array responses** (projects, versions, catalog items, mocks, classes and paths) keep their JSON
  array body and report the same two facts in the `X-Has-More` and `X-Next-Cursor` response headers.

To read a whole list, request the first page, then repeat with `cursor` set to the value you were
given until `has_more` (or `X-Has-More`) is `false`:

```bash
curl -s -D - -H "X-API-Key: $APIOME_API_KEY" \
  "http://localhost:8000/v1/projects/acme?limit=200"
# X-Has-More: true
# X-Next-Cursor: eyJrIjpbdHJ1ZSwiMjAyNi0xMS0yMlQxMDozMDoxNS4xMjM0NTYrMDA6MDAiLCIwYjhmLi4uIl19

curl -s -H "X-API-Key: $APIOME_API_KEY" \
  "http://localhost:8000/v1/projects/acme?limit=200&cursor=eyJrIjpbdHJ1ZSwi..."
```

A cursor is opaque: do not build or edit one. It belongs to the list and filters it came from, so
keep the other query parameters the same from page to page. A malformed cursor is refused with
`400`.

Paging by cursor costs the same on the last page as on the first. Paging by `offset` reads and
discards every skipped row, which is why it is deprecated and capped.

The lists that hold the parts of one revision (`GET /v1/classes/{tenant}` and
`GET /v1/paths/{tenant}/{version}`) allow up to **1,000** rows a page, so most revisions fit in
one.

The `apiome` CLI follows cursors for you: its list commands return the whole list as before.

## Swagger UI for a *published spec* vs. the API reference

There are two different Swagger UIs in Apiome — don't confuse them:

| You want… | Use |
|---|---|
| To explore the **Apiome REST API** (import, classes, versions, …) | `/docs` (this page) |
| To explore a **published OpenAPI spec** authored in Apiome | `/v1/swagger/{tenant}/{project}/{version}` — see [Browse published specs](../ship/browse-published-specs.md) |

## Related

- [CLI quick-start](./cli-quickstart.md) — the CLI calls these same routes
- [MCP quick-start](./mcp-quickstart.md) — the MCP server exposes published specs to AI hosts
