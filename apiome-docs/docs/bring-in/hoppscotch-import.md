---
title: "Import a Hoppscotch collection"
description: "Catalog a Hoppscotch collection and its environments as one inferred REST API."
sidebar_position: 29
tags: [import, hoppscotch, collection, requests, environment]
---

**Hoppscotch** is the open-source API client many teams move to from Postman. The **Hoppscotch
collection** importer (`hoppscotch`) reads a collection export, together with the environment
exports its variables come from, into the [Catalog](./catalog.mdx) as one **REST** API. You can
then search, version, diff and convert it like any other catalog item, and
[export it back to Hoppscotch](../ship/export-to-an-api-client.md) (or to Thunder Client).

A collection lists the requests you saved. It is not a specification, so Apiome **infers** the API
from those requests: path templates, parameters and body schemas. It uses the same engine as
cURL, `.http` and Postman imports, and labels everything it builds **inferred** (see
[Declared, inferred and synthesized](./inference-provenance.mdx)).

## What you can import

| You have | What Apiome makes of it |
| --- | --- |
| One collection export (`.json`) | One catalog item, named after the collection |
| An export of several collections (one JSON array) | One catalog item, named after all of them (`Payments · Reporting`) |
| A collection plus one or more environment exports, in one archive (`.zip`, `.tar.gz`) | One catalog item. The environments supply the values of the collection's `<<variables>>` |

In Hoppscotch, export the collection as JSON from its menu in **Collections**, and each
environment as JSON from its menu in **Environments**.

Apiome recognises a collection by its tree: a `name` with `folders[]` and `requests[]`. An
environment is a `name` with `variables[]`. An environment uploaded **on its own** is refused,
because it has no requests to import.

## Import it

Import the file or the archive like any other specification: in the
[import wizard](./import-wizard.mdx), with `apiome import`, or through the REST API (see
[Import a specification](./import-a-spec.md)). Apiome picks **Hoppscotch collection**
(`hoppscotch`).

**Upload the environment with the collection.** Hoppscotch writes the server as a variable, as in
`<<baseUrl>>/v2/orders`. Put the collection and its environment files in one archive and Apiome
fills in the variable's value. Without the environment, the server is kept as a variable with no
value.

## What each part becomes

| Hoppscotch | In the catalog item |
| --- | --- |
| A request | An **operation**, keyed by its method and path (`GET /v2/orders/{orderId}`). Requests to the same method and path become one operation |
| A folder | An **operation group**: each operation is tagged with the folder path it sits in, such as `Catalogue / Products` |
| `<<variable>>` at the start of an endpoint (`<<baseUrl>>/v2/orders`) | A **server** `{baseUrl}` with a server variable. Its default is the variable's value from the environment, unless the variable is marked secret |
| `<<variable>>` inside the path (`/v2/orders/<<orderId>>`) | A **path parameter** `orderId` |
| A full URL (`https://api.example.com/ping`) | A server `https://api.example.com` and the path `/ping` |
| Active query parameters | **Query parameters**. Inactive ones are left out. A parameter sent by some requests to an operation and not others is optional |
| Active headers, including headers set on the collection or a folder | **Header parameters**. Folders pass their headers down to the requests inside them; a request's own header wins |
| Auth (`bearer`, `basic`, `digest`, `api-key`, `oauth-2`, `jwt` …), including auth inherited from a folder or the collection | The operation's auth **scheme**, with the API key's header or query name and the OAuth 2 grant type, token URL and scopes. **Never the credential** — see below |
| A JSON body | A request **schema** inferred from the body. Bodies sent to the same operation are merged |
| A URL-encoded or multipart form body | A request schema with one field per form field. A file part is a string field. The body keeps its media type (`application/x-www-form-urlencoded`, `multipart/form-data`) |
| A saved example response | A response schema for that status code |
| A pre-request or test script | Not imported; listed in the coverage ledger |

Variables resolve in Hoppscotch's own order: a request variable first, then the environment, then
the collection's variables.

## Credentials are never kept

A saved request can hold a real token, password, API key or OAuth client secret. Apiome does not
keep any of them:

- **Auth is read as a scheme and names only.** The token, password, API key value and client
  secret fields are never read.
- **Every other value is scrubbed** before it reaches the catalog item: endpoints, query and
  header values, bodies and environment values. A header, parameter or form field whose name says
  it holds a secret (`Authorization`, `Cookie`, `client_secret`, `api_key` …) is redacted
  whatever its value looks like.
- **Secret environment variables are listed by name only.** A variable Hoppscotch marks secret
  never becomes a server variable default.
- **The stored copy of your upload is scrubbed too.** Apiome keeps the uploaded file so it can be
  converted later. The secret scrubber now also finds a Hoppscotch auth block's `token` and the
  `{"key": "apiKey", "value": …}` pairs that client exports use, so those values are replaced with
  `«redacted»` in the stored copy as well.

The coverage ledger lists every request whose auth credential was withheld, and every secret
variable.

## What is declared, not imported

Apiome records these in the import's coverage ledger instead of guessing:

- **A script**: pre-request and test scripts are JavaScript that the client runs. They are not
  modelled.
- **A withheld credential**: the request's auth scheme is kept and its credential is not.
- **A secret variable**: its name is kept and its value is not.

## When an import is refused

| Error code | Why |
| --- | --- |
| `INPUT_MALFORMED` | The file is not valid JSON, or the collection's structure is wrong (a request with no method, a folder without `folders[]` and `requests[]`). |
| `INPUT_TRUNCATED` | The JSON ends while a value is still open. The file looks cut short. |
| `INPUT_SEMANTIC_INVALID` | The collection has no requests in it or in any folder; a request has an empty endpoint, or an endpoint written only as a variable that nothing in the upload defines; or the upload holds environments and no collection. |
| `INPUT_ENCODING_INVALID` | The file is not UTF-8 (for example, it was saved as UTF-16). |
| `FORMAT_MISMATCH` | The JSON is not a Hoppscotch collection, such as a Postman collection or an OpenAPI document. Import it as that format instead. |

## Related

- [Supported formats](./supported-formats.md): what this importer reads.
- [Declared, inferred and synthesized](./inference-provenance.mdx): why everything a collection
  import builds is labelled inferred.
- [Import a specification](./import-a-spec.md): the import job and its options.
- [Export to an API client](../ship/export-to-an-api-client.md): export any HTTP API as a
  Hoppscotch collection and environment.
