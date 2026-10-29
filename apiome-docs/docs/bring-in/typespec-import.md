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
[Import a specification](./import-a-spec.md)), or [from the CLI](#from-the-cli).

| What you have | How it is read |
| --- | --- |
| One `.tsp` file | Read by the built-in TypeSpec reader. |
| A TypeSpec project: several `.tsp` files, or a `.tsp` file with its `tspconfig.yaml` (a `.zip`, `.tar.gz` or `.tar`, or a directory from the CLI) | Compiled to OpenAPI by the **TypeSpec compiler**, then cataloged from that OpenAPI. |

The built-in reader reads each model's properties, including their decorators, optional `?` marks
and backticked names, and each enum's members. It reads every interface operation with its verb, its
own `@route`, and its `@path`, `@query`, `@header` and `@cookie` parameters. A parameter is required
unless it is marked `?`. It also reads `/** … */` and `///` doc comments, and the
`@service({ title: "…" })` title. A path parameter that the route does not name is added to the
path, as the compiler does.

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

Only `.tsp` files are compiled, with the libraries the server ships: an uploaded `package.json` or
`node_modules` is ignored. A `tspconfig.yaml` beside the root is read for the settings below.

The catalog item records how it was built:

| Field | What it holds |
| --- | --- |
| `typespec_compiled_via` | `tsp` |
| `typespec_openapi_format` | The OpenAPI version the compiler emitted, such as `openapi-3.0` |
| `typespec_source_files` | The `.tsp` files of the project |
| `typespec_namespaces` | The namespaces the files declare |
| `typespec_openapi_sha256` | A hash of the emitted OpenAPI: the same project gives the same hash |

**Convert to OpenAPI** on a compiled item uses the OpenAPI the compiler emitted at import.

## Compiler and linter warnings

Every compile runs the TypeSpec libraries' built-in linter rules (the `@typespec/http/all`
ruleset). The warnings the compile reports are kept with the catalog item: the compiler's own,
such as `deprecated`, and the linter's, such as `@typespec/http/op-reference-container-route`.

```text
ops/legacy.tsp:15:18 - warning deprecated: Deprecated: Use Pet instead.
main.tsp:22:4 - warning @typespec/http/op-reference-container-route: Operation adoptable references an operation which has a @route prefix …
```

Lint reports each warning under the
[`typespec.compiler-diagnostic`](../build/lint-rules.md#typespec-compiler-diagnostic) rule, at
`tsp:<file>:<line>:<column>` (for example `tsp:main.tsp:22:4`). The message starts with the
diagnostic code, so you can look it up in the [TypeSpec docs](https://typespec.io/docs/). The
catalog item's own OpenAPI lint still applies to the emitted API.

| Field | What it holds |
| --- | --- |
| `typespec_diagnostics` | Up to 50 warnings, each a `severity`, `code`, `message`, and the `file`, `line` and `column` when the compiler gave one |
| `typespec_diagnostic_count` | How many warnings there were in all |

Both fields are present only when the compile reported a warning. A compile **error** refuses the
import (see [below](#when-the-import-refuses-a-project)), and `warn-as-error: true` in your
`tspconfig.yaml` turns these warnings into errors. A single `.tsp` file without a `tspconfig.yaml`
is read without compiling, so it has no compiler warnings.

## Versioned services

A service that uses `@typespec/versioning` describes several versions of one API:

```typespec
@versioned(Versions)
namespace PetStore;

enum Versions {
  v1: "2023-01-01",
  v2: "2023-06-01",
}

model Pet {
  id: string;
  @added(Versions.v2) tag?: string;
}
```

Apiome compiles every version, each to its own OpenAPI document. The catalog item is the
**newest** version: its operations, types, diff and lint are that version's. The item also records:

| Field | What it holds |
| --- | --- |
| `typespec_versions` | Every version, oldest first (the enum's order), with a hash of its OpenAPI |
| `typespec_latest_version` | The version the catalog item describes |
| `typespec_version_changes` | One entry per step from a version to the next: `from`, `to`, an `overall` grade (`breaking`, `safe` or `unknown`), counts per grade, and up to 50 findings such as `property_removed` at `components.schemas.Pet.properties.legacyCode` |

The steps are graded by the same OpenAPI compatibility check Apiome runs when you compare two
OpenAPI revisions. A version is named by its enum member's value (`2023-01-01` above), or by the
member's name when it has no value.

## `tspconfig.yaml`

A `tspconfig.yaml` (or `tspconfig.yml`) in the same folder as the root `.tsp` marks a TypeSpec
project: it compiles even when it holds only one `.tsp` file. Apiome always compiles with the
`@typespec/openapi3` emitter into one OpenAPI document per version (see
[Versioned services](#versioned-services)), and applies these settings from your file:

| Setting | Values | Effect |
| --- | --- | --- |
| `options."@typespec/openapi3".openapi-versions` | `3.0.0`, `3.1.0` | The OpenAPI version emitted. Only the **first** listed version is used. |
| `options."@typespec/openapi3".omit-unreachable-types` | `true`, `false` | Leave out types no operation uses. |
| `options."@typespec/openapi3".include-x-typespec-name` | `inline-only`, `never` | Add `x-typespec-name` to inline types. |
| `options."@typespec/openapi3".safeint-strategy` | `double-int`, `int64` | How `safeint` is written. |
| `warn-as-error` | `true`, `false` | Treat compiler warnings as errors, which refuses the import. |

```yaml
options:
  "@typespec/openapi3":
    openapi-versions:
      - 3.1.0
    omit-unreachable-types: true
```

Every other setting is ignored, and the catalog item lists each one with the reason:

- `emit` and other emitters' options: only `@typespec/openapi3` runs on import.
- `output-dir`, `emitter-output-dir`, `output-file`, `file-type`, `new-line`: Apiome names and reads the
  JSON documents (one per version) in its own working folder.
- `imports`, `linter`, `extends`, `parameters`, `environment-variables`, `trace`: the project's
  `.tsp` files are its imports, Apiome runs the built-in linter rulesets itself (see
  [Compiler and linter warnings](#compiler-and-linter-warnings)), and no interpolation is performed.
- A value of the wrong type, such as `omit-unreachable-types: "yes"`.

| Field | What it holds |
| --- | --- |
| `typespec_tspconfig` | The configuration's path in the upload |
| `typespec_tspconfig_applied` | The settings applied |
| `typespec_tspconfig_ignored` | One line per setting left out, with the reason |

A `tspconfig.yaml` that is not a YAML mapping refuses the import with `INPUT_MALFORMED`.

## From the CLI

Point `apiome import typespec` at a file, an archive or a project directory:

```bash
apiome import typespec ./main.tsp
apiome import typespec ./shop-api.zip --root main.tsp
apiome import typespec ./shop-api/
```

A directory is packed into an archive and sent as one upload. `node_modules`, `tsp-output`,
`dist`, `build` and hidden folders are left out. The root is `--root` when you give it, otherwise
the `tspMain` in the directory's `package.json`, otherwise `main.tsp`.

## When the import refuses a project

| Code | Why | What to do |
| --- | --- | --- |
| `INPUT_SEMANTIC_INVALID` | The project does not compile. The message quotes each compiler error with its file, line and column, such as `models/pets.tsp:9:11 - error invalid-ref: Unknown identifier PetState`. | Fix the reported lines. |
| `INPUT_REFERENCE_UNRESOLVED` | A file `import` names a file that is not in the upload. | Add the file to the archive. |
| `INPUT_REFERENCE_UNRESOLVED` | A file `import` is an absolute path, a URL, or a `../` path that leaves the upload. Such files are never read. | Copy the file into the archive and import it by a relative path. |
| `ADAPTER_UNAVAILABLE` | The upload holds several `.tsp` files and this server has no TypeSpec compiler. | Ask your administrator to deploy the standard image, which ships the compiler. |
| `INPUT_ARCHIVE_INVALID` | The archive's root document is not a `.tsp` file. | Make the main `.tsp` file the archive's root. |
| `INPUT_MALFORMED` | The `tspconfig.yaml` beside the root is not a YAML mapping. | Fix the file, or leave it out. |

## Related

- [Import a specification](./import-a-spec.md): the import paths every format shares
- [Supported formats](./supported-formats.md): TypeSpec's coverage and export support
- [Convert to OpenAPI](./convert-to-openapi.md): turn a TypeSpec catalog item into an OpenAPI project
