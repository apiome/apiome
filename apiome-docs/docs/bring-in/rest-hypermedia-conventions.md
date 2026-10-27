---
title: "REST hypermedia conventions"
description: "How Apiome tags and lints JSON:API, HAL, HAL-FORMS, JSON-LD and Hydra APIs."
sidebar_position: 46
tags: [import, openapi, rest, jsonapi, hal, hydra, json-ld, lint, catalog]
---

JSON:API, HAL, HAL-FORMS, JSON-LD and Hydra are conventions for REST APIs: media types and
document shapes, not schema languages. An API that follows one is still described by an OpenAPI,
Swagger or RAML document. When you import that document, Apiome notices which conventions it
declares, tags the catalog item with them, and checks each body against its convention.

## What is recognized

A convention is recognized from the media type of a request or response body:

| Convention | Media type | What Apiome records |
| --- | --- | --- |
| **JSON:API** | `application/vnd.api+json` | Resource types (the values of `data.type`) |
| **HAL** | `application/hal+json`, `application/hal+xml` | Link relations (`_links`) and embedded resources (`_embedded`) |
| **HAL-FORMS** | `application/prs.hal-forms+json` | Link relations and form templates (`_templates`) |
| **JSON-LD** | `application/ld+json` | Types (the values of `@type`) |
| **Hydra** | JSON-LD that uses Hydra terms (`hydra:member`, a Hydra `@context`), or a Hydra `profile` | Types |

The catalog item lists its conventions, the operations that use each, and the details above. An
API that uses only `application/json` has no convention.

## Filter the catalog by convention

On **Bring in → Catalog**, **choose a convention** in the filter row (**All conventions**):
**JSON:API**, **HAL**, **HAL-FORMS**, **JSON-LD** or **Hydra**, or **No convention** for items that
declare none. The menu appears once an item in your catalog declares a convention, and lists only
the conventions in use. Over the REST API, pass `convention` to
`GET /v1/catalog/{tenant}`; it can be repeated, and `GET /v1/catalog/{tenant}/facets` counts each
value.

## Conformance checks

The `rest-conventions` lint pack runs for every REST API and checks only the conventions it
declares. Its findings show on the item's **Lint & score** tab like any other rule.

| Rule | Checks |
| --- | --- |
| `rest-conventions.jsonapi-top-level` | A JSON:API document has `data`, `errors` or `meta`. |
| `rest-conventions.jsonapi-data-and-errors` | A JSON:API document does not require both `data` and `errors`. |
| `rest-conventions.jsonapi-resource-object` | A resource object in `data` has `type`, and `id` in a response. |
| `rest-conventions.jsonapi-error-document` | A 4xx or 5xx JSON:API response has `errors`. |
| `rest-conventions.hal-self-link` | A HAL resource has a `_links.self` link. |
| `rest-conventions.hal-link-object` | Every HAL link object has `href`. |
| `rest-conventions.hal-forms-template` | A HAL-FORMS document has a `_templates.default` template. |
| `rest-conventions.jsonld-context` | A JSON-LD body has `@context`, or its response sends a `Link` header. |
| `rest-conventions.hydra-collection-member` | A Hydra collection's `member` is an array. |

All of them are warnings. A schema that declares no properties is not checked, and a property any
`allOf`, `oneOf` or `anyOf` branch declares counts as present. See the
[lint rule reference](../build/lint-rules.md#pack-rest-conventions) for each rule's details.

## JSON Type Definition

A JSON Type Definition schema (JTD, RFC 8927) imports as a data schema, the same way a JSON Schema
does: its `properties` become required fields and its `optionalProperties` optional ones. Choose
**JSON Type Definition** in the import wizard, or upload a `.jtd.json` file. See
[Supported formats](./supported-formats.md).
