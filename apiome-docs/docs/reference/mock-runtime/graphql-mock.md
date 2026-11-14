---
title: "GraphQL mocks"
description: "The /graphql route: resolver order, settings, limits and errors."
sidebar_position: 11
tags: [mocks, graphql]
---

A published GraphQL version with its mock turned on answers GraphQL at one extra route on the
same mock host as every other version:

```
https://<mock host>/<tenant>/<project>/<version>/graphql
```

| Method | What it does |
| --- | --- |
| `GET` with no `query` | Opens **GraphiQL** in a browser. It loads the schema through the same URL. |
| `GET ?query=…` | Runs a query. `variables` (JSON text) and `operationName` are optional. |
| `POST` | Runs a query or mutation from a JSON body: `{"query", "variables", "operationName"}`. |

The mock is built from the version's own schema: fragments, variables, aliases, `@include` /
`@skip`, unions, interfaces and introspection all behave as they would on a real server. An unknown
field is a standard GraphQL validation error. Send your API key in `X-Api-Key` exactly as you would
for a REST mock.

```bash
curl -X POST https://mock.apiome.dev/acme/people-graph/1.0.0/graphql \
  -H 'Content-Type: application/json' \
  -d '{"query": "{ user(id: \"1\") { id email posts { title } } }"}'
```

A REST version that has its own `/graphql` operation is unaffected: the route only answers for
versions imported from GraphQL SDL, and everything else falls through to the REST mock.

## Where each value comes from

Every field resolves through the first layer that has a value, in the same order as the REST mock:

| Order | Layer | Applies to |
| --- | --- | --- |
| 1 | **Scenario override**: a canned body becomes the field's value, and a `4xx`/`5xx` status becomes an error on that field | Root fields (`Query.user`) |
| 2 | **Parent value**: a field already present in a scenario body, example or fixture | Nested fields |
| 3 | **Declared example** on the field or root operation, then on the field's type | Any field |
| 4 | **Fixture-pack value** whose name is the field's schema coordinate (`Query.user`, `User.email`) | Any field |
| 5 | **Synthesized value**, seeded per request | Everything else |

A declared example is an `@example(value: …)` directive on the field or type in the SDL (a string
that holds JSON is decoded), or an `example` / `examples` entry the importer kept. A canned body that
leaves fields out is completed by the layers below it, so a scenario only has to say what it
changes.

Synthesized data is **deterministic**: the same query with the same `?__seed=` always returns the
same response, and each field's value depends on its response path, so two fields never share a
value by accident. Interfaces and unions resolve to their first member by name unless a value names
its own `__typename`. A mutation returns its declared payload type, synthesized like any query.

## Scenarios and chaos

Scenarios and chaos entries name a GraphQL root field by its **schema coordinate**, the
`Type.field` form, instead of `METHOD /path`:

```json
{
  "scenarios": {
    "missing-user": {
      "operations": {
        "Query.user": { "responses": [{ "status": 404, "body": { "detail": "No such user." } }] }
      }
    }
  },
  "chaos": { "operations": { "Mutation.createUser": { "errorRate": 25, "delayMs": 400 } } }
}
```

- `X-Mock-Scenario: missing-user` (or the version's **active scenario**) applies the override to
  `user` only. Other root fields in the same request resolve normally.
- A `2xx` canned body is the field's value. A `4xx`/`5xx` response nulls the field and adds an
  `errors[]` entry with `extensions.code = "MOCK_SCENARIO_ERROR"` and the `status`. The message is
  the body's `detail`, `message` or `title`.
- Only the first response of a list is served: a GraphQL request carries several root fields at
  once, so a call sequence has no single position.
- The built-in scenarios work by name. `server-error` fails every root field.
- Chaos delay is the largest delay any selected root field draws. An injected error nulls that root
  field with `extensions.code = "MOCK_CHAOS_INJECTED"`, and the response carries the same
  `X-Mock-Chaos: error` and `X-Mock-Chaos-Delay-Ms` headers as a REST mock.

Saving a scenario checks each coordinate against the version's schema, so a typo such as
`Query.usr` is rejected with the field it could not find. Canned bodies are not checked against a
response schema, because they become a field's value rather than a whole response.

## Settings

The `graphql` key of the version's mock settings sets the limits. Every key is optional:

| Key | Default | Range | What it does |
| --- | --- | --- | --- |
| `maxDepth` | `10` | 1–50 | Deepest field nesting an operation may select. `{ user { name } }` is 2. |
| `maxComplexity` | `1000` | 1–100000 | Largest complexity score. Each field costs 1, multiplied by `listLength` for every list it sits inside. |
| `listLength` | `3` | 0–50 | Items in every synthesized list. |

Introspection fields (`__schema`, `__type`, `__typename`) are not counted, so GraphiQL can always
load the schema. The settings are saved with the scenarios
(`PUT /v1/versions/{tenant}/{project_id}/{version_record_id}/mock/scenarios`, field `graphql`).
Omitting the field keeps what is stored; `null` clears it. They are the `graphql` section of the
`apiome mock config` document, so `pull`, `push` and `diff` round-trip them:

```json
{
  "configFormat": "apiome.mock.config/v1",
  "graphql": { "maxDepth": 6, "maxComplexity": 400, "listLength": 2 }
}
```

They also travel in [portable bundles](./mock-bundle-format.md), so a sandbox applies the same limits.

## Errors

Every GraphQL-level outcome is HTTP `200` with an `errors[]` document, never a bare `5xx`:

| `extensions.code` | When |
| --- | --- |
| `MAX_DEPTH_EXCEEDED` | The operation nests deeper than `maxDepth` (with `depth` and `maxDepth`). |
| `MAX_COMPLEXITY_EXCEEDED` | The operation scores above `maxComplexity` (with `complexity` and `maxComplexity`). |
| `UNSUPPORTED_ON_THIS_DEPLOYMENT` | The operation is a subscription. Subscriptions are not served over HTTP yet. |
| `MOCK_SCENARIO_ERROR` | A scenario answered a root field with a `4xx`/`5xx`. |
| `MOCK_CHAOS_INJECTED` | Chaos injected an error into a root field. |
| `UNKNOWN_SCENARIO` | `X-Mock-Scenario` names a scenario the version does not define. |
| `BAD_REQUEST` | No `query`, a body or `variables` that is not JSON (HTTP `400`), or a mutation sent with `GET` (HTTP `405`). |

Syntax and validation errors (an unknown field, a missing variable) are reported exactly as
`graphql-core` words them.

## Usage and limits

A GraphQL call counts against the tenant's rate limit and monthly quota, and appears in the Mock
cell's sparkline, exactly like a REST call. Its audit path is `/graphql`.

## In a sandbox

The internal `/__sandbox__` endpoint (see [One mock engine](./one-mock-engine.md)) serves the same
route when its payload carries a `graphqlSdl` and the request path is `/graphql`. The bundle supplies
the scenarios, chaos, fixture packs and `graphql` limits; the result is the GraphQL document as a
JSON body.

## See also

- [Mock try-out](../../ship/mock-try-out.mdx): calling a hosted mock, with the Mock cell.
- [Mock fixture packs](./mock-fixture-packs.md): where coordinate-keyed values come from.
- [One mock engine](./one-mock-engine.md): the engine and what a deployment has to reach.
