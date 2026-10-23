---
title: "Export to an API client"
description: "Export an API as a Hoppscotch or Thunder Client collection with its environment."
sidebar_position: 2.6
tags: [export, hoppscotch, thunder-client, collection, requests, environment]
---

Any HTTP API in Apiome can be exported as a collection your team opens in its API client: one saved
request per operation, in folders, ready to run. Leaving a client doesn't mean losing your work. A
collection imported from [Hoppscotch](../bring-in/hoppscotch-import.md) or
[Thunder Client](../bring-in/thunder-client-import.md) can be exported back to the same client or
to the other one, and an OpenAPI, Postman or `.http` source can be exported to either.

## The client targets

| Target | What you get | Re-imports as |
| --- | --- | --- |
| **Hoppscotch** | `<name>.hoppscotch_collection.json` (collection schema `v` 6) and `<name>.hoppscotch_environment.json` | `hoppscotch` |
| **Thunder Client** | `thunder-collection_<name>.json` (export `version` 1.2) and `thunder-environment_<name>.json` | `thunder-client` |

Both targets write two files: the **collection** and the **environment** its variables come from.
Import both into the client. In Hoppscotch, import the collection under **Collections** and the
environment under **Environments**. In Thunder Client, use **Import** on the **Collections** tab
and again on the **Env** tab.

## Export it

1. On the project's **Versions** page, **open a version's Actions menu** and **choose “Export to
   another format…”**.
2. Pick the **Hoppscotch** or **Thunder Client** card.
3. Read its fidelity: a client collection is **lossy**, because it saves calls, not a contract (see
   [What a collection cannot carry](#what-a-collection-cannot-carry)).
4. **Click “Export”** (or **“Export anyway”** when the fidelity check warns) and download the
   bundle.

From the CLI, write both files into a folder. A lossy export exits `1` unless you pass `--force`:

```bash
apiome export hoppscotch petstore-sample --version 1.0.0 --out ./petstore-hoppscotch/ --force
apiome export thunder-client petstore-sample --version 1.0.0 --out ./petstore-thunder/ --force
```

With the API, use the target key (`hoppscotch` or `thunder-client`) with
`POST /v1/export/{tenant}/preview` and the export job endpoints. See
[Export a specification](./export-a-spec.md).

## What you get

| In the API | In the collection |
| --- | --- |
| Each HTTP operation | One saved request, named after the request it was imported from or else the operation |
| The operation's first tag (`Catalogue / Widgets`) | Its folder, nested at each ` / ` |
| The first server | A `baseUrl` variable in the environment. Every request starts `<<baseUrl>>` (Hoppscotch) or `{{baseUrl}}` (Thunder Client) |
| A request saved with a full URL (from a client or capture import) | The same URL, so the server comes back unchanged |
| Path parameters | `<<id>>` in the endpoint with a request variable (Hoppscotch); `:id` with a path parameter (Thunder Client) |
| Required query parameters and headers | Enabled, holding the parameter's default or the value seen at import |
| Optional query parameters and headers | Saved, but **disabled** |
| A request body | An example built from the request schema: JSON text, or form fields for a URL-encoded or multipart body |
| A body that accepts two media types | One saved request per media type |
| The same auth on every operation | Set once on the collection; each request inherits it |

The export checks its own output before you download it: both files are read back by Apiome's own
Hoppscotch or Thunder Client importer, and an export that would not import is rejected.

## Credentials are placeholders

**No credential value is ever exported.** Auth is written as a variable reference, and the
environment declares every one of those variables **empty**. Hoppscotch environments also mark them
**secret**. Fill them in in your client before you send a request.

| Auth | Hoppscotch | Thunder Client |
| --- | --- | --- |
| Bearer token, OpenID Connect | Bearer, token `<<accessToken>>` | Bearer, token `{{accessToken}}` |
| Basic, Digest | Basic / Digest, `<<username>>` and `<<password>>` | Basic / Digest, `{{username}}` and `{{password}}` |
| API key | API Key, value `<<apiKey>>`, in the header or query parameter the API names | A header or query parameter holding `{{apiKey}}` (Thunder Client has no API-key auth type) |
| OAuth 2 | OAuth 2.0, client ID `<<clientId>>` and secret `<<clientSecret>>`, with the token URL and scopes | OAuth 2, client ID `{{clientId}}` and secret `{{clientSecret}}`, with the token URL and scopes |
| Any other `Authorization` or `Cookie` requirement | A header holding `<<authorization>>` or `<<cookie>>` | A header holding `{{authorization}}` or `{{cookie}}` |

The same rule covers everything else:

- A header, query parameter, form field or JSON body field whose name says it holds a secret
  (`password`, `api_key`, `client_secret`, `X-Auth-Token` …) becomes a reference to a variable of
  that name, whatever default or example the API holds for it.
- Every other value written (defaults, example values, the base URL) first goes through the same
  secret scrubber imports use.
- A user name and password in a server URL (`https://user:pass@…`) are removed.

## What a collection cannot carry

A collection describes calls, so the fidelity report lists what it leaves behind:

- **Types.** Only the shape of each example body survives. A re-import infers body types again,
  under names of its own.
- **Responses.** A saved request records the call, not the reply.
- **Events, channels and non-HTTP operations** have no saved request and are dropped.
- **Extra tags, servers and auth schemes.** A request sits in one folder and has one auth; the
  collection has one base URL. Each one left out is listed in the export's losses.
- **Cookie parameters, and bodies with no example** (an XML or binary body) are not carried.
- **API keys in Thunder Client** come back as a parameter rather than a declared auth scheme.

A collection exported from the same client re-imports to the same operations, parameters,
folders, auth schemes, body media types, title and servers.

## Related

- [Understand export fidelity](./export-fidelity.md): how the fidelity report is worked out.
- [Import a Hoppscotch collection](../bring-in/hoppscotch-import.md) and
  [Import a Thunder Client collection](../bring-in/thunder-client-import.md): the importers these
  targets round-trip through.
- [Export to an API gateway](./export-to-a-gateway.md): the gateway targets.
- [Supported formats](../bring-in/supported-formats.md): every format Apiome reads and writes.
