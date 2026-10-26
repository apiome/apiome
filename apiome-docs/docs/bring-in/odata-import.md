---
title: "Import an OData service"
description: "Catalog OData metadata as CSDL XML or CSDL JSON, checked against the OASIS schema."
sidebar_position: 43
tags: [import, odata, csdl, edmx, validation]
---

The **OData** importer (`odata`) reads an OData service's metadata into the
[Catalog](./catalog.mdx). Entity types and complex types become types, enums become enums, and each
entity set becomes a set of operations. You can then search, version, diff, lint and convert it like
any other catalog item.

## Import it

Import the metadata like any other catalog format: in the [import wizard](./import-wizard.mdx)
(**Import to catalog** → **OData**), over the REST API (see
[Import a specification](./import-a-spec.md)), or from the CLI with `apiome import odata <file>`.

| What you have | How it is read |
| --- | --- |
| CSDL XML: a `$metadata` document or `.edmx` file, OData v4, v3 or v2 | Read by the CSDL XML reader. v2 and v3 associations become v4-style navigation properties. |
| CSDL JSON: the OData v4 JSON metadata format (`.json`, `"$Version": "4.0"` or `"4.01"`) | Read into the same model as CSDL XML, so both forms of one service import alike. |

## OASIS schema validation

Every OData **v4** document is checked against the OASIS
[CSDL JSON schema](https://docs.oasis-open.org/odata/odata-csdl-json/v4.01/os/schemas/csdl.schema.json):

- **CSDL JSON** is checked as uploaded.
- **CSDL XML** is first converted to its CSDL JSON form, following the OASIS mapping. For example,
  an XML property with no `Nullable` becomes `"$Nullable": true`, because the JSON form defaults to
  `false`. The converted form is checked, and it is kept with the catalog item.

v2 and v3 metadata has no CSDL JSON form, so it is not checked.

A document that does not match the schema **still imports**. Its problems are recorded on the catalog
item, each with the JSON pointer of the place it is about:

| Field | What it holds |
| --- | --- |
| `odata_csdl_valid` | `true` when the document matches the OASIS schema |
| `odata_csdl_violations` | Up to 50 problems, each a `path` and a `message`, such as `/Shop/Item/ID/$Nullable`: `'yes' is not of type 'boolean'` |
| `odata_csdl_violation_count` | How many problems there were in all |

Lint reports each problem as a warning under the
[`odata.csdl-schema`](../build/lint-rules.md#odata-csdl-schema) rule, at the path `csdl:<pointer>`.
To stop such services from being published, raise the rule to `error` in a copy of your
[style guide](../build/lint-and-quality.md).

## When the import refuses a document

| Code | Why | What to do |
| --- | --- | --- |
| `INPUT_MALFORMED` | The XML or JSON cannot be read. | Fix the syntax the message names. |
| `INPUT_SEMANTIC_INVALID` | The document declares no entity container, so it describes no service. | Add the `EntityContainer` (XML) or `$Kind: "EntityContainer"` member (JSON). |

## Related

- [Import a specification](./import-a-spec.md): the import paths every format shares
- [Supported formats](./supported-formats.md): OData's version coverage and export support
- [Built-in lint rules](../build/lint-rules.md): every rule with its rationale
