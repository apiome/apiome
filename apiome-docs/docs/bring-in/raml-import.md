---
title: "Import a RAML API"
description: "Catalog a RAML 1.0 API, with its includes and libraries resolved."
sidebar_position: 39
tags: [import, raml, amf, includes, libraries]
---

The **RAML** importer (`raml`) reads a RAML 1.0 REST API definition into the [Catalog](./catalog.mdx).
Its types become types, and its resources and methods become operations. You can then search,
version, diff and convert it like any other catalog item.

RAML APIs are often split across files. The root document pulls in data types and examples with
`!include`, and shared types with `uses` libraries:

```yaml
#%RAML 1.0
title: Pet Store
uses:
  common: libs/common.raml
types:
  Pet: !include types/pet.raml
/pets/{petId}:
  get:
    responses:
      404:
        body:
          type: common.Error
```

Apiome resolves those references with **AMF**, the AML Modeling Framework maintained for RAML,
which ships with the server.

## Import it

Import the RAML like any other catalog format: in the [import wizard](./import-wizard.mdx)
(**Import to catalog**), or over the REST API (see [Import a specification](./import-a-spec.md)).

- **One self-contained file.** Upload, paste or link the `.raml` file.
- **A file set.** Upload a `.zip`, `.tar.gz` or `.tar` that holds the root document and every
  file it includes or uses, in the same folders the `!include` and `uses` paths name.

## What the import resolves

- **Included types.** A type pulled in with `!include` imports as that type (`Pet` above).
- **Library types.** Each type of a `uses` library imports under its alias: `common.Error`. A
  field or body that names it links to it.
- **Inherited properties.** A type that extends another (`type: Auditable`) imports with the
  properties it inherits.
- **Arrays.** A field typed `Pet[]` or `string[]` keeps its item type.

The catalog item records which files it was built from (`raml_source_files`) and a hash of the
resolved model (`raml_amf_model_sha256`). The hash comes from the resolved model, not the raw
bytes, and does not depend on where the server unpacked the files, so importing the same files
again gives the same hash.

## When the import refuses a set

| Code | Why | What to do |
| --- | --- | --- |
| `INPUT_REFERENCE_UNRESOLVED` | An `!include` or `uses` names a file that is not in the upload, or a type name that is not defined. | Add the missing file to the archive, or fix the type name. |
| `INPUT_REFERENCE_UNRESOLVED` | A reference is an absolute path, a URL, or a `../` path that leaves the uploaded files. Such files are never read. | Copy the file into the archive and reference it with a relative path. |
| `INPUT_SEMANTIC_INVALID` | AMF found the RAML invalid, for example a missing `title`. The message lists each problem with its file and line. | Fix the reported lines. |
| `ADAPTER_UNAVAILABLE` | The document includes or uses other files, and this server has no AMF. | Ask your administrator to deploy the standard image, which ships AMF. |

On a server without AMF, a self-contained RAML document (no `!include`, no `uses`) still imports
with the built-in reader.

## Related

- [Import a specification](./import-a-spec.md): the import paths every format shares
- [Supported formats](./supported-formats.md): RAML's version coverage and export support
