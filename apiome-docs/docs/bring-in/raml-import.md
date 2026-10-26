---
title: "Import a RAML API"
description: "Catalog a RAML 1.0 API with includes, libraries, resource types and traits resolved."
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
- **Resource types and traits.** A resource's `type:` and the `is:` traits on a resource or method
  are applied before the API is cataloged, with their `<<parameters>>` filled in. Each operation
  carries the headers, query parameters, bodies and responses they add, as if the method had
  declared them itself. A value the method declares wins over one it inherits.
- **Headers and every response.** Request headers import as header parameters. A response with no
  body, such as `204`, still imports under its status code.

For example, with a `secured` trait and a `collection` resource type:

```yaml
traits:
  secured:
    headers:
      Authorization: string
    responses:
      401:
        body:
          type: Error
resourceTypes:
  collection:
    get:
      description: List <<resourcePathName>>.
      responses:
        200:
          body:
            type: <<item>>[]
/books:
  type: { collection: { item: Book } }
  is: [secured]
```

`GET /books` imports as **List books.**, with an `Authorization` header and both a `200` response
(`Book[]`) and a `401` response (`Error`).

The catalog item also records where the shape came from:

| Field | Where | What it holds |
| --- | --- | --- |
| `raml_resource_type` | Operation `extras` | The resource type applied to the operation's resource, such as `collection` |
| `raml_traits` | Operation `extras` | The traits applied to the operation, the method's own first, such as `["secured", "paging.pageable"]` |
| `raml_traits` | API `extras` | Every trait the API declares, library ones as `alias.name` |
| `raml_resource_types` | API `extras` | Every resource type the API declares, library ones as `alias.name` |

Resource types and traits from a `uses` library are applied too; they need AMF, like every set that
uses a library.

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
with the built-in reader, which applies the document's own resource types and traits the same way.

## Move to OpenAPI

RAML is no longer actively developed. Once the API is in the catalog, export it as **OpenAPI 3.1**
(see [Export a specification](../ship/export-a-spec.md)). Because resource types and traits are
already applied, every operation in the export lists its own headers, parameters and responses,
each under its status code.

## Related

- [Import a specification](./import-a-spec.md): the import paths every format shares
- [Supported formats](./supported-formats.md): RAML's version coverage and export support
