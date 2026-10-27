---
title: "Search across formats"
description: "Find operations, types and messages in every API, whatever its format."
sidebar_position: 1.2
tags: [catalog, search, rest, grpc, graphql, asyncapi, openapi]
---

Search across formats answers questions like *"which of our APIs has a `createOrder`
operation?"* in a single query: gRPC services, GraphQL fields, AsyncAPI operations and messages,
Avro records and OpenAPI Projects are all searched together. It searches the normalized model
Apiome builds at import — operations, types and messages — rather than the raw files, so a match
says what it is and which API it belongs to.

It is available through the REST API.

---

## Search

```http
GET /v1/search/{tenant_slug}/model?q=createOrder
```

Send the request with your bearer token or API key, as for any tenant endpoint (see the
[REST API reference](../reference/rest/index.mdx#authentication)).

Each hit names:

- the **element** — its `kind` (`operation`, `type` or `message`), `name`, `key`, and for an HTTP
  operation its `method` and `path`;
- where it sits — `parent` is the service of an operation, the namespace of a type, or the
  operation of a message;
- the **API** — `project_name` / `project_slug`, `publishable` (`true` for a Project, `false` for a
  catalog item) and the revision searched (`version_label`);
- the API's `paradigm`, `format` (with `format_label`) and `quality_grade`.

Hits are ranked by relevance, best first.

### Writing a query

| Write | To find |
|---|---|
| `createOrder` | Elements whose name, key, path or description contains the word. Case does not matter, so `CreateOrder` (gRPC) and `createOrder` (AsyncAPI, OpenAPI) both match |
| `order payment` | Elements mentioning both words |
| `"order created"` | The words next to each other, in that order |
| `invoice or receipt` | Either word |
| `order -legacy` | Elements about orders that do not mention *legacy* |

Words are matched by their English stem, so `orders` finds `order`. A word inside an identifier
is not matched on its own: `order` does not find `createOrder` unless its description mentions
orders.

## Narrow the results

Add any of these filters. Each can be repeated: values of one filter OR together, and different
filters AND.

| Filter | Values |
|---|---|
| `kind` | `operation`, `type`, `message` |
| `protocol` | The paradigm: `rest`, `rpc`, `event`, `graph`, `data_schema`, `agent` (`grpc`, `graphql` and `event-driven` work too) |
| `format` | A source format, such as `openapi-3.1`, `protobuf`, `graphql`, `asyncapi-3`, `avro` |
| `grade` | The revision's quality grade: `A`, `B`, `C`, `D`, `F`, or `ungraded` |

For example, every gRPC or GraphQL operation about orders graded A or B:

```http
GET /v1/search/acme/model?q=order&kind=operation&protocol=rpc&protocol=graph&grade=A&grade=B
```

An unknown value matches nothing; it never returns an error.

The response's `facets` give the count for every value of each filter. Each count is taken over
the results the *other* filters keep, so it tells you how many results you would get by adding
that value. Values you selected are always listed (`selected: true`), even at 0.

## Versions and paging

- Each API's latest version is searched. Add `all_versions=true` to search every version; the
  same element then appears once per version.
- `limit` (1–100, default 25) and `offset` page through the results; `matched` is the number of
  results after filtering and `total` the number before.
- A search considers the 2 000 best matches. When it reaches that, `truncated` is `true` and the
  counts cover those matches only — add a word or a filter to narrow it.

## What is searched

Every import records its normalized model, so APIs you import are searchable straight away.
OpenAPI Projects are searched through their operations and schemas.

Catalog items imported before search across formats shipped become searchable once an
administrator re-indexes them, from `apiome-rest`:

```bash
uv run python scripts/backfill_canonical_models.py
```

The script rebuilds each catalog item's model from the source stored with it and prints a
summary. An item whose source was not stored (it was withheld at import) is listed under
`skips`; re-import it to make it searchable. Running the script again only processes items it has
not indexed yet.

## Related

- [Catalog](./catalog.mdx) — browse and filter catalog items
- [Supported formats](./supported-formats.md)
- [Search reference](../reference/rest/search.md)
