---
title: "Import an OpenRPC / JSON-RPC API"
description: "Catalog an OpenRPC document or a live JSON-RPC service via rpc.discover."
sidebar_position: 45
tags: [import, openrpc, json-rpc, rpc, web3, discover, breaking-changes, lint]
---

The **OpenRPC** importer (`openrpc`) reads an [OpenRPC](https://spec.open-rpc.org/) document, the
standard description of a JSON-RPC 2.0 service, into the [Catalog](./catalog.mdx). OpenRPC is the
de-facto API description across web3: Ethereum clients, wallets and many blockchain nodes publish
one. Each method becomes an operation, and the component schemas become types. You can then search,
version, diff, lint and convert it like any other catalog item.

## Import it

| What you have | How to bring it in |
| --- | --- |
| An OpenRPC document (`.json`, `.openrpc.json`) | Upload, paste or link it in the [import wizard](./import-wizard.mdx) (**Import to catalog** → **OpenRPC**), or `apiome import openrpc ./openrpc.json`. |
| A running JSON-RPC service | `apiome import openrpc --discover https://rpc.example.com/` |

Parameters and results written as references to reusable content descriptors
(`{"$ref": "#/components/contentDescriptors/BlockNumber"}`) are resolved, so every method keeps all
of its parameters, in order.

## Discover a live service

A JSON-RPC service that supports OpenRPC service discovery answers the reserved method
**`rpc.discover`** with its own OpenRPC document. Give `--discover` the service's JSON-RPC endpoint:

```bash
apiome import openrpc --discover https://rpc.example.com/
```

The CLI sends one JSON-RPC call to the endpoint:

```json
{"jsonrpc": "2.0", "id": 1, "method": "rpc.discover", "params": []}
```

It reports the endpoint that answered (`Discovered OpenRPC document at …`) and imports the document
it returned. The endpoint's path and query are kept, so a provider URL that carries an API key, such
as `https://mainnet.example.com/v3/<key>`, works as given. The key never becomes the name of the
imported file. `--discover` must be the only input.

| Message | Why | What to do |
| --- | --- | --- |
| `does not implement rpc.discover` | The service answered `Method not found` (`-32601`). | Ask the provider for the OpenRPC document and import the file. |
| `answered rpc.discover with an error` | The service returned another JSON-RPC error, such as a rate limit. | Retry, or check the credentials the endpoint needs. |
| `returned no OpenRPC document` | The reply's `result` is not an OpenRPC document. | Check that the URL is the JSON-RPC endpoint and not a web page. |
| `returned HTTP …` | The endpoint refused the call. | Check the URL and that the endpoint accepts `POST`. |

## Breaking changes between versions

JSON-RPC callers pass parameters **by position** (an array) or **by name** (an object), and a method's
`paramStructure` (`by-position`, `by-name`, or `either`, the default) says which. A new version of an
OpenRPC catalog item is compared parameter by parameter with that in mind:

| Change | Severity | Rule |
| --- | --- | --- |
| A parameter removed | Breaking | `openrpc.param-removed` |
| A required parameter added | Breaking | `openrpc.required-param-added` |
| An optional parameter added after the others | Safe | `openrpc.optional-param-added` |
| A parameter moved to another position | Breaking; safe when the method is `by-name` | `openrpc.param-moved` |
| A parameter renamed, position and schema unchanged | Breaking; safe when the method is `by-position` | `openrpc.param-renamed` |
| An optional parameter made required | Breaking | `openrpc.made-required` |
| A required parameter made optional | Safe | `openrpc.made-optional` |
| A parameter's schema changed | Dangerous | `openrpc.param-schema-changed` |
| `paramStructure` no longer allows a call style it allowed | Breaking | `openrpc.param-structure-narrowed` |
| `paramStructure` changed to `either` | Safe | `openrpc.param-structure-widened` |

Every other change (a removed method, a changed result) is graded by the standard rules.

## Lint rules

On top of the common rules, every OpenRPC catalog item is checked by the `openrpc` pack:

| Rule | Severity | Checks |
| --- | --- | --- |
| [`openrpc.unique-method-names`](../build/lint-rules.md#openrpc-unique-method-names) | Error | No two methods share a name. |
| [`openrpc.unique-param-names`](../build/lint-rules.md#openrpc-unique-param-names) | Error | No two parameters of a method share a name. |
| [`openrpc.required-params-first`](../build/lint-rules.md#openrpc-required-params-first) | Error | Every required parameter comes before the optional ones. |
| [`openrpc.reserved-method-name`](../build/lint-rules.md#openrpc-reserved-method-name) | Warning | No method name begins with `rpc.`, which JSON-RPC reserves (`rpc.discover` is allowed). |
| [`openrpc.method-described`](../build/lint-rules.md#openrpc-method-described) | Info | Every method has a summary or a description. |

## Related

- [Import a specification](./import-a-spec.md): the import paths every format shares
- [Supported formats](./supported-formats.md): OpenRPC's version coverage and export support
- [Built-in lint rules](../build/lint-rules.md): every rule with its rationale
