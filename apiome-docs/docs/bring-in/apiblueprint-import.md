---
title: "Import an API Blueprint"
description: "Catalog an API Blueprint, checked and hashed by drafter, the reference parser."
sidebar_position: 46
tags: [import, apiblueprint, apib, drafter, refract, api-elements]
---

The **API Blueprint** importer (`apiblueprint`) reads an [API Blueprint](https://apiblueprint.org/)
document (`.apib`, or any file with a `FORMAT: 1A` line) into the [Catalog](./catalog.mdx).
API Blueprint is no longer actively developed; once the API is cataloged you can version, diff and
lint it, and [move it to OpenAPI](#move-to-openapi).

## Import it

Import the blueprint like any other catalog format: in the [import wizard](./import-wizard.mdx)
(**Import to catalog** → **API Blueprint**), over the REST API (see
[Import a specification](./import-a-spec.md)), or from the CLI:

```bash
apiome import apiblueprint ./shelter.apib
```

Apiome's own reader builds the catalog item, so it imports the same way on every server.

## What the catalog item holds

| API Blueprint | Catalog item |
| --- | --- |
| `# Group Pets` | The tag of every action in the group (`apib_group`) |
| A resource and its actions (`## Pets [/pets]`, `### List pets [GET]`) | One operation per action, with the action's own URI when it gives one |
| `+ Parameters`, and a URI template's query (`{?status,limit}`) | Path and query parameters, with each `+ Default:` value |
| `+ Members` under an `enum[…]` parameter or member | The allowed values |
| The first `+ Request` of an action, named or not (`+ Request Minimal (application/json)`) | The request body, its media type and its `+ Headers` |
| Each `+ Response 200 (…)` | A response with that status, its body and its `+ Headers` |
| `+ Attributes (Pet)`, `+ Attributes (array[Pet])` | The body's type |
| An inline `+ Attributes` body (members, no named type) | A type of its own, named after the action: `Get owner 200 Response` (`apib_inline`) |
| `# Data Structures`, `## Pet (object)` | A type with one field per member; a name may contain spaces (`## Owner Summary (object)`) |
| `## Cat (Pet)` | A type with `Pet`'s members, then its own (`apib_base`) |
| `+ Include Problem` | The members of `Problem` added to the type (`apib_includes`) |
| A member typed `object` with deeper members | A nested type, named after its parent: `Pet.address` |
| `required`, `optional`, `nullable` | Whether the field is required, and whether it may be null |

A member named again in a subtype or after an `+ Include` replaces the inherited one. An action's
further requests (`+ Request Invalid`) are other transactions: their responses are kept, but only the
first request is the operation's body.

Exporting the item back to API Blueprint writes `## Cat (Pet)` and `+ Include` lines again, with the
inherited members restated under them. A type whose name has spaces or dots is written with
underscores (`Owner_Summary`), because the export keeps names to letters, digits and `_`.

## What drafter adds

The Apiome server ships **drafter** 4.0.0, the reference API Blueprint parser. Every import also runs
the blueprint through it, once, and keeps two things from its answer, the
[API Elements](https://apielements.org/) (Refract) parse result:

- **Its warnings and errors**, as lint findings of the `apiblueprint` pack (see
  [Lint rules](../build/lint-rules.md#pack-apiblueprint)). Zero warnings is a good blueprint.
- **A hash of the API it describes**, taken over drafter's element tree with everything that is not
  the API's contract removed:

  | Left out | Because |
  | --- | --- |
  | Prose between sections, and every description | Rewording is not a contract change |
  | The headings of groups, resources, actions and transactions | Renaming a heading is not either |
  | Example request and response bodies, and MSON sample values | Examples illustrate the contract |
  | drafter's warnings, and source positions | They describe the text, not the API |

  Body schemas, resources and their URI templates, methods, parameters and their types, status codes,
  headers and data structures stay in, so changing any of them changes the hash.

The catalog item records:

| Key | Holds |
| --- | --- |
| `apib_refract_sha256` | The hash, which is also the item's format hash |
| `apib_refract_algorithm` | `sha256-refract-contract-v1` |
| `apib_drafter_version` | The drafter release that produced the tree: `4.0.0` |

The parse result itself is kept with the item's source. Whether a new catalog version is created is
still decided by the catalog's own fingerprint, so the same blueprint gets the same version on a
server with drafter and on one without.

### Without drafter

drafter is optional. On a server without it, the blueprint still imports, read by Apiome's reader;
the item has no drafter findings and none of the keys above.

## Move to OpenAPI

Convert the item to an OpenAPI project: open it on the **Catalog** and **click “Convert to OpenAPI
Project”**, or run `apiome convert <item-id> --to openapi`. The **API Blueprint** conversion pack
converts each resource and action directly; example transactions are not carried over (see
[Per-format conversion packs](./convert-to-openapi.md#per-format-conversion-packs)).

## Related

- [Lint rules](../build/lint-rules.md#pack-apiblueprint): the `apiblueprint` pack
- [Supported formats](./supported-formats.md): API Blueprint's version coverage and export support
