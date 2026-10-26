---
title: "Import an Insomnia collection"
description: "Catalog an Insomnia v4 or v5 export and its environments as one REST API."
sidebar_position: 37
tags: [import, insomnia, collection, requests, environment]
---

**Insomnia** is a desktop API client. The **Insomnia collection** importer (`insomnia`) reads an
Insomnia export, together with the environments its variables come from, into the
[Catalog](./catalog.mdx) as one **REST** API. You can then search, version, diff and convert it like
any other catalog item.

An export lists the requests you saved. It is not a specification, so Apiome **infers** the API from
those requests: path templates, parameters and body schemas. It uses the same engine as the
[Hoppscotch](./hoppscotch-import.md), [Thunder Client](./thunder-client-import.md) and
[HAR](./har-import.md) imports, and labels everything it builds **inferred** (see
[Declared, inferred and synthesized](./inference-provenance.mdx)).

## What you can import

| You have | What Apiome makes of it |
| --- | --- |
| A **v5** export (`.yaml`, Insomnia 10 and later) | One catalog item, named after the collection |
| A **v4** export (`.json`, *Insomnia v4* export format) | One catalog item, named after the workspace |
| A design document (`spec.insomnia.rest/5.0`) | One catalog item from its requests. Its API spec is not read here — import the spec as OpenAPI |
| An export plus one or more environment exports, in one archive (`.zip`, `.tar.gz`) | One catalog item. The environments supply the values of the collection's variables |

To export from Insomnia, open the collection, select its name at the top of the sidebar and choose
**Export**. Pick **Insomnia v5** (YAML) or **Insomnia v4** (JSON); both import the same way.

Apiome recognises a v5 export by its first-level `type: collection.insomnia.rest/5.0` line and a v4
export by `"_type": "export"` with `"__export_format": 4`. An environment uploaded **on its own** is
refused, because it has no requests to import.

## Import it

Import the file or the archive like any other specification: in the
[import wizard](./import-wizard.mdx), with `apiome import`, or through the REST API (see
[Import a specification](./import-a-spec.md)). Apiome picks **Insomnia collection** (`insomnia`).

## What each part becomes

| Insomnia | In the catalog item |
| --- | --- |
| A request | An **operation**, keyed by its method and path (`GET /v1/users/{userId}`). Requests to the same method and path become one operation |
| A folder | An **operation group**: each operation is tagged with its folder path, such as `Users / Admin`. A v4 export stores folders as a flat list linked by `parentId`; Apiome rebuilds the tree |
| `{{ _.variable }}` at the start of a URL (`{{ _.baseUrl }}/v1/users`) | A **server** `{baseUrl}` with a server variable. Its default is the variable's value from the environments, unless the variable is secret |
| `:name` or `{{ _.variable }}` inside the path | A **path parameter** (`userId`) |
| A full URL (`https://api.example.com/ping`) | A server `https://api.example.com` and the path `/ping`. A URL with no scheme (`localhost:3000/x`) is `http` |
| Query parameters and headers that are not disabled, including headers set on a folder | **Query** and **header parameters**. Folders pass their headers down; a request's own header wins |
| A parameter or header written as a whole variable (`limit` = `{{ _.pageSize }}`) | The parameter's **default** is the variable's value, unless the variable is secret |
| Auth (`bearer`, `basic`, `digest`, `oauth2`, `apikey`, `iam`, `ntlm` …), including auth a request inherits from its folder | The operation's auth **scheme**, with an OAuth 2 grant's grant type, URLs and scopes, or an API key's header name and where it is sent. **Never the credential** — see below |
| A JSON body | A request **schema** inferred from the body. A body written with a bare variable (`"qty": {{ _.qty }}`) still infers |
| A GraphQL body | A request schema with `query` and `variables`, sent as `application/json` |
| A form-encoded or multipart body | A request schema with one field per form field. A file part is a string field. The body keeps its media type |
| An XML, text or file body | Nothing is inferred from it; the operation keeps its media type |

**Which environment's value wins.** The **base** environment's value is used. A variable that only
sub-environments (*Staging*, *Production* …) define takes the first one's value, in Insomnia's order.
A folder's own environment overrides both for the requests inside it. Variables may refer to other
variables (`https://{{ _.host }}/v2`), and nested values (`{{ _.api.host }}`) work.

## Credentials are never kept

A saved request can hold a real token, password, OAuth client secret or API key. Apiome keeps none of
them:

- **Auth is read as a scheme only.** Token, password, client-secret, access-token and API-key value
  fields are never read.
- **Every other value is scrubbed** before it reaches the catalog item: URLs, query and header values,
  bodies and environment values. A header, parameter or form field whose name says it holds a secret
  (`Authorization`, `X-Api-Key`, `password` …) is redacted whatever its value looks like.
- **Secret variables are listed by name only.** A variable whose name says it holds a credential
  (`accessToken`, `clientSecret` …), or one Insomnia marks as a **secret**, never becomes a server
  variable or parameter default.
- **Cookie jars are never read.**
- **The stored copy of your upload is scrubbed too.** Apiome keeps the uploaded file so it can be
  converted later. For Insomnia, secret scrubbing is always on and cannot be switched off
  ([Secrets in collections and captures](./collection-secret-scrubbing.md)). It redacts
  credentials in both JSON and YAML exports, including name/value pairs, `token:` values, cookie jars
  and secret-typed variables, replacing them with `«redacted»`.

## What is declared, not imported

Apiome records these in the import's coverage ledger instead of guessing:

- **Scripts**: pre-request and after-response scripts. Insomnia runs them; they are not modelled.
- **Template tags** (`{% response … %}`, `{% uuid %}`): evaluated by Insomnia when it sends the
  request. The request is kept, and a tag in its path becomes a path parameter.
- **gRPC and WebSocket requests**, **unit tests**, **mock routes** and a design document's **API spec**:
  listed by name; not modelled.
- **Cookie jars**: never read.
- **A withheld credential**: the request's auth scheme is kept and its credential is not.
- **A secret variable**: its name is kept and its value is not.

## Exporting back to Insomnia

Apiome does not export Insomnia collections yet. To get a catalog item into an API client, export it
as a [Hoppscotch or Thunder Client collection](../ship/export-to-an-api-client.md), or as OpenAPI,
which Insomnia imports.

## When an import is refused

| Error code | Why |
| --- | --- |
| `INPUT_MALFORMED` | The file is not valid JSON or YAML, or its structure is wrong (`resources` is not a list, a request has no method). |
| `INPUT_TRUNCATED` | The JSON or YAML ends while a value is still open. The file looks cut short. |
| `INPUT_SEMANTIC_INVALID` | The export has no HTTP requests (only folders, gRPC or WebSocket requests, or just an API spec); a v4 resource names a `parentId` the export does not declare; a request has an empty URL, or one written only as a variable nothing defines; or the upload is an environment or a mock server on its own. |
| `INPUT_ENCODING_INVALID` | The file is not UTF-8 (for example, it was saved as UTF-16). |
| `FORMAT_VERSION_UNSUPPORTED` | The export is in an older format (for example `__export_format: 3`). Export it again from a current Insomnia. |
| `FORMAT_MISMATCH` | The file is not an Insomnia export, such as a Postman collection or an OpenAPI document. Import it as that format instead. |

## Related

- [Supported formats](./supported-formats.md): what this importer reads.
- [Import a Thunder Client collection](./thunder-client-import.md) and
  [Import a Hoppscotch collection](./hoppscotch-import.md): the same import for other clients.
- [Declared, inferred and synthesized](./inference-provenance.mdx): why everything a collection
  import builds is labelled inferred.
- [Import a specification](./import-a-spec.md): the import job and its options.
