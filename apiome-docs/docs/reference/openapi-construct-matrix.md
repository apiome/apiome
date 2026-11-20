---
title: "OpenAPI construct matrix"
description: "Which OpenAPI 3.0, 3.1 and 3.2 constructs survive import and export, measured."
sidebar_position: 5.6
tags: [openapi, import, export, fidelity]
---

This page is Apiome's fidelity statement for OpenAPI. For every OpenAPI construct, in each of
OpenAPI 3.0, 3.1 and 3.2, it says whether the construct survives when you import a document and
export it again. The table is not written by hand: a test builds it by running a corpus of
documents through Apiome and checking each construct.

## What is measured

Each document in the corpus goes through the same steps a catalog import and export take:

1. **Import** the document into Apiome's canonical model.
2. **Export** it as OpenAPI, at the document's own version (a 3.0 document as 3.0, and so on).
3. **Re-import** the exported file and **export** it again.
4. **Compare** every construct of the original document with both exports.

Each occurrence of a construct gets one of three verdicts:

| Verdict | Meaning |
| --- | --- |
| Preserved | The construct is identical in both exports. |
| Reported | The construct changed, and the export's loss report says so. |
| Silent loss | The construct changed and nothing said so. The test fails on any silent loss. |

A cell is **Lossless** when every occurrence was preserved and **Reported** when some changed but
each change is in the loss report. The count in a cell is the number of occurrences, and how many
corpus documents they came from. A dash means the construct does not exist in that version.

The **Loss category** column says which of the seven loss categories a loss of that construct
would fall under: Naming, Type precision, Definitions, Structure, Behaviour, Identity or
Placeholders. To read a real export's report, see
[Understand export fidelity](../ship/export-fidelity.md#openapi).

## The matrix

<!-- openapi-construct-matrix:begin — generated, do not edit by hand. Regenerate with: cd apiome-rest && uv run python scripts/generate_openapi_construct_matrix_doc.py -->

| Construct | Loss category | OpenAPI 3.0 | OpenAPI 3.1 | OpenAPI 3.2 |
| --- | --- | --- | --- | --- |
| `$self` document URI | Identity | — | — | ✅ Lossless (2 in 2 docs) |
| `jsonSchemaDialect` | Type precision | — | ✅ Lossless (2 in 2 docs) | ✅ Lossless (2 in 2 docs) |
| Info contact, licence and terms of service | Definitions | ✅ Lossless (8 in 4 docs) | ✅ Lossless (9 in 5 docs) | ✅ Lossless (9 in 5 docs) |
| `info.summary` | Definitions | — | ✅ Lossless (6 in 6 docs) | ✅ Lossless (6 in 6 docs) |
| SPDX `license.identifier` | Definitions | — | ✅ Lossless (4 in 4 docs) | ✅ Lossless (4 in 4 docs) |
| Servers and server variables (document, path, operation) | Behaviour | ✅ Lossless (6 in 4 docs) | ✅ Lossless (5 in 3 docs) | ✅ Lossless (4 in 3 docs) |
| Server `name` | Naming | — | — | ✅ Lossless (2 in 2 docs) |
| Tag descriptions and documents | Definitions | ✅ Lossless (2 in 2 docs) | ✅ Lossless (3 in 3 docs) | ✅ Lossless (3 in 3 docs) |
| Tag `parent`, `kind` and `summary` | Structure | — | — | ✅ Lossless (23 in 3 docs) |
| `externalDocs` | Definitions | ✅ Lossless (4 in 1 doc) | ✅ Lossless (7 in 5 docs) | ✅ Lossless (7 in 6 docs) |
| `x-` specification extensions | Definitions | ✅ Lossless (9 in 1 doc) | ✅ Lossless (22 in 3 docs) | ✅ Lossless (22 in 3 docs) |
| Security requirements and schemes | Behaviour | ✅ Lossless (2 in 1 doc) | ✅ Lossless (8 in 6 docs) | ✅ Lossless (4 in 4 docs) |
| Reusable components other than schemas | Structure | ✅ Lossless (9 in 2 docs) | ✅ Lossless (34 in 17 docs) | ✅ Lossless (34 in 17 docs) |
| Path item summary, description, servers and shared parameters | Structure | ✅ Lossless (3 in 1 doc) | ✅ Lossless (10 in 8 docs) | ✅ Lossless (11 in 7 docs) |
| Path item `$ref` | Structure | ✅ Lossless (1 in 1 doc) | ✅ Lossless (2 in 2 docs) | ✅ Lossless (2 in 2 docs) |
| Operation id, summary, description, tags and `deprecated` | Definitions | ✅ Lossless (47 in 7 docs) | ✅ Lossless (33 in 7 docs) | ✅ Lossless (38 in 8 docs) |
| `QUERY` method | Behaviour | — | — | ✅ Lossless (3 in 3 docs) |
| `additionalOperations` (custom methods) | Behaviour | — | — | ✅ Lossless (2 in 2 docs) |
| Callbacks | Behaviour | ✅ Lossless (2 in 2 docs) | ✅ Lossless (3 in 3 docs) | ✅ Lossless (2 in 2 docs) |
| Webhooks | Behaviour | — | ✅ Lossless (6 in 6 docs) | ✅ Lossless (4 in 4 docs) |
| Response links | Behaviour | ✅ Lossless (5 in 2 docs) | ✅ Lossless (3 in 3 docs) | ✅ Lossless (2 in 2 docs) |
| Parameter `style`, `explode`, `allowReserved`, `allowEmptyValue`, `content` | Structure | ✅ Lossless (7 in 2 docs) | ✅ Lossless (26 in 6 docs) | ✅ Lossless (30 in 8 docs) |
| `in: querystring` parameter | Behaviour | — | — | ✅ Lossless (2 in 2 docs) |
| Request body `required` | Behaviour | ✅ Lossless (4 in 3 docs) | ✅ Lossless (3 in 3 docs) | ✅ Lossless (3 in 3 docs) |
| Examples on parameters, media types and headers | Definitions | ✅ Lossless (11 in 3 docs) | ✅ Lossless (16 in 6 docs) | ✅ Lossless (14 in 6 docs) |
| Several media types on one body or response | Structure | ✅ Lossless (2 in 1 doc) | ✅ Lossless (7 in 5 docs) | ✅ Lossless (8 in 5 docs) |
| Streaming media types (SSE, JSON Lines, JSON Text Sequences, multipart/mixed) | Behaviour | ✅ Lossless (2 in 1 doc) | ✅ Lossless (4 in 1 doc) | ✅ Lossless (5 in 2 docs) |
| `itemSchema` for sequential media | Behaviour | — | — | ✅ Lossless (5 in 2 docs) |
| Media type `encoding` | Structure | ✅ Lossless (1 in 1 doc) | ✅ Lossless (5 in 4 docs) | ✅ Lossless (6 in 4 docs) |
| `prefixEncoding` and `itemEncoding` | Structure | — | — | ✅ Lossless (4 in 2 docs) |
| Response headers | Behaviour | ✅ Lossless (2 in 2 docs) | ✅ Lossless (3 in 3 docs) | ✅ Lossless (1 in 1 doc) |
| Response `summary` | Definitions | — | — | ✅ Lossless (3 in 2 docs) |
| `summary` / `description` beside `$ref` | Definitions | — | ✅ Lossless (5 in 3 docs) | ✅ Lossless (3 in 2 docs) |
| `discriminator` | Structure | ✅ Lossless (1 in 1 doc) | ✅ Lossless (2 in 2 docs) | ✅ Lossless (2 in 2 docs) |
| `allOf`, `oneOf`, `anyOf`, `not` | Structure | ✅ Lossless (7 in 2 docs) | ✅ Lossless (6 in 3 docs) | ✅ Lossless (5 in 3 docs) |
| Nullability | Type precision | ✅ Lossless (3 in 1 doc) | ✅ Lossless (9 in 3 docs) | ✅ Lossless (7 in 3 docs) |
| `$dynamicRef` / `$dynamicAnchor` | Structure | — | ✅ Lossless (2 in 1 doc) | ✅ Lossless (2 in 1 doc) |
| JSON Schema 2020-12 keywords (`const`, `prefixItems`, `if`/`then`/`else`, …) | Type precision | — | ✅ Lossless (34 in 5 docs) | ✅ Lossless (10 in 5 docs) |
| Numeric, string, array and object constraints | Type precision | ✅ Lossless (20 in 3 docs) | ✅ Lossless (22 in 6 docs) | ✅ Lossless (14 in 6 docs) |
| Schema `format` | Type precision | ✅ Lossless (17 in 5 docs) | ✅ Lossless (16 in 8 docs) | ✅ Lossless (17 in 7 docs) |
| Schema `readOnly`, `writeOnly`, `xml`, `example`, `default`, `deprecated`, `title` | Definitions | ✅ Lossless (14 in 3 docs) | ✅ Lossless (8 in 4 docs) | ✅ Lossless (24 in 4 docs) |

Corpus documents — OpenAPI 3.0: 7, OpenAPI 3.1: 39, OpenAPI 3.2: 40.

<!-- openapi-construct-matrix:end -->

## Exporting to another version

The matrix covers exports at a document's own version. When you export to a different version,
Apiome converts what the target can hold and reports what it cannot:

- **3.0 to 3.1 or 3.2:** schemas are rewritten into JSON Schema 2020-12. `nullable: true` becomes
  a `"null"` type, and a boolean `exclusiveMinimum` or `exclusiveMaximum` takes the bound's number.
  Nothing is lost.
- **3.1 or 3.2 to 3.0:** 3.1 schema keywords are rewritten into their 3.0 forms where one exists
  (`const` becomes a one-value `enum`, a `"null"` type becomes `nullable`). Constructs 3.0 has no
  place for, such as `webhooks`, `jsonSchemaDialect`, `$dynamicRef` and keywords beside a `$ref`,
  are left out, and each one is listed in the loss report.
- **3.2 to 3.1 or 3.0:** 3.2-only constructs, such as `$self`, `itemSchema`, `in: querystring`
  parameters, tag `parent` and `kind`, and response `summary`, are left out and listed in the loss
  report. A `QUERY` operation and custom methods are kept on `x-apiome-query-operation` and
  `x-apiome-additional-operations` extensions.
- **Any version to Swagger 2.0:** the file is built from the canonical model only. The loss report
  says that OpenAPI 3.x constructs such as callbacks, links, webhooks and examples are not written.

## Edited operations and schemas

Apiome keeps a copy of each imported operation and schema, and exports that copy as long as the
operation or schema has not changed since import. If it has changed, the export is built from the
current version instead. Every source field Apiome has no other place for (callbacks, extensions,
`discriminator`, `externalDocs` and so on) is still written. The loss report gets one entry for
the changed operation or schema, because detail inside the edited fields, such as schema keywords
or examples, may be missing.

## The corpus

The corpus is in `apiome-rest/tests/fixtures/openapi_construct_corpus`:

- the OpenAPI Initiative's schema test documents for 3.1 and 3.2, from the
  [OpenAPI Specification repository](https://github.com/OAI/OpenAPI-Specification);
- the OpenAPI Initiative's example documents for 3.0, 3.1 and 3.2, from
  [learn.openapis.org](https://learn.openapis.org);
- one Apiome document per version that holds every construct in the matrix.

To add a construct, add it to the catalogue in `apiome-rest/src/app/openapi_construct_audit.py`
and to a corpus document, then regenerate this page:

```bash
cd apiome-rest && uv run python scripts/generate_openapi_construct_matrix_doc.py
```

A cell no corpus document covers shows as **Not covered**, which also fails the test.
