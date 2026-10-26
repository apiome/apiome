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
