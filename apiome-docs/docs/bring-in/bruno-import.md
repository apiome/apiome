---
title: "Import a Bruno collection"
description: "Catalog a Bruno collection folder, from an archive or git, as one REST API."
sidebar_position: 38
tags: [import, bruno, collection, requests, git, environment]
---

**Bruno** is an API client that keeps collections as plain files in git. The **Bruno collection**
importer (`bruno`) reads a collection folder into the [Catalog](./catalog.mdx) as one **REST** API.
You can then search, version, diff and convert it like any other catalog item.

A collection lists the requests you saved. It is not a specification, so Apiome **infers** the API
from those requests: path templates, parameters and body schemas. It uses the same engine as the
[Insomnia](./insomnia-import.md), [Thunder Client](./thunder-client-import.md) and
[HAR](./har-import.md) imports, and labels everything it builds **inferred** (see
[Declared, inferred and synthesized](./inference-provenance.mdx)).

## What you can import

| You have | What Apiome makes of it |
| --- | --- |
| A collection folder (`bruno.json`, its `.bru` files, `collection.bru`, `folder.bru` and `environments/`), zipped (`.zip`, `.tar.gz`) | One catalog item, named after the collection |
| The same folder in a git repository | One catalog item, identical to the archive import — same operations, same fingerprint |
| A single `.bru` request file (uploaded or pasted) | One catalog item with that one operation |

Apiome recognises a collection by its `bruno.json` (`"type": "collection"`), and a request file by its
`meta { … }` block and a method block such as `get { … }`. `bruno.json` on its own, or an environment
or `folder.bru` file on its own, is refused, because it has no requests to import.

## Import it

- **As an archive:** zip the collection folder (the folder that holds `bruno.json`) and import the
  archive in the [import wizard](./import-wizard.mdx), with `apiome import`, or through the REST API (see
  [Import a specification](./import-a-spec.md)). It does not matter whether the zip has the folder at its
  top level or the files directly.
- **From git:** in **Import to catalog**, choose the **Git repository** source and select the collection
  folder (for example `api/bruno/**`). See the [import wizard](./import-wizard.mdx).

Apiome picks **Bruno collection** (`bruno`). Paths inside the collection are read relative to
`bruno.json`, which is why an archive and a git selection import the same API. Files `bruno.json`
lists under `ignore` (such as `node_modules`), and files outside the collection folder, are skipped.

## What each part becomes

| Bruno | In the catalog item |
| --- | --- |
| A request `.bru` file | An **operation**, keyed by its method and path (`GET /v1/users/{id}`). Requests to the same method and path become one operation |
| A folder | An **operation group**: each operation is tagged with its folder path, such as `Users / Admin`. A folder's `folder.bru` `meta` name is used when it has one |
| `{{variable}}` at the start of a URL (`{{baseUrl}}/v1/users`) | A **server** `{baseUrl}` with a server variable. Its default is the variable's value, unless the variable is secret |
| `:name` or `{{variable}}` inside the path | A **path parameter** (`id`) |
| `params:query` and `headers` entries that are not disabled (`~`), including headers in `collection.bru` and `folder.bru` | **Query** and **header parameters**. A request's own header wins |
| A parameter or header written as a whole variable (`limit: {{pageSize}}`) | The parameter's **default** is the variable's value, unless the variable is secret |
| `auth` (`bearer`, `basic`, `digest`, `oauth2`, `apikey`, `awsv4`, `ntlm`, `wsse`), including `inherit` from the folder or collection | The operation's auth **scheme**, with an OAuth 2 grant's grant type, URL and scopes, or an API key's header name. **Never the credential** — see below |
| The body the method block's `body:` mode selects (`json`, `formUrlEncoded`, `multipartForm`, `graphql`, `xml`, `text`) | A JSON, form or multipart body becomes a request **schema** (a file part is a string field); a GraphQL body is `query` + `variables`; XML and text keep their media type. Body blocks for other modes are ignored |

**Which value a variable takes.** Bruno's order: the request's own `vars:pre-request`, then its
folders', then the environments, then `collection.bru`. Bruno does not record which environment is
active, so the first environment by file name (`environments/local.bru` before
`environments/staging.bru`) that defines a variable gives its value.

## Credentials are never kept

A `.bru` file can hold a real token, password, client secret or API key. Apiome keeps none of them:

- **Auth is read as a scheme only.** Token, password, client-secret and API-key value fields are never
  read.
- **Every other value is scrubbed** before it reaches the catalog item: URLs, query and header values,
  and bodies. A header, parameter or form field whose name says it holds a secret (`X-Api-Key`,
  `password` …) is redacted whatever its value looks like.
- **Secret variables are listed by name only.** A variable an environment lists under `vars:secret`, or
  whose name says it holds a credential, never becomes a server variable or parameter default.
- **`.env` files are never read.** Neither archive nor git intake picks up dotfiles, so
  `{{process.env.*}}` values stay unresolved.
- **The stored copy of your upload is scrubbed too.** For Bruno, secret scrubbing is always on and
  cannot be switched off. Credential values in a stored `.bru` file are replaced with `«redacted»`.
  An archive or git selection that holds a credential is not stored at all; only its member list is.
  See [Secrets in collections and captures](./collection-secret-scrubbing.md).

## What is declared, not imported

Apiome records these in the import's coverage ledger instead of guessing:

- **Scripts**: `script:pre-request`, `script:post-response` and `vars:post-response`, at the request,
  folder or collection level. Bruno runs them; they are not modelled.
- **Tests and assertions**: `tests` and `assert` blocks.
- **`{{process.env.*}}`**: the request is kept with the variable unresolved.
- **Requests that are not HTTP** (gRPC, WebSocket): listed by name.
- **A withheld credential** and **a secret variable**: the scheme and the name are kept, not the value.

Blocks Bruno adds in future versions are skipped without failing the import.

## Exporting back to Bruno

Apiome does not export Bruno collections yet. To get a catalog item into an API client, export it as a
[Hoppscotch or Thunder Client collection](../ship/export-to-an-api-client.md), or as OpenAPI, which
Bruno imports.

## When an import is refused

| Error code | Why |
| --- | --- |
| `INPUT_MALFORMED` | A `.bru` file has a line outside any block, or a `key: value` line with no `:`; a request has no method block; or `bruno.json` is not a JSON object. |
| `INPUT_TRUNCATED` | A `.bru` block (or a `'''` value) is never closed, or `bruno.json` ends while a value is still open. |
| `INPUT_SEMANTIC_INVALID` | The collection has no HTTP requests; the upload has `.bru` files but no `bruno.json`; a request has no URL, or one written only as a variable nothing defines; or the upload is `bruno.json`, an environment or a folder file on its own. |
| `INPUT_ENCODING_INVALID` | A file is not UTF-8 (for example, it was saved as UTF-16). |
| `FORMAT_MISMATCH` | The upload is not a Bruno collection, such as a Postman collection. Import it as that format instead. |

## Related

- [Supported formats](./supported-formats.md): what this importer reads.
- [Import an Insomnia collection](./insomnia-import.md): the same import for Insomnia.
- [Declared, inferred and synthesized](./inference-provenance.mdx): why everything a collection import
  builds is labelled inferred.
- [Import a specification](./import-a-spec.md): the import job, archives and git intake.
