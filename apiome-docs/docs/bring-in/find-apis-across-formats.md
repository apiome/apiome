---
title: "Find APIs across formats"
description: "Filter, categorize and search every API by protocol, format, domain and tag."
sidebar_position: 1.12
tags: [catalog, search, browse]
---

Your catalog can hold OpenAPI documents, gRPC services, GraphQL schemas, AsyncAPI event APIs,
Avro records, agent cards and more. Apiome records two things about every one of them at import,
so you can find them side by side instead of in one list per format:

- its **protocol** (also called its *paradigm*), the kind of API it is: **REST**, **RPC**,
  **event-driven**, **graph**, **data schema** or **agent**;
- its **format**, the exact source it came from: `openapi-3.1`, `swagger-2.0`, `protobuf`,
  `graphql`, `asyncapi-3`, `avro` and so on.

On top of those, you can give an item a **domain** and **tags** of your own. All four are filters
everywhere you look for an API.

## Where to look

| To | Use | Where |
| --- | --- | --- |
| Narrow your catalog to one kind of API | The Catalog's filters | **Catalog** (`/ade/dashboard/catalog`) — [Find an item](./catalog.mdx#find-an-item) |
| Group or label items by domain and tag | **Categorize…** on an item | **Catalog** — [Categorize an item](./catalog.mdx#categorize-an-item) |
| Find an operation, type or message in any format | Search across formats | `GET /v1/search/{tenant_slug}/model` — [Search across formats](./search-across-formats.md) |
| Find published public APIs by protocol or format | The **Paradigm** and **Format** chips, and the `format:` / `paradigm:` search operators | The browse app — [Browse published specs](../ship/browse-published-specs.md) |

## Filter the Catalog

On the **Catalog**, narrow the list by **Formats**, by protocol (**REST**, **RPC**, **Event**,
**Graph**, **Data Schema**, **Agent**), and by **domain** and **tag**. The search box also matches
a format or protocol by name. In **Cards** view, cards can be **grouped by protocol**, so each
kind of API gets its own section.

<Screenshot id="catalog-cards" alt="The Catalog in Cards view, grouped by protocol" />

## Categorize an item

Every item has three categories:

| Category | Set by | Can it change? |
| --- | --- | --- |
| **Paradigm** | Apiome, from the imported source | No |
| **Domain** | You — one of the domains Projects use (Finance, Healthcare, IoT, …), or none | Yes |
| **Tags** | You — any words that help your team find it | Yes |

**Click ⋯ → “Categorize…”** on a card or row, choose a **Domain**, add tags and **click “Save”**.
The **domain** and **tag** filters list the new values straight away. The full steps are in
[Categorize an item](./catalog.mdx#categorize-an-item).

<Screenshot id="catalog-categorize" alt="The Categorize dialog: the derived paradigm, a Domain menu and four tags" />

## Search inside every API

Search across formats looks inside the APIs, not just at their names: *“which of our APIs has a
`createOrder` operation?”* returns gRPC methods, GraphQL fields, AsyncAPI operations and OpenAPI
operations together, each naming the API it belongs to.

```http
GET /v1/search/acme/model?q=order&kind=operation&protocol=rpc&protocol=graph&grade=A
```

Filter by `kind`, `protocol`, `format` and `grade`. Values of one filter OR together, and different
filters AND. See [Search across formats](./search-across-formats.md) for the query syntax and
the response.

## Browse published public APIs

The browse app's organization directory and each organization's project list show **Paradigm**
and **Format** chips above the list, each with a count. **Click a chip** to list only the
organizations or projects that publish that kind of API; click it again, or **click “Clear
filters”**, to see everything. The counts always cover the whole list, so they show what else you
could pick. Each project row carries its own paradigm and format chips.

The browse app's **Search** page takes the same vocabulary as operators — `paradigm:rest`,
`format:openapi` — see [Query language](../ship/browse-published-specs.md#query-language).

Over the REST API, `GET /v1/browse/tenants` and `GET /v1/browse/tenants/{tenant_slug}/projects`
accept `protocol` and `format` and return a `facets` block with the same counts.

## The vocabulary

Every surface uses the same protocol values. The REST filters (`protocol` on the catalog, search
and browse routes) are forgiving about how you write them: case, hyphens and spaces are ignored,
and these words mean the same thing:

| Protocol | Also accepted |
| --- | --- |
| `rest` | `http` |
| `rpc` | `grpc` |
| `event` | `events`, `event-driven`, `messaging` |
| `graph` | `graphql` |
| `data_schema` | `data-schema`, `schema`, `data` |
| `agent` | `agentic`, `mcp` |

A value Apiome does not recognise matches nothing; it never returns an error. A version imported
before Apiome recorded formats was tagged once from its kept source, so older versions are found
too — see [Browse published specs](../ship/browse-published-specs.md#query-language).

## Related

- [Catalog](./catalog.mdx) — the list, its filters and each item's page
- [Search across formats](./search-across-formats.md) — the full search reference
- [Supported formats](./supported-formats.md) — every format and its protocol
- [Browse published specs](../ship/browse-published-specs.md) — the public browse app
