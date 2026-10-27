---
title: "Import an OData service"
description: "Catalog OData CSDL XML or JSON, validate it, or discover a live service."
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

## Discover a live service

Import a running OData service from the CLI by giving its **service root** (or its `$metadata` URL):

```bash
apiome import odata --discover https://services.example.com/odata/trippin/
apiome import odata --discover "https://sap.example.com/sap/opu/odata/sap/ZBP_SRV/?sap-client=100"
```

The CLI derives the `$metadata` URL (`<service root>/$metadata`, query string kept), reports it
(`Discovered OData $metadata at …`) and imports that document exactly as it would a `--url` import:
it is parsed, [checked](#how-the-metadata-is-checked), cataloged and linted. `--discover` must be the
only input.

| Problem | What you see |
| --- | --- |
| The URL is not `http`/`https` or has no host | The CLI stops with a usage error. |
| `$metadata` cannot be fetched (404, 401, network) | The CLI stops with the fetch error; check the service root and your access. |

## How the metadata is checked

Every OData document is checked three ways. None of the checks refuses an import: a document with
problems **still imports**, its problems are recorded on the catalog item, and lint reports them.

| Check | Versions | What it catches | Lint rule |
| --- | --- | --- | --- |
| OASIS CSDL JSON schema | v4 | A member of the wrong shape, such as a `$Nullable` that is not `true` or `false` | [`odata.csdl-schema`](../build/lint-rules.md#odata-csdl-schema) (warning) |
| OASIS CSDL XML schema | v4 CSDL XML | XML the JSON form never sees: a misspelled attribute (`Nulable`), an element CSDL does not define, a missing required attribute | [`odata.csdl-xsd`](../build/lint-rules.md#odata-csdl-xsd) (warning) |
| References and keys | v4, v3, v2 | A name that points at nothing, and an entity type with no usable key | [`odata.unresolved-reference`](../build/lint-rules.md#odata-unresolved-reference) and [`odata.entity-key`](../build/lint-rules.md#odata-entity-key) (errors) |

### OASIS schemas

The two OASIS schemas describe CSDL's shape:

- **CSDL JSON** is checked against the
  [CSDL JSON schema](https://docs.oasis-open.org/odata/odata-csdl-json/v4.01/os/schemas/csdl.schema.json)
  as uploaded.
- **CSDL XML** is checked against the OASIS
  [EDMX and EDM XML schemas](https://docs.oasis-open.org/odata/odata-csdl-xml/v4.01/os/schemas/).
  It is also converted to its CSDL JSON form, following the OASIS mapping, and that form is checked
  against the JSON schema and kept with the catalog item. For example, an XML property with no
  `Nullable` becomes `"$Nullable": true`, because the JSON form defaults to `false`.

v2 and v3 metadata has no OASIS schema, so it is not checked this way. The schemas are part of
Apiome: checking never fetches anything, even when a document names a schema location.

### References and keys

A document can be the right shape and still name things that do not exist. Apiome follows every
name a document uses:

- **Types**: property, parameter, return and term types, base types, and the entity type of each
  entity set and singleton. Names written with a schema alias (`self.Product`) resolve like
  namespace-qualified ones.
- **Relationships**: each navigation property's target type, partner and referential constraint;
  each navigation property binding's path and target; in v2 and v3, each association's ends and
  each association set's association, roles and entity sets.
- **Operations**: the action or function each import names, and the entity set it returns into.

Every entity type must also have a usable **key**: a non-abstract type declares one or inherits one
from its base type (a derived type must not declare its own), and each key property must exist and
be a single, non-nullable primitive, enumeration or type-definition value. A floating-point, stream
or spatial property cannot be part of a key.

A name in a namespace the document only references (`<edmx:Reference>`) and did not bring in is
not checked, because the import cannot see it.

Both rules are errors, so a document that breaks them fails a style guide's publish gate. Clients
generated from such metadata cannot bind the missing names or address the keyless entities.

### Where the problems are recorded

Each problem carries the path of the place it is about, written like a CSDL JSON pointer
(`/Namespace/Type/Member`):

| Field | What it holds |
| --- | --- |
| `odata_csdl_valid` | `true` when a v4 document matches the OASIS CSDL JSON schema |
| `odata_csdl_violations` | Up to 50 JSON schema problems, each a `path` and a `message`, such as `/Shop/Item/ID/$Nullable`: `'yes' is not of type 'boolean'` |
| `odata_csdl_violation_count` | How many JSON schema problems there were in all |
| `odata_xsd_violations` | Up to 50 XML schema problems, such as `/Shop/Item/ID`: `'Nulable' attribute not allowed for element` |
| `odata_xsd_violation_count` | How many XML schema problems there were in all |
| `odata_resolution_issues` | Up to 50 reference and key problems, each a `kind` (`reference` or `key`), a `path` and a `message`, such as `/Shop/Svc/Items/$Type`: ``entity set 'Items' names `Shop.Itm`, which is not declared.`` |
| `odata_resolution_issue_count` | How many reference and key problems there were in all |

The `odata_xsd_*` and `odata_resolution_*` fields are present only when there is a problem.

Lint reports each problem at its path: `csdl:<path>` for JSON schema, reference and key problems,
and `xml:<path>` for XML schema problems. To stop services that do not match the OASIS schemas
from being published, raise `odata.csdl-schema` and `odata.csdl-xsd` to `error` in a copy of your
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
