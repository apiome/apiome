---
title: "Import a Smithy model"
description: "Catalog a Smithy model: one file, a JSON AST, or a multi-file set."
sidebar_position: 41
tags: [import, smithy, json-ast, multi-file, rpc]
---

The **Smithy** importer (`smithy`) reads a [Smithy](https://smithy.io/2.0/) model into the
[Catalog](./catalog.mdx). Structures, unions, enums, lists and maps become types, and each service's
operations become operations. You can then search, version, diff and convert it like any other
catalog item.

## Import it

Import the model like any other catalog format: in the [import wizard](./import-wizard.mdx)
(**Import to catalog** → **Smithy**), over the REST API (see
[Import a specification](./import-a-spec.md)), or [from the CLI](#from-the-cli).

You can bring the model in three ways:

| What you have | How it is read |
| --- | --- |
| One `.smithy` file | Read by the built-in Smithy reader. |
| One JSON AST file (`.json`) | Read as is. A JSON AST already holds every shape by its absolute id. |
| Several model files (a `.zip`, `.tar.gz` or `.tar`) | Assembled by the **Smithy CLI** into one JSON AST, then read. |

## Multi-file models

A Smithy model is often split across files. A namespace can span several files, and shapes target
shapes in other namespaces:

```smithy
$version: "2"
namespace example.weather

use example.common#Money

structure GetForecastOutput {
    priceOfUmbrella: Money
}
```

Upload every model file in one archive. Apiome runs `smithy ast` on them, which validates the
combined model and assembles it into one JSON AST:

- **Every file counts.** `.smithy` files and JSON AST `.json` files are assembled together. Other
  files are ignored. A `smithy-build.json` is never read, so an upload cannot make the server fetch
  dependencies.
- **Namespaces stay apart.** Shapes in the model's main namespace (the namespace of its first
  service) keep their plain names. A shape from another namespace keeps its absolute id, such as
  `example.common#Money`, and its catalog type is keyed under that namespace.
- **Resources bring their operations.** A service's operations include the ones bound to its
  resources (`read`, `create`, `list`, `operations` and so on).
- **Simple shapes resolve.** A member that targets `CityId` (a `string` shape) is typed `String`.
- **Unknown traits are kept.** Traits from packages the server does not bundle, such as
  `aws.protocols#restJson1`, do not fail the import.

The catalog item records the model's identity:

| Field | What it holds |
| --- | --- |
| `smithy_version` | The model's `$version`, such as `2.0` |
| `smithy_namespaces` | Every namespace the model defines shapes in |
| `smithy_ast_sha256` | A hash of the assembled JSON AST: the same model gives the same hash, however its files are split or ordered |
| `smithy_source_files` | The model files it was assembled from |

A set that holds a single model file is read like that one file.

## Lint: Smithy validation and smithy-linters

On a server with the Smithy CLI, every Smithy import (one `.smithy` file, a JSON AST or a
multi-file model) is also run through `smithy validate`, with these validators from Smithy's
`smithy-linters` package switched on:

| Validator | What it catches |
| --- | --- |
| `CamelCase` | Member names that are not lower camel case (`pet_id`), shape names that are not upper camel case. |
| `MissingPaginatedTrait` | A `List…` / `Search…` operation that returns a list but is not `@paginated`. |
| `AbbreviationName` | Names with all-caps abbreviations (`URLValue` should be `UrlValue`). |
| `ShouldHaveUsedTimestamp` | A member named like a time (`adoptedAt`) whose type is not a `timestamp`. |
| `MissingSensitiveTrait` | A member that looks like sensitive data (`password`) without `@sensitive`. |
| `InputOutputStructureReuse` | An operation input or output structure that is shared or not marked `@input` / `@output`. |
| `NoninclusiveTerms` | Non-inclusive words in shape or member names and documentation. |
| `RepeatedShapeName` | A member name that repeats its structure's name (`Pet$petName`). |
| `StutteredShapeName` | A shape name that repeats its namespace. |

`ReservedWords` and `StandardOperationVerb` need lists only you can provide, so they are not switched
on. A model can still configure them, or any other validator, with its own `metadata validators`.

Each event is a lint finding at `smithy:<file>:<line>:<column>`, its message starting with the
validator name:

```text
smithy.linter  smithy:model.smithy:13:1  MissingPaginatedTrait: The verb of this operation, `list`, requires that the operation is marked with the `paginated` trait. …
```

| Rule | Severity | Reports |
| --- | --- | --- |
| [`smithy.linter`](../build/lint-rules.md#smithy-linter) | warning | The `smithy-linters` validators above. |
| [`smithy.validation-error`](../build/lint-rules.md#smithy-validation-error) | error | An `ERROR` event, such as a member targeting a shape that does not exist. A single `.smithy` file the built-in reader imported can have one; a multi-file model with errors is refused at import. |
| [`smithy.validation-warning`](../build/lint-rules.md#smithy-validation-warning) | warning | `DANGER` and `WARNING` events from Smithy's built-in validators or your own `metadata validators`. |
| [`smithy.validation-note`](../build/lint-rules.md#smithy-validation-note) | info | `NOTE` events. |

Suppressions in the model (`@suppress`, `metadata suppressions`) are honored. The events are listed
on the catalog item (`smithy_validation_events`, up to 50, with `smithy_validation_event_count`).
Without the Smithy CLI the model imports the same way, with no Smithy lint findings. The linters
ship with the server, so validation never fetches anything from the network.

## From the CLI

Point `apiome import smithy` at a model file, a JSON AST, an archive or a model directory:

```bash
apiome import smithy ./weather.smithy
apiome import smithy ./weather-ast.json
apiome import smithy ./weather-model.zip
apiome import smithy ./weather-model/
```

A directory is packed into an archive and sent as one upload. `build`, `dist` and hidden folders are
left out. Apiome then assembles the model files the same way as an uploaded archive. Pass `--root`
to choose the file kept as the item's source text; otherwise the server picks one.

## When the import refuses a model

| Code | Why | What to do |
| --- | --- | --- |
| `INPUT_SEMANTIC_INVALID` | The Smithy CLI found the model invalid, for example a target that no file defines. The message quotes the CLI's errors with their file and line. | Fix the reported shapes, or add the missing file to the archive. |
| `INPUT_REFERENCE_UNRESOLVED` | A JSON AST targets a shape it does not define. | Upload the files that define it together, as a set. |
| `ADAPTER_UNAVAILABLE` | The upload holds several model files and this server has no Smithy CLI. | Ask your administrator to deploy the standard image, which ships the Smithy CLI. |
| `INPUT_ARCHIVE_INVALID` | The archive holds no `.smithy` or JSON AST file. | Add the model files to the archive. |

## Related

- [Import a specification](./import-a-spec.md): the import paths every format shares
- [Supported formats](./supported-formats.md): Smithy's coverage and export support
- [Convert to OpenAPI](./convert-to-openapi.md): turn a Smithy catalog item into an OpenAPI project
