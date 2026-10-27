---
title: "Import an Apache Avro schema"
description: "Catalog Avro schemas and IDL, with Parsing Canonical Form fingerprints."
sidebar_position: 45
tags: [import, avro, avdl, schema-registry, fingerprint, pcf]
---

The **Avro** importer (`avro`) reads Apache Avro schemas into the [Catalog](./catalog.mdx). It
accepts both of Avro's surfaces: the JSON schema (`.avsc`) and the Avro IDL source (`.avdl`).
Records, enums and fixed types become types. An IDL `protocol` with messages becomes an RPC API with
one operation per message. You can then search, version, diff, lint and convert it like any other
catalog item.

## Import it

Import the schema like any other catalog format: in the [import wizard](./import-wizard.mdx)
(**Import to catalog** → **Avro**), over the REST API (see
[Import a specification](./import-a-spec.md)), or from the CLI:

```bash
apiome import avro ./user.avsc
apiome import avro ./orders.avdl
```

- **One file.** Upload, paste or link the `.avsc` or `.avdl` file.
- **A file set.** Upload a `.zip`, `.tar.gz` or `.tar` holding an IDL file and the files it
  `import`s.

## Fingerprints

Every Avro catalog item records two hashes for each named type it declares. Each type is hashed
together with the named types it uses.

- **Parsing Canonical Form (PCF).** This is
  [Avro's own schema identity](https://avro.apache.org/docs/1.12.0/specification/#parsing-canonical-form-for-schemas).
  The schema is reduced to what a reader needs to decode its bytes: full names, types, fields in
  order, symbols, items, values and sizes. Everything else is stripped. Apiome hashes it two ways:
  - **CRC-64-AVRO**: the 64-bit fingerprint Avro libraries compute, shown as 16 hex digits.
  - **SHA-256**.

  Two schemas with the same PCF read and write the same binary data.
- **Semantic hash.** A SHA-256 over the same normalized schema, keeping what PCF strips: `doc`,
  `default`, `aliases`, `order`, `logicalType` and custom attributes. Defaults and aliases matter
  when a schema evolves, so this hash changes whenever anything in the schema does.

| Change | PCF | Semantic hash | New catalog version |
| --- | --- | --- | --- |
| A `doc` edited | Same | Changes | No |
| Key order or whitespace | Same | Same | No |
| A field's `default` | Same | Changes | Yes |
| A field's `aliases` or `order` | Same | Changes | No |
| A field's type, a field added or removed, fields reordered | Changes | Changes | Yes |
| A type renamed, an enum symbol added | Changes | Changes | Yes |

A `doc`-only edit is not a change to the contract: it creates no new version, and a diff between
the two shows nothing breaking. The catalog's version check does not read `aliases` or `order` yet,
so compare the semantic hashes to spot those edits.

The catalog item keeps the hashes under these keys:

| Key | Holds |
| --- | --- |
| `avro_pcf` | `crc64` and `sha256` of each named type, keyed by full name (`com.example.User`) |
| `avro_semantic_hashes` | The semantic hash of each named type, keyed by full name |
| `avro_root` | The full name of the document's root type |

The schema's own fingerprint is its root type's. An IDL `protocol` has no single schema, so it has
a fingerprint per type only.

:::note
The [schema registry](../reference/rest/schema-registry.md) still matches schemas by the catalog's
canonical fingerprint, not by PCF.
:::

## Lint

The `avro` lint pack checks the schema as written: defaults, union branches, aliases and `doc`s that
tools would drop. See [Lint rules](../build/lint-rules.md#pack-avro).
