---
title: "Import an Apache Avro schema"
description: "Catalog Avro schemas and IDL, with fingerprints and Confluent-style compatibility checks."
sidebar_position: 45
tags: [import, avro, avdl, schema-registry, fingerprint, pcf, compatibility, breaking-changes, logical-types]
---

The **Avro** importer (`avro`) reads Apache Avro schemas into the [Catalog](./catalog.mdx). It
accepts both of Avro's surfaces: the JSON schema (`.avsc`) and the Avro IDL source (`.avdl`).
Records, enums and fixed types become types. An IDL `protocol` with messages becomes an RPC API with
one operation per message. You can then search, version, diff, lint and convert it like any other
catalog item.

## When to use it

Use the Avro importer for the schemas behind your Kafka topics and any other Avro data: Avro 1.12
JSON schemas and Avro IDL protocols. Bring them in as files, or read them straight from a
Confluent-compatible schema registry (Confluent Platform or Cloud, Karapace, Apicurio Registry's
compatibility API). Each version is fingerprinted the way Avro libraries do it, and compared by the
same rules a Confluent Schema Registry uses.

## At a glance

| Step | Where | Details |
| --- | --- | --- |
| **Import** an `.avsc` or `.avdl` file, or a file set | **Import to catalog** → **Avro**, or `apiome import avro` | [Import it](#import-it) |
| **Read** one schema from a schema registry | **URL Import** with a registry URL, or `apiome import avro --registry` | [Import from a schema registry](#import-from-a-schema-registry) |
| **Mirror** a whole registry, every subject and version | A `schema-registry` connector | [Schema registry connector](./schema-registry-connector.md) |
| **See** what the schema became: types, unions, logical types | The catalog item | [What the catalog item holds](#what-the-catalog-item-holds) |
| **Fingerprint** each type by Parsing Canonical Form | Automatic on every import | [Fingerprints](#fingerprints) |
| **Compare** two versions by the Avro schema resolution rules | Tick two versions on the catalog item's **Versions** tab, or `apiome registry compat` | [Compatibility between versions](#compatibility-between-versions) |
| **Lint** defaults, unions, aliases and `doc`s | The `avro` lint pack | [Lint](#lint) |
| **Convert** to an OpenAPI project | **Convert to OpenAPI** on the catalog item | [Per-format conversion packs](./convert-to-openapi.md#per-format-conversion-packs) |
| **Export** back to Avro, or **push** it to a registry | **Export** on the catalog item; a push over the REST API | [Export catalog items](../ship/export-catalog-items.mdx), [Push Avro to a schema registry](../ship/push-avro-to-a-schema-registry.md) |

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
- **A schema registry.** Read one schema from a Confluent-compatible schema registry. See
  [Import from a schema registry](#import-from-a-schema-registry).

The CLI's test fixtures include the same orders schema in each of Avro's surfaces:
`orders-avro.avsc` and `orders-avro.avdl`, in `apiome-cli/tests/fixtures/`. They are a quick way to
try an import:

```bash
apiome import avro apiome-cli/tests/fixtures/orders-avro.avdl
```

## Import from a schema registry

A Confluent-compatible schema registry serves each schema it holds at a *raw-schema* route:

- `<registry>/subjects/<subject>/versions/<version>/schema`, for one version of a subject.
- `<registry>/schemas/ids/<id>/schema`, for a schema by its global id.

The wizard and the CLI both import the schema from that route, so the catalog item records it as
its source. This imports one schema. To keep a whole registry in the catalog, with its credentials
and every subject's history, [mirror the registry](./schema-registry-connector.md) instead.

### In the import wizard

1. On the [Catalog](./catalog.mdx), **click “Import to catalog”** and choose **URL Import**.
2. Enter a registry URL as the **Document URL**:
   - `…/subjects/orders-value/versions/3`, for one version.
   - `…/subjects/orders-value/versions`, for the subject's latest version.
   - `…/schemas/ids/21`, for a schema by id.
   - A raw-schema URL ending in `/schema` works too.
3. **Click “Fetch and detect”**.

The first three routes answer with JSON *about* the schema: the schema wrapped in an envelope, or a
list of version numbers. The wizard recognizes that answer, fetches the raw-schema route instead,
and continues with the schema. An envelope for a JSON Schema or Protobuf schema is not followed.

The fetch runs in your browser, so the registry must allow requests from Apiome (CORS) and must not
need a sign-in. If it does, use the CLI, or mirror the registry.

### From the CLI

Give the registry's base URL to `--registry`, and name the schema:

```bash
apiome import avro --registry https://registry.example.com:8081 --subject orders-value
apiome import avro --registry https://registry.example.com:8081 --subject orders-value --version 3
apiome import avro --registry https://registry.example.com:8081 --schema-id 21
```

`--version` is `latest` (the default) or a version number. The base URL may carry a path prefix,
such as `https://host/apis/ccompat/v7`.

You can also name the subject the way a Kafka producer does, from its topic or record, with
`--strategy`:

| `--strategy` | Subject | Example |
| --- | --- | --- |
| `topic` (the default) | `<topic>-value`, or `<topic>-key` with `--key` | `--topic orders` → `orders-value` |
| `record` | The record's full name | `--record com.example.orders.Order` |
| `topic_record` | `<topic>-<record>` | `--topic orders --record com.example.orders.Order` → `orders-com.example.orders.Order` |

```bash
apiome import avro --registry https://registry.example.com:8081 --topic orders --key
apiome import avro --registry https://registry.example.com:8081 \
  --strategy topic_record --topic orders --record com.example.orders.Order
```

These are Confluent's `TopicNameStrategy`, `RecordNameStrategy` and `TopicRecordNameStrategy`, the
same names a mirrored registry records for each subject. `--registry` replaces the file or URL
input: use one or the other. See the [CLI reference](../reference/cli/import.md#import-avro) for every
option.

## What the catalog item holds

Both surfaces map the same way. Each named type becomes a catalog type, keyed by its full name
(`com.example.User`).

| Avro | Catalog item |
| --- | --- |
| `record` (and IDL `error`) | A record type, one field per Avro field, in order |
| A field's `default` | The field's default; an explicit `null` default counts as a default |
| `enum` | An enum type, one value per symbol, in order; its `default` symbol is kept |
| `fixed` | A scalar type that keeps its `size` |
| `["null", X]` | A nullable reference to `X` |
| Any other union | A union type, one member per branch |
| `map` | A map type, named after its values: `Map_long`, `Map_array_string` |
| `array` | A list of its `items` |
| `aliases` of a type or field, a field's `order` | Kept as written |

A union branch can be a type named elsewhere (`["Cat", "Dog"]`), a type declared inline, a map or
a primitive written as an object (`{"type": "long"}`). Each one becomes a member. An `array` branch
has no name of its own, so it is listed as `string`.

Custom attributes (`"x-owner": "team"`) are kept only from Avro IDL, where they are `@annotations`.

### Logical types

Every logical type in Avro 1.12 is read, on a field, behind `["null", X]`, or on a named `fixed`:

| Logical type | Written on | Read as |
| --- | --- | --- |
| `date` | `int` | `date` |
| `time-millis` / `time-micros` | `int` / `long` | `time` |
| `timestamp-millis` / `-micros` / `-nanos` | `long` | `date-time` |
| `local-timestamp-millis` / `-micros` / `-nanos` | `long` | `date-time` |
| `uuid` | `string`, or `fixed` of 16 bytes | `uuid` |
| `decimal` | `bytes` or `fixed`, with `precision` and `scale` | `decimal` |
| `big-decimal` | `bytes` | `decimal` |
| `duration` | `fixed` of 12 bytes | `duration` |

The exact logical type is kept beside the format, so a `timestamp-micros` field is exported back as
`timestamp-micros`, not as `timestamp-millis`.

The [Avro specification](https://avro.apache.org/docs/1.12.0/specification/#logical-types) says a
reader ignores a logical type it does not know, or one written on the wrong type. Apiome does the
same: it reads the field as its plain Avro type and marks the logical type `unknown` or `invalid`.
These count as invalid:

- A logical type on the wrong type, such as `{"type": "string", "logicalType": "date"}`.
- A `decimal` with no `precision`, or a `scale` below 0 or above its `precision`.
- A `decimal` on a `fixed` too small for its `precision`.
- A `uuid` or `duration` on a `fixed` of the wrong size.

The mark is a field's (or `fixed` type's) `avro_logical_type_ignored` key. The logical type itself
is still kept, so an export writes it back as it was.

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
| A field's `aliases` or `order` | Same | Changes | Yes |
| A field's type, a field added or removed, fields reordered | Changes | Changes | Yes |
| A type renamed, an enum symbol added | Changes | Changes | Yes |

A `doc`-only edit is not a change to the contract: it creates no new version, and a diff between
the two shows nothing breaking. An `aliases` or `order` edit does create one, because the catalog
item keeps them.

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
