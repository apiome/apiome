---
title: "Export to an API client"
description: "Export an API as a Postman, Insomnia, Bruno, Hoppscotch or Thunder Client collection."
sidebar_position: 2.6
tags: [export, postman, insomnia, bruno, hoppscotch, thunder-client, collection, requests, environment]
---

Any HTTP API in Apiome can be exported as a collection your team opens in its API client: one saved
request per operation, in folders, ready to run. Leaving a client doesn't mean losing your work. A
collection imported from [Postman](../bring-in/postman-import.md),
[Insomnia](../bring-in/insomnia-import.md), [Bruno](../bring-in/bruno-import.md),
[Hoppscotch](../bring-in/hoppscotch-import.md) or [Thunder Client](../bring-in/thunder-client-import.md)
can be exported back to the same client or to another one, and an OpenAPI or `.http` source can be
exported to any of them.

## The client targets

| Target | What you get | Re-imports as |
| --- | --- | --- |
| **Postman** | `<name>.postman_collection.json`, a Postman Collection v2.1 with its variables inside | `postman` |
| **Insomnia** | `<name>.insomnia.json`, an Insomnia v4 export: a workspace, its folders and requests, and a base environment | `insomnia` |
| **Bruno** | A `.zip` of a Bruno collection folder: `bruno.json`, one `.bru` file per request in a folder per tag, and `environments/Default.bru` | `bruno` |
| **Hoppscotch** | `<name>.hoppscotch_collection.json` (collection schema `v` 6) and `<name>.hoppscotch_environment.json` | `hoppscotch` |
| **Thunder Client** | `thunder-collection_<name>.json` (export `version` 1.2) and `thunder-environment_<name>.json` | `thunder-client` |

Postman writes one file: in Postman, **click Import** and choose it. Its variables (the base URL and
every credential) are collection variables, so there is no environment to import.

Insomnia writes one file with its environment inside. In Insomnia, **choose Import** from the
project's menu and pick the file; Insomnia reads the v4 export into its current format. Select the
**Base Environment** to fill in the credentials.

Bruno writes a collection folder, delivered as a `.zip`. **Unzip it**, then in Bruno **choose “Open
Collection”** and pick the folder that holds `bruno.json`. Select the **Default** environment; its
credentials are secret variables, so enter their values in Bruno — they are never written to the
files.

Hoppscotch and Thunder Client write two files: the **collection** and the **environment** its
variables come from. Import both into the client. In Hoppscotch, import the collection under **Collections** and the
environment under **Environments**. In Thunder Client, use **Import** on the **Collections** tab
and again on the **Env** tab.

## Export it

1. On the project's **Versions** page, **open a version's Actions menu** and **choose “Export to
   another format…”**.
2. Pick the **Postman**, **Insomnia**, **Bruno**, **Hoppscotch** or **Thunder Client** card.
3. Read its fidelity: a client collection is **lossy**, because it saves calls, not a contract (see
   [What a collection cannot carry](#what-a-collection-cannot-carry)).
4. **Click “Export”** (or **“Export anyway”** when the fidelity check warns) and download the
   bundle.

From the CLI, write the files into a folder. A lossy export exits `1` unless you pass `--force`:

```bash
apiome export postman petstore-sample --version 1.0.0 --out ./petstore-postman/ --force
apiome export insomnia petstore-sample --version 1.0.0 --out ./petstore-insomnia/ --force
apiome export bruno petstore-sample --version 1.0.0 --out ./petstore-bruno/ --force
apiome export hoppscotch petstore-sample --version 1.0.0 --out ./petstore-hoppscotch/ --force
apiome export thunder-client petstore-sample --version 1.0.0 --out ./petstore-thunder/ --force
```

With the API, use the target key (`postman`, `insomnia`, `bruno`, `hoppscotch` or `thunder-client`) with
`POST /v1/export/{tenant}/preview` and the export job endpoints. See
[Export a specification](./export-a-spec.md).

## Postman options

Set these in the export's **Options**, with `--option key=value` on the CLI, or in `options` over the
API:

| Option | Values | What it does |
| --- | --- | --- |
| `folder_strategy` | `auto` (default), `tag`, `service`, `flat` | `auto` files each request under the operation's first tag, else under its service when the API has more than one. `tag` and `service` use only one of those; `flat` puts every request at the top. A collection imported from Postman keeps its own folders under `auto` and `service`. |
| `variable_style` | `variables` (default), `inline` | `variables` makes every server a collection variable (`{{baseUrl}}`, then `{{baseUrl2}}` …) and declares a server's own variables, such as `{{region}}` in `https://{{region}}.example.com`. `inline` writes the server's address into every request and declares only the credential variables. |
| `example_depth` | `minimal` (default), `full` | Example bodies and responses fill the required fields only, or every field the schema declares. |
| `flavor` | `postman` (default), `insomnia`, `bruno` | The collection format written. `insomnia` and `bruno` write exactly what the **Insomnia** and **Bruno** targets write, with this export's `folder_strategy` and `example_depth`. |

```bash
apiome export postman petstore-sample --version 1.0.0 --out ./petstore-postman/ \
  --option folder_strategy=tag --option example_depth=full --force
```

## Insomnia and Bruno options

| Option | Values | What it does |
| --- | --- | --- |
| `folder_strategy` | `tag` (default), `auto`, `service`, `flat` | As for Postman. A collection imported from the same client keeps its own folders under `tag`. |
| `example_depth` | `minimal` (default), `full` | Example bodies fill the required fields only, or every field the schema declares. |
| `indent` | a number (Insomnia only; default `2`) | JSON indentation; `0` writes one line. |

Each Insomnia and Bruno export is checked before you download it: Apiome's own Insomnia or Bruno
importer reads it back, as an uploaded export would be read, and an export that does not import fails
with `insomnia.reimport` or `bruno.reimport`.

## What Postman carries beyond the other clients

- **Saved example responses.** Each response with one status code (`200`, `404` …) is saved on its
  request as an example, with a body built from the response schema. A status range such as `4XX`
  has no code to save under and is listed in the losses.
- **The API's description and version**, in the collection's info.
- **Every server**, as a collection variable.

Each Postman export is checked before you download it:

1. It is validated against the published
   [Postman Collection v2.1.0 schema](https://schema.postman.com/collection/json/v2.1.0/draft-07/collection.json).
   Each violation is listed on its own, with the JSON path where it is (`/item/0/request/method`).
2. It is imported again by Apiome's Postman importer, as an uploaded collection would be.

If either check fails, the export fails and names the file, the path and the rule (`postman.schema`,
`postman.reimport`). A collection imported from Postman is written back as it was read — its folders,
headers, bodies, saved responses, variables and auth — and re-imports unchanged. A Collection v2.0 one
is written as v2.1.

## What you get

| In the API | In the collection |
| --- | --- |
| Each HTTP operation | One saved request, named after the request it was imported from or else the operation |
| The operation's first tag (`Catalogue / Widgets`) | Its folder, nested at each ` / ` |
| The first server | A `baseUrl` variable in the environment (in the collection for Postman). Every request starts `<<baseUrl>>` (Hoppscotch), `{{ _.baseUrl }}` (Insomnia) or `{{baseUrl}}` (Postman, Bruno, Thunder Client) |
| A request saved with a full URL (from a client or capture import) | The same URL, so the server comes back unchanged |
| Path parameters | `<<id>>` in the endpoint with a request variable (Hoppscotch); `:id` with a path parameter (Postman, Insomnia, Bruno, Thunder Client) |
| Required query parameters and headers | Enabled, holding the parameter's default or the value seen at import |
| Optional query parameters and headers | Saved, but **disabled** |
| A request body | An example built from the request schema: JSON text, or form fields for a URL-encoded or multipart body |
| A body that accepts two media types | One saved request per media type |
| The same auth on every operation | Set once on the collection; each request inherits it (Insomnia has no collection auth, so each request carries it) |

The export checks its own output before you download it: the files are read back by Apiome's own
Postman, Insomnia, Bruno, Hoppscotch or Thunder Client importer, and an export that would not
import is rejected.

## Credentials are placeholders

**No credential value is ever exported.** Auth is written as a variable reference, and the
environment (the collection, for Postman) declares every one of those variables **empty**.
Hoppscotch environments also mark them **secret**, and a Bruno environment lists them under
`vars:secret` with no value at all. Fill them in in your client before you send a request.

| Auth | Postman | Hoppscotch | Thunder Client |
| --- | --- | --- | --- |
| Bearer token, OpenID Connect | Bearer Token, token `{{accessToken}}` | Bearer, token `<<accessToken>>` | Bearer, token `{{accessToken}}` |
| Basic, Digest | Basic / Digest Auth, `{{username}}` and `{{password}}` | Basic / Digest, `<<username>>` and `<<password>>` | Basic / Digest, `{{username}}` and `{{password}}` |
| API key | API Key, value `{{apiKey}}`, in the header or query parameter the API names | API Key, value `<<apiKey>>`, in the header or query parameter the API names | A header or query parameter holding `{{apiKey}}` (Thunder Client has no API-key auth type) |
| OAuth 2 | OAuth 2.0, client ID `{{clientId}}` and secret `{{clientSecret}}`, with the token URL and scopes | OAuth 2.0, client ID `<<clientId>>` and secret `<<clientSecret>>`, with the token URL and scopes | OAuth 2, client ID `{{clientId}}` and secret `{{clientSecret}}`, with the token URL and scopes |
| Any other `Authorization` or `Cookie` requirement | A header holding `{{authorization}}` or `{{cookie}}` | A header holding `<<authorization>>` or `<<cookie>>` | A header holding `{{authorization}}` or `{{cookie}}` |

Insomnia and Bruno write the same auth types as Postman — bearer token, basic, digest, API key (in
the header or query parameter the API names) and OAuth 2 — each credential a variable reference:
`{{ _.accessToken }}` in Insomnia, `{{accessToken}}` in Bruno.

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
- **Responses.** An Insomnia, Bruno, Hoppscotch or Thunder Client request records the call, not the
  reply. Postman keeps each one as a saved example, but a re-import infers the response schema again
  from it.
- **Events, channels and non-HTTP operations** have no saved request and are dropped.
- **Extra tags, servers and auth schemes.** A request sits in one folder and has one auth; the
  collection has one base URL (Postman keeps every server, except with `variable_style=inline`).
  Each one left out is listed in the export's losses.
- **Cookie parameters, and bodies with no example** (an XML or binary body) are not carried.
- **API keys in Thunder Client** come back as a parameter rather than a declared auth scheme.
- **A method Bruno has no request for** (such as `QUERY`) is not saved in a Bruno collection.

A collection exported from the same client re-imports to the same operations, parameters,
folders, auth schemes, body media types, title and servers. An Insomnia or Bruno one is written anew
from those, so what Apiome does not model is not written back: an Insomnia v5 export comes back as
v4, and environments other than the base one, request-level variables, scripts and tests are left
out. The report says so.

### How a Postman export's fidelity report reads

A Postman collection trades schemas for examples. The report names each trade as its own item on the
operation it affects, with the reason:

| What the source has | What the report says | Kind |
| --- | --- | --- |
| A request body schema | It becomes one example body; its types and constraints are not enforced | approximated |
| Response schemas (`200`, `404` …) | They become saved example responses; a re-import infers the schemas again | approximated |
| A status range (`4XX`, `default`) | It has no status code to save under and is not saved | dropped |
| A union or `oneOf` in a body | The example shows one of its alternatives | approximated |
| Any example body or response | Its values are generated from the schema, not taken from the source | synthesized |
| A streaming operation | It is saved as one request and one response | dropped |
| OpenID Connect | It is written as a bearer token | approximated |
| A generic `Authorization` or `Cookie` requirement | It is sent as a header holding a variable reference | approximated |
| Any other auth scheme (mutual TLS …) | Postman has no form for it | dropped |
| Several auth schemes on one operation | Only the first is written | approximated |
| Constraints on a field | The example satisfies them, but the collection does not enforce them | approximated |
| Events, channels and gRPC or GraphQL operations | They have no saved request | dropped |

Whenever an item is dropped, approximated or synthesized, the export shows its fidelity warning
before you download. A collection imported from Postman is written back as it was read, so its
report is empty.

## Related

- [Understand export fidelity](./export-fidelity.md): how the fidelity report is worked out.
- [Import an Insomnia collection](../bring-in/insomnia-import.md),
  [Import a Bruno collection](../bring-in/bruno-import.md),
  [Import a Hoppscotch collection](../bring-in/hoppscotch-import.md) and
  [Import a Thunder Client collection](../bring-in/thunder-client-import.md): the importers these
  targets round-trip through.
- [Export to an API gateway](./export-to-a-gateway.md): the gateway targets.
- [Supported formats](../bring-in/supported-formats.md): every format Apiome reads and writes.
