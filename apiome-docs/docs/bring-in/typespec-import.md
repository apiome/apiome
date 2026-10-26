---
title: "Import a TypeSpec API"
description: "Catalog TypeSpec: one .tsp file, or a multi-file project compiled to OpenAPI."
sidebar_position: 42
tags: [import, typespec, tsp, openapi, multi-file]
---

The **TypeSpec** importer (`typespec`) reads a [TypeSpec](https://typespec.io/) API definition
(`.tsp`) into the [Catalog](./catalog.mdx). You can then search, version, diff, lint and convert it
like any other catalog item.

## Import it

Import the definition like any other catalog format: in the [import wizard](./import-wizard.mdx)
(**Import to catalog** → **TypeSpec**), over the REST API (see
[Import a specification](./import-a-spec.md)), or from the CLI with `apiome import typespec <file>`.

| What you have | How it is read |
| --- | --- |
| One `.tsp` file | Read by the built-in TypeSpec reader. |
| Several `.tsp` files (a `.zip`, `.tar.gz` or `.tar`) | Compiled to OpenAPI by the **TypeSpec compiler**, then cataloged from that OpenAPI. |

## Multi-file projects

A TypeSpec API is often split across files. The main file imports its siblings and the TypeSpec
libraries:

```typespec
import "@typespec/http";
import "./models/pets.tsp";
import "./ops/pets-ops.tsp";

@service({ title: "Pet Store" })
namespace PetStore;
```

Upload every `.tsp` file in one archive, in the folders the `import` paths name. The archive's root
document is the compile's entry point. Apiome then:

1. Checks that every file import (`./models/pets.tsp`) names a file in the upload.
2. Compiles the project with `tsp compile`. The `@typespec/http`, `@typespec/rest`,
   `@typespec/openapi3` and `@typespec/versioning` libraries ship with the server.
3. Catalogs the **OpenAPI** the compiler emits. The item's operations, types, diff and lint are the
   ones an OpenAPI import of that document would have, and it stays a TypeSpec item.

Only `.tsp` files are compiled. An uploaded `tspconfig.yaml`, `package.json` or `node_modules` is
ignored: Apiome compiles with its own configuration and the libraries it ships.

The catalog item records how it was built:

| Field | What it holds |
| --- | --- |
| `typespec_compiled_via` | `tsp` |
| `typespec_openapi_format` | The OpenAPI version the compiler emitted, such as `openapi-3.0` |
| `typespec_source_files` | The `.tsp` files of the project |
| `typespec_namespaces` | The namespaces the files declare |
| `typespec_openapi_sha256` | A hash of the emitted OpenAPI: the same project gives the same hash |

**Convert to OpenAPI** on a compiled item uses the OpenAPI the compiler emitted at import.

## When the import refuses a project

| Code | Why | What to do |
| --- | --- | --- |
| `INPUT_SEMANTIC_INVALID` | The project does not compile. The message quotes each compiler error with its file, line and column, such as `models/pets.tsp:9:11 - error invalid-ref: Unknown identifier PetState`. | Fix the reported lines. |
| `INPUT_REFERENCE_UNRESOLVED` | A file `import` names a file that is not in the upload. | Add the file to the archive. |
| `INPUT_REFERENCE_UNRESOLVED` | A file `import` is an absolute path, a URL, or a `../` path that leaves the upload. Such files are never read. | Copy the file into the archive and import it by a relative path. |
| `ADAPTER_UNAVAILABLE` | The upload holds several `.tsp` files and this server has no TypeSpec compiler. | Ask your administrator to deploy the standard image, which ships the compiler. |
| `INPUT_ARCHIVE_INVALID` | The archive's root document is not a `.tsp` file. | Make the main `.tsp` file the archive's root. |

## Related

- [Import a specification](./import-a-spec.md): the import paths every format shares
- [Supported formats](./supported-formats.md): TypeSpec's coverage and export support
- [Convert to OpenAPI](./convert-to-openapi.md): turn a TypeSpec catalog item into an OpenAPI project
