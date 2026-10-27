---
title: "Import a RAML API"
description: "Catalog a RAML 1.0 API with includes, libraries, resource types and traits resolved."
sidebar_position: 39
tags: [import, raml, amf, includes, libraries, breaking-changes]
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
| `INPUT_SEMANTIC_INVALID` | A set that includes or uses other files does not pass AMF's validation, for example a missing `title`. The message lists each problem with its file and line. A self-contained document imports instead, with each problem as a lint finding (see [Lint and validation](#lint-and-validation)). | Fix the reported lines. |
| `ADAPTER_UNAVAILABLE` | The document includes or uses other files, and this server has no AMF. | Ask your administrator to deploy the standard image, which ships AMF. |

On a server without AMF, a self-contained RAML document (no `!include`, no `uses`) still imports
with the built-in reader, which applies the document's own resource types and traits the same way.

## Lint and validation

RAML items are linted by the `raml` pack, on top of the checks every catalog item gets.

**AMF validation.** On a server with AMF, every import is also run through AMF's validation of the
RAML profile, the rules the RAML specification sets: an example that does not match its type, a
default of the wrong type, a facet that does not fit. Each result is a lint finding at
`raml:<file>:<line>:<column>`, its message starting with AMF's constraint name:

```text
raml.shacl-violation  raml:api.raml:21:1  example-validation-error: /id expected type: Integer, found: String
```

| Rule | Severity |
| --- | --- |
| [`raml.shacl-violation`](../build/lint-rules.md#raml-shacl-violation) | error |
| [`raml.shacl-warning`](../build/lint-rules.md#raml-shacl-warning) | warning |
| [`raml.shacl-info`](../build/lint-rules.md#raml-shacl-info) | info |

AMF builds no model for a document that does not pass, so:

- a **self-contained** document with violations is read by the built-in reader instead, and
  imports with each violation as an error finding;
- a set that **includes or uses other files** still cannot be imported until it passes
  (`INPUT_SEMANTIC_INVALID`, below), because only AMF can resolve it.

**Hygiene.** These checks run with or without AMF. AMF's RAML profile does not report them:

| Rule | Severity | What it catches |
| --- | --- | --- |
| [`raml.undeclared-security-scheme`](../build/lint-rules.md#raml-undeclared-security-scheme) | warning | A `securedBy` (API, resource or method) naming a scheme `securitySchemes` does not declare. |
| [`raml.unused-base-uri-parameter`](../build/lint-rules.md#raml-unused-base-uri-parameter) | warning | A `baseUriParameters` entry that `baseUri` never uses. |
| [`raml.unused-uri-parameter`](../build/lint-rules.md#raml-unused-uri-parameter) | warning | A resource's `uriParameters` entry that its path never uses. |
| [`raml.method-without-responses`](../build/lint-rules.md#raml-method-without-responses) | warning | A method that declares no response. |

The hygiene checks read the root document as written: a scheme or parameter declared in an
`!include`d file, or a library scheme such as `lib.oauth`, is not checked.

Every problem is listed on the catalog item (`raml_lint_issues`, up to 50, with
`raml_lint_issue_count`), each with its rule, path and message.

## Breaking changes between versions

RAML has no official compatibility rules, so Apiome grades the changes between two versions of a
RAML catalog item with its own. Resource types and traits are already applied, so a trait that adds
a parameter is graded as that parameter.

| Change | Severity | Rule |
| --- | --- | --- |
| A required parameter added to a method | Breaking | `raml.parameter-added-required` |
| An optional parameter added | Safe | `raml.parameter-added-optional` |
| A parameter removed | Dangerous | `raml.parameter-removed` |
| A parameter made required / optional | Breaking / Safe | `raml.parameter-made-required` / `raml.parameter-made-optional` |
| A parameter's type changed | Breaking | `raml.parameter-type-changed` |
| A required property added to a type | Breaking | `raml.property-added-required` |
| An optional property (`name?`) added | Safe | `raml.property-added-optional` |
| A property's type changed | Breaking | `raml.property-type-changed` |
| A property made required / optional | Breaking / Dangerous | `raml.property-made-required` / `raml.property-made-optional` |
| An enum value removed / added | Breaking / Dangerous | `raml.enum-value-removed` / `raml.enum-value-added` |
| Only an enum's order changed | Safe | `raml.enum-reordered` |
| Only the applied resource type or traits changed | Safe | `raml.reuse-changed` |

A removed resource, method, response or type is breaking; a new one is safe.

## Move to OpenAPI

RAML is no longer actively developed. Once the API is in the catalog, export it as **OpenAPI 3.1**
(see [Export a specification](../ship/export-a-spec.md)). Because resource types and traits are
already applied, every operation in the export lists its own headers, parameters and responses,
each under its status code.

## Related

- [Import a specification](./import-a-spec.md): the import paths every format shares
- [Supported formats](./supported-formats.md): RAML's version coverage and export support
