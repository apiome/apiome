---
title: "Import an Apache Avro schema"
description: "Catalog Avro schemas and IDL, with fingerprints and Confluent-style compatibility checks."
sidebar_position: 45
tags: [import, avro, avdl, schema-registry, fingerprint, pcf, compatibility, breaking-changes]
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

## Compatibility between versions

Avro data written with one schema is read with another, and the
[Avro schema resolution rules](https://avro.apache.org/docs/1.12.0/specification/#schema-resolution)
decide whether that works. Apiome applies them the way a Confluent Schema Registry does, in two
places.

### Breaking changes in a diff

When you compare two versions of an Avro catalog item, each change is graded by which way the data
can still be read:

| What the check finds | Severity | Confluent modes it breaks |
| --- | --- | --- |
| The new schema cannot read data written with the old one | Breaking | `BACKWARD`, `FULL` |
| Only the old schema cannot read data written with the new one | Dangerous | `FORWARD`, `FULL` |
| Each reads the other's data | Safe | None |

For example:

| Change | Severity |
| --- | --- |
| A field added **without** a `default` | Breaking: new readers have nothing to fill it with |
| A field added **with** a `default` | Safe |
| A field removed that had no `default` | Dangerous: old readers miss it |
| A field removed that had a `default` | Safe |
| `int` widened to `long`, or a union branch added | Dangerous |
| `long` narrowed to `int`, or a union branch removed | Breaking |
| An enum symbol added (and the enum has no `default`) | Dangerous |
| An enum symbol removed | Breaking |
| A field renamed, keeping the old name in `aliases` | Dangerous: new readers find it by the alias, old readers do not |
| The namespace changed | Safe: Avro compares names without their namespace |

Each grade's explanation names the modes it breaks and gives the registry's own message, such as
`READER_FIELD_MISSING_DEFAULT_VALUE`. For an IDL `protocol`, every type both versions declare is
compared; its operations and messages keep the general rules.

### The schema registry

A subject's compatibility level now applies to Avro schemas. A new version is checked when you
register it, and an incompatible one is refused with HTTP `409`, as a Confluent registry refuses it:

| Level | The new schema must… |
| --- | --- |
| `BACKWARD` (the default) | read data written with the latest version |
| `BACKWARD_TRANSITIVE` | read data written with every version |
| `FORWARD` | be readable by the latest version |
| `FORWARD_TRANSITIVE` | be readable by every version |
| `FULL` / `FULL_TRANSITIVE` | both, against the latest version or every version |
| `NONE` | nothing; any schema registers |

To test a schema without registering it, use `apiome registry compat <subject> <file>`
([CLI reference](../reference/cli/registry.md#registry-compat)) or the Confluent
`POST /compatibility/subjects/{subject}/versions` route. The answer lists the same messages a
Confluent registry gives with `?verbose=true`. JSON Schema and Protobuf have no compatibility rules
yet: under any level but `NONE`, a second version of those is refused with error code `42290`.

## Lint

The `avro` lint pack checks the schema as written: defaults, union branches, aliases and `doc`s that
tools would drop. See [Lint rules](../build/lint-rules.md#pack-avro).
