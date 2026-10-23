---
title: "Import a Thunder Client collection"
description: "Catalog a Thunder Client collection and its environments as one inferred REST API."
sidebar_position: 30
tags: [import, thunder-client, collection, requests, environment]
---

**Thunder Client** is the API client built into VS Code. The **Thunder Client collection** importer
(`thunder-client`) reads a collection export, together with the environment exports its variables
come from, into the [Catalog](./catalog.mdx) as one **REST** API. You can then search, version, diff
and convert it like any other catalog item, and
[export it back to Thunder Client](../ship/export-to-an-api-client.md) (or to Hoppscotch).

A collection lists the requests you saved. It is not a specification, so Apiome **infers** the API
from those requests: path templates, parameters and body schemas. It uses the same engine as
cURL, `.http`, Postman and [Hoppscotch](./hoppscotch-import.md) imports, and labels everything it
builds **inferred** (see [Declared, inferred and synthesized](./inference-provenance.mdx)).

## What you can import

| You have | What Apiome makes of it |
| --- | --- |
| One collection export (`thunder-collection_<name>.json`) | One catalog item, named after the collection |
| A collection plus one or more environment exports (`thunder-environment_<name>.json`), in one archive (`.zip`, `.tar.gz`) | One catalog item. The environments supply the values of the collection's `{{variables}}` |
| Several collection exports in one archive | One catalog item, named after all of them (`Payments · Reporting`) |

In VS Code, open **Thunder Client**, then use the **⋯** menu of a collection in **Collections** and
choose **Export**. Export each environment the same way from **Env**.

Apiome recognises a collection by `"clientName": "Thunder Client"` with `collectionName` and
`requests[]`. An environment is `"clientName": "Thunder Client"` with `data[]`. An environment
uploaded **on its own** is refused, because it has no requests to import.

## Import it

Import the file or the archive like any other specification: in the
[import wizard](./import-wizard.mdx), with `apiome import`, or through the REST API (see
[Import a specification](./import-a-spec.md)). Apiome picks **Thunder Client collection**
(`thunder-client`).

**Upload the environment with the collection.** Thunder Client usually writes the server as a
variable, as in `{{baseUrl}}/v2/orders`. Put the collection and its environment files in one archive
and Apiome fills in the variable's value. Without the environment, the server is kept as a variable
with no value. When several environments define the same variable, the one marked **default** in
Thunder Client wins.

## What each part becomes

| Thunder Client | In the catalog item |
| --- | --- |
| A request | An **operation**, keyed by its method and path (`GET /v2/orders/{orderId}`). Requests to the same method and path become one operation |
| A folder | An **operation group**: each operation is tagged with the folder path it sits in, such as `Tenant A / Read`. Thunder Client stores folders as a flat list linked by `containerId`; Apiome rebuilds the tree from those links |
| `{{variable}}` at the start of a URL (`{{baseUrl}}/v2/orders`) | A **server** `{baseUrl}` with a server variable. Its default is the variable's value from the environment, unless the variable's name says it holds a credential |
| A URL starting with `/`, when the collection has a **Base Url** in its settings | The base URL is put in front of it |
| `:name` or `{{variable}}` inside the path (`/v2/orders/:orderId`) | A **path parameter** `orderId` |
| A full URL (`https://api.example.com/ping`) | A server `https://api.example.com` and the path `/ping` |
| Query parameters that are not disabled | **Query parameters**. A parameter sent by some requests to an operation and not others is optional |
| Headers that are not disabled, including headers set in the collection's or a folder's settings | **Header parameters**. Folders pass their headers down to the requests inside them; a request's own header wins |
| Auth (`bearer`, `basic`, `oauth2`, `ntlm`, `aws` …), including auth inherited from a folder or the collection | The operation's auth **scheme**, with an OAuth 2 grant's grant type, token URL and scopes. **Never the credential** — see below |
| A JSON body | A request **schema** inferred from the body. Bodies sent to the same operation are merged |
| A GraphQL body | A request schema with `query` and `variables` fields, sent as `application/json` |
| A form-encoded or multipart form body | A request schema with one field per form field. A file part is a string field. The body keeps its media type (`application/x-www-form-urlencoded`, `multipart/form-data`) |
| An XML, text or binary body | Nothing is inferred from it; the operation is kept |
| Tests and pre-request steps | Not imported; listed in the coverage ledger |

## Credentials are never kept

A saved request can hold a real token, password or OAuth client secret. Apiome does not keep any
of them:

- **Auth is read as a scheme only.** The bearer token, the basic-auth password and the OAuth 2
  client secret fields are never read; for OAuth 2, only the grant type, token URL and scopes are.
- **Every other value is scrubbed** before it reaches the catalog item: URLs, query and header
  values, bodies and environment values. A header, parameter or form field whose name says it
  holds a secret (`Authorization`, `Cookie`, `X-Api-Key`, `client_secret` …) is redacted whatever
  its value looks like.
- **Credential variables are listed by name only.** Thunder Client environments do not mark
  variables secret, so Apiome treats a variable whose name says it holds a credential (`apiKey`,
  `accessToken`, `clientSecret` …) as secret: it never becomes a server variable default.
- **The stored copy of your upload is scrubbed too.** Apiome keeps the uploaded file so it can be
  converted later. The secret scrubber also finds a Thunder Client auth block's `bearer` value and
  the `{"name": "apiKey", "value": …}` pairs that headers, form fields and environments are saved
  as, so those values are replaced with `«redacted»` in the stored copy as well.

The coverage ledger lists every request whose auth credential was withheld, and every credential
variable.

## What is declared, not imported

Apiome records these in the import's coverage ledger instead of guessing:

- **Tests**: status, timing and JSON-query assertions, and `set-env-var` captures. Thunder Client
  runs them; they are not modelled.
- **Pre-request steps**: variable setters and pre-run requests. They are not modelled.
- **A withheld credential**: the request's auth scheme is kept and its credential is not.
- **A credential variable**: its name is kept and its value is not.

## When an import is refused

| Error code | Why |
| --- | --- |
| `INPUT_MALFORMED` | The file is not valid JSON, or the collection's structure is wrong (a request with no method, a folder without an `_id`). |
| `INPUT_TRUNCATED` | The JSON ends while a value is still open. The file looks cut short. |
| `INPUT_SEMANTIC_INVALID` | The collection has no requests; a folder or request sits in a folder (`containerId`) the collection does not declare, or the folders form a cycle; a request has an empty URL, or a URL written only as a variable that nothing in the upload defines; or the upload holds environments and no collection. |
| `INPUT_ENCODING_INVALID` | The file is not UTF-8 (for example, it was saved as UTF-16). |
| `FORMAT_MISMATCH` | The JSON is not a Thunder Client export, such as a Hoppscotch or Postman collection or an OpenAPI document. Import it as that format instead. |

## Related

- [Supported formats](./supported-formats.md): what this importer reads.
- [Import a Hoppscotch collection](./hoppscotch-import.md): the same import for Hoppscotch.
- [Declared, inferred and synthesized](./inference-provenance.mdx): why everything a collection
  import builds is labelled inferred.
- [Import a specification](./import-a-spec.md): the import job and its options.
- [Export to an API client](../ship/export-to-an-api-client.md): export any HTTP API as a
  Thunder Client collection and environment.
