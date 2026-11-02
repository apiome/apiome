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

Apiome's own reader builds the catalog item: its resource groups, resources, actions, parameters,
requests, responses and data structures.

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
