---
title: "Import a Postman collection"
description: "Catalog a Postman Collection v2.0 or v2.1 and its environments as one REST API."
sidebar_position: 36.5
tags: [import, postman, collection, requests, environment]
---

**Postman** is an API client. The **Postman** importer (`postman`) reads a Postman Collection v2.0 or
v2.1, together with any environment files its variables come from, as one **REST** API. By default it
goes into the [Catalog](./catalog.mdx), where you can search, version, diff and convert it like any
other catalog item.

A collection lists the requests you saved. It is not a specification, so Apiome **infers** the API from
those requests: path templates, parameters and body schemas. It uses the same engine as the
[Insomnia](./insomnia-import.md), [Bruno](./bruno-import.md) and [HAR](./har-import.md) imports, and
labels everything it builds **inferred** (see [Declared, inferred and synthesized](./inference-provenance.mdx)).

## What you can import

| You have | What Apiome makes of it |
| --- | --- |
| A Collection **v2.1** export (`.postman_collection.json`) | One catalog item, named after the collection |
| A Collection **v2.0** export | The same. Its version is recorded, and it imports like v2.1 |
| A collection plus one or more environment exports, in one archive (`.zip`, `.tar.gz`) | One catalog item. The environments supply the values of the collection's variables; the collection's own value wins |

To export from Postman, open the collection's **⋯** menu, choose **Export** and pick **Collection
v2.1**. Collection v1 is not supported: export it again as v2.1.

## Import it

- **In the app:** in **Import to catalog**, upload the file on **File Upload** (or paste it) and let
  Apiome detect it as **Postman**.
- **From the CLI:** `apiome import postman ./orders.postman_collection.json`, or an archive that holds
  the collection and its environments. Add `--dry-run` to preview without saving.
- **Through the REST API:** see [Import a specification](./import-a-spec.md).

**As a project instead.** Where the import dialog offers a **Postman Collection** card, it converts a collection to
OpenAPI 3.1 and continues into the [import wizard](./import-wizard.mdx), so it becomes a publishable
project rather than a catalog item. The conversion runs through the same importer, so the project gets
the inferred schemas, the credentials are removed, and the card lists what the conversion left out. Fill
in **Base URL** to set the OpenAPI server. The REST API exposes the same conversion as
`POST /v1/import/{tenant}/postman/openapi` (see [Import sources](../reference/rest/import-sources.md)).

## What each part becomes

| Postman | In the catalog item |
| --- | --- |
| A request | An **operation**, keyed by its method and path (`GET /orders/{orderId}`). Requests to the same method and path become one operation whose schemas cover all of them; the first request names it |
| A folder | An **operation group**: each operation is tagged with its folder path, such as `Orders / Admin` |
| `{{baseUrl}}` at the start of a URL | The **server**: the `baseUrl` variable's value, or a `{baseUrl}` server variable when it has no value or holds a credential |
| `:orderId` in the path, or a numeric or UUID segment | A **path parameter** |
| Query parameters and headers that are not disabled | **Query** and **header parameters** |
| A parameter or header written as a whole variable (`limit` = `{{pageSize}}`) | The parameter's **default** is the variable's value, unless the variable is secret |
| Auth (`bearer`, `basic`, `digest`, `oauth2`, `apikey` …) | The operation's auth **scheme**, with an API key's name and where it is sent. **Never the credential** |
| A raw JSON body | A request **schema** inferred from the body |
| A saved example response | A response for its status code, with a **schema** inferred from its JSON body |
| A raw body that is not JSON | A request typed as a string, labelled **synthesized** |

## Credentials are never kept

- **Auth is read as a scheme only.** Token, password and key values are never read.
- **Every other value is scrubbed** before it reaches the catalog item: URLs, query and header values,
  bodies and variable values. A header or parameter whose name says it holds a secret
  (`Authorization`, `X-Api-Key`, `access_token` …) is redacted whatever its value looks like.
- **Secret variables are listed by name only.** A variable whose name says it holds a credential, or
  whose value the scrubber flags, never becomes a server, a parameter default or an exported value.
- **The stored copy of your upload is scrubbed too.** For Postman, secret scrubbing is always on and
  cannot be switched off ([Secrets in collections and captures](./collection-secret-scrubbing.md)).

## What is declared, not imported

Apiome records these in the import's coverage ledger instead of guessing:

- **Scripts**: pre-request and test scripts on the collection, a folder or a request. Postman runs them;
  they are not modelled.
- **Form-data, URL-encoded, GraphQL and file bodies**: the request is kept, but no request schema is
  inferred from them.
- **Merged requests**: requests that share a method and path, listed by name under the one operation
  they became.
- **A withheld credential**: the request's auth scheme is kept and its credential is not.
- **A secret variable**: its name is kept and its value is not.

## Exporting back to Postman

A catalog item can be exported as a Postman collection: see [Export to an API
client](../ship/export-to-an-api-client.md). A collection imported from Postman is written back with its
own folders, headers, bodies and example responses.

## When an import is refused

| Error code | Why |
| --- | --- |
| `INPUT_MALFORMED` | The file is not valid JSON, or it ends while a value is still open. |
| `INPUT_SEMANTIC_INVALID` | The collection has no requests. |
| `INPUT_ENCODING_INVALID` | The file is not UTF-8 (for example, it was saved as UTF-16). |
| `FORMAT_VERSION_UNSUPPORTED` | The collection is a v1 export. Export it again as v2.1. |
| `FORMAT_MISMATCH` | The file is not a Postman collection, such as an OpenAPI or OpenRPC document. Import it as that format instead. |

## Related

- [Supported formats](./supported-formats.md): what this importer reads.
- [Import an Insomnia collection](./insomnia-import.md) and [Import a Bruno collection](./bruno-import.md):
  the same import for other clients.
- [Declared, inferred and synthesized](./inference-provenance.mdx): why everything a collection import
  builds is labelled inferred.
- [Import a specification](./import-a-spec.md): the import job and its options.
