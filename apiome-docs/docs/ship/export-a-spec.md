---
title: "Export a spec"
description: "Export a catalog item or version to another format, in the app or CLI."
sidebar_position: 5
tags: [export]
---

Apiome reconstructs the full OpenAPI 3.1 document (or Arazzo workflow document, or JSON Schema)
for a **published** version on demand. You can download it from the CLI or fetch it directly over
REST in JSON or YAML.

Those three have dedicated endpoints, but they are not the whole export surface: Apiome emits
**61<!--format-count:exportable--> formats** — AsyncAPI, GraphQL, Proto3, Avro, Thrift, Smithy,
TypeSpec, WSDL, XSD, OData, EDI X12, SAP IDoc, HL7 v2, FHIR, COBOL copybooks and more —
through the export-target registry. The full list, and which formats round-trip (import *and*
export) versus export only, is generated at [Supported formats](../bring-in/supported-formats.md).

Run `apiome export targets` to see the same list for a specific version, and
`apiome export evidence --target <format>` to see what a given conversion preserves before you
generate it.

## In the app: the Export dialog

The **Export** dialog exports one source to one format, and shows what the conversion keeps before
you download anything.
[The Export dialog](./export-dialog.mdx) is the overview: where to open it, its four steps and the
version's **Export** panel. The steps in detail:

1. Open it from a catalog item (**click "Export"** in the item's header) or from a version
   (on **Versions**, open the version's **⋯** menu and **click "Export to another format…"**).
2. The **Source** step names the item and version, and measures how well each format can carry
   it. **Click "Choose target"**.
3. Pick a format. Each card shows a fidelity badge for *this* source, such as *lossless* or
   *lossy*, and the line under the cards says how much is preserved (*64% preserved*). A card
   that cannot export this source is greyed out, with the reason written on it. **Click
   "Continue"**.
4. The fidelity report lists every construct the conversion drops, approximates or invents, and
   where each one lands. If the conversion loses something, tick the acknowledgement, or type the
   phrase it asks for when the result would be types only.
5. **Click "Export"** (**"Export anyway"** after an acknowledgement), review the file, and
   **click the "Download" button that names the file**, or **"Download .zip"** for everything in one
   archive.

   A format that writes several files (an Avro or Protobuf schema set, for example) previews its
   main file, and the zip button reads **"Download all files (.zip)"**. It runs the export as a job
   and downloads the job's bundle: every emitted file plus a `manifest.json` that lists them. The
   download starts when the job finishes; if the job fails, the dialog shows why.

**“Open in Export Studio”** at the foot of the dialog carries the source, target and options into
the [Export studio](./export-studio.mdx), which adds options, a verify step and a job you can watch.
For catalog items, including several at once, see [Export catalog items](./export-catalog-items.mdx).

<Screenshot id="export-dialog-targets" alt="The Export dialog's target step: format cards with fidelity badges, one greyed out with its reason" />

<Screenshot id="export-dialog-fidelity" alt="The Export dialog's fidelity report for Protobuf: what is kept, approximated and dropped, and the acknowledgement" />

## Formats the Export dialog offers

The dialog, `apiome export targets` and `GET …/export/targets` all offer the same **61<!--format-count:exportable--> formats**.
Most export from any source. A few write one format's own structure back out, so they export only
a source imported in that format: an EDI X12 interchange in the catalog exports back to EDI X12,
but an OpenAPI version does not. For any other source their card is greyed out with that reason,
and an export request is refused with `422`.

Formats that write HTTP routes or saved requests (Kong, Gateway API, Envoy, Istio, Traefik, Apigee,
AWS API Gateway, Azure API Management, Postman, Insomnia, Bruno, Hoppscotch, Thunder Client and the `.http`
file) need at least
one HTTP operation, and the data-contract formats (ODCS, Kafka Connect) need at least one record type.
API Blueprint needs at least one HTTP operation or one type. For a source without one, the card is
greyed out with that reason; for example, a GraphQL schema with no HTTP bindings cannot become a Kong
configuration.

A format that needs a tool this deployment does not have installed is greyed out the same way, with
the missing tool named on the card. It is never offered and then left to fail: an export to it is
refused with `422` and the same reason before anything runs. `apiome export targets` shows the reason
in its **Why not** column, and `apiome export <format>` stops with it (exit 2) before starting a job.

### Exports checked with the format's own tool

Some exports are checked with the tool that format's community uses, the same tool Apiome runs when
it imports that format. These tools only **check** an export; none is needed to **write** one, so the
format is offered whether or not the server has its tool. Without it, the export is still checked the
way the last column says.

| Export | Checked with | Without the tool |
| --- | --- | --- |
| Protobuf (gRPC) | `buf build` compiles every `.proto` | Not compiled; the export says it was not re-validated |
| TypeSpec | `tsp compile` to OpenAPI, and that OpenAPI must import | Read back by Apiome's TypeSpec reader |
| Smithy | `smithy validate` on each file, then `smithy ast` builds the model to import | Read back by Apiome's Smithy reader |
| RAML | AMF's RAML 1.0 validation | Read back by Apiome's RAML reader |
| API Blueprint | drafter, with no errors and no warnings | Read back by Apiome's API Blueprint reader |
| Thrift | The Thrift compiler, plus thriftpy2 | Checked by thriftpy2 and Apiome's Thrift reader |
| Cap'n Proto | `capnp compile` | Not compiled; the export says it was not re-validated |
| FlatBuffers | `flatc` | Read back by Apiome's FlatBuffers reader |
| CORBA IDL | `omniidl` (`corba` profile) or `idlc` (`dds` profile) | Read back by Apiome's CORBA IDL reader |
| FHIR | The HL7 FHIR validator | Checked by Apiome's structural FHIR rules |
| COBOL copybook | cb2xml parses the copybook, and the layout it reads must match the one Apiome planned | Read back by Apiome's copybook reader |
| X12 implementation guide | pyx12's segment dictionary, for the envelope and segments carried from X12 | Checked by Apiome's guide rules only |
| ASN.1 | asn1tools parses and compiles the module, and it must define exactly the planned types | Always checked: asn1tools ships with Apiome |
| AsyncAPI | The AsyncAPI parser | Not parsed; the export says it was not re-validated |
| Kubernetes CRD | Apiome's structural-schema rules, then kubeconform against the `apiextensions.k8s.io/v1` schema | Checked by Apiome's structural-schema rules only |
| WADL | The W3C WADL schema, and an XML Schema processor builds its grammar | Always checked: the schema and processor ship with Apiome |
| Google API Discovery | The Discovery metaschema and the document's rules | Always checked: the metaschema ships with Apiome |

The sections below say what each check rejects. [How an export is checked](./check-an-export.mdx)
explains the four verdicts and the lint of the exported file.

### When an item has nothing to export from

Exports are built from the source file captured when the item was imported. If that file was not
kept, or was not stored because it contained credentials, the **Export** dialog and the
[Export studio](./export-studio.mdx#1-source) say so instead of failing. **Click "Re-import"** to open **Import to catalog** and import the source
again.

<Screenshot id="export-dialog-missing-source" alt="The Export dialog for Orders RPC: it can't be exported because its source file wasn't kept, with a Re-import button" />

Over the API, every export route answers `422` with a structured `detail`:
`{"code": "source-not-captured" | "source-withheld", "message", "artifactId", "versionId", "reimport": true}`.
An export job fails with `SOURCE_LOAD_FAILED`, and its `error.context` carries the same `source_code`
and `reimport`.

### OpenAPI 3.2, 3.1, 3.0 and Swagger 2.0

Exporting to **OpenAPI** writes OpenAPI **3.1** by default. Set **openapi_version** to pick another
version. On the target card and in the options, a badge says what that choice does: `3.1 · native`,
`3.2 · newer`, or `3.0 · downgrade` / `2.0 · downgrade`.

- **3.2** writes OpenAPI 3.2.0 and keeps what only 3.2 can express:
  - a `QUERY` operation, as the path's `query` key;
  - any other method, such as `REPORT` or `PURGE`, under `additionalOperations`;
  - the tag tree of an item imported from OpenAPI 3.2, as `tags` with `parent`, `summary` and `kind`.

  The document is checked against the OpenAPI 3.2 schema before you download it. Tools that only
  read 3.1 may not open it.
- **3.1** has no `QUERY` or custom methods and no tag tree. Those operations are kept on the
  `x-apiome-query-operation` and `x-apiome-additional-operations` extensions, which 3.1 tools do not
  read. The tag tree is not written. The fidelity report lists each operation as approximated and the
  tag tree as dropped, and says to export 3.2 to keep them.
- **3.0** and **2.0** are downgrades of the 3.1 document. They report the same losses, plus what
  their version cannot express.

The fidelity report is computed for the version you pick, so changing **openapi_version** updates
it. From the CLI, run `apiome export openapi-3.1 <item> --out openapi.json --option openapi_version=3.2`.

Webhooks, callbacks and the full set of 3.2 security-scheme fields are not written yet, in any
version.

### AsyncAPI 3.1, 3.0 and 2.6

#### When to export to AsyncAPI

- **Round-trip an event API.** An item imported from AsyncAPI, or any other event source, exports
  back **lossless**: its channels, operations, messages and schemas are kept.
- **Describe a REST or RPC API as messages.** A REST or RPC item exports **lossy**. Each
  request / response operation is reframed as a `send` operation with a `reply`. The HTTP method,
  path and response status are not represented, and the fidelity report says so for each
  operation (see [Worked examples](./export-fidelity.md#worked-examples)).
- **Serve consumers on an older AsyncAPI.** Write 3.0 or 2.6 instead of 3.1; what the older version
  cannot hold is listed before you download.

#### AsyncAPI export at a glance

| Step | Where | Details |
| --- | --- | --- |
| **Pick** the AsyncAPI card and its version | **Export** dialog → **Events** → **AsyncAPI** | [Versions](#asyncapi-versions) |
| **See** what is kept, reframed or dropped | The fidelity report on the card | [Understand export fidelity](./export-fidelity.md#worked-examples) |
| **Trust** the file | Checked with the AsyncAPI parser before every download | [Exports checked with the format's own tool](#exports-checked-with-the-formats-own-tool) |
| **Export** from the CLI | `apiome export asyncapi --project … --version … -o asyncapi.json`, or `apiome export asyncapi-3 <item> --out …` | [Export from the CLI](./export-from-the-cli.md) |

A REST or RPC source is lossy, so from the CLI it exits non-zero unless you add `--force`.

#### Versions {#asyncapi-versions}

Exporting to **AsyncAPI** writes AsyncAPI **3.1** by default. Set **asyncapi_version** to `3.0` or `2.6`
for consumers on an older version; the badge then reads `3.0 · downgrade` or `2.6 · downgrade`.

- **3.0** has the same structure as 3.1 but not what 3.1 added. A `ros2` server or operation binding
  is dropped. A message example whose `headers` is not a map loses its headers. A schema format that
  names AsyncAPI `3.1.0` is written as `3.0.0`.
- **2.6** is the AsyncAPI 2 structure: each channel carries its own `publish` / `subscribe` operation,
  and a server has one `url`. It first drops what 3.0 drops, then everything else 2.x cannot express.

The fidelity report is computed for the version you pick. Each thing the older version cannot hold
is listed with where it was (`/servers/robot/bindings/ros2`), as dropped or approximated. Every
version is checked with the AsyncAPI parser before you download it. From the CLI, run
`apiome export asyncapi-3 <item> --out asyncapi.json --option asyncapi_version=3.0`.

### MCP tool definitions

Exporting to **MCP Tool Definitions** turns the API's operations into the tools an MCP host lists,
so an agent can call them. You get an MCP **server descriptor**, `<server>.mcp.json`. It holds the
server's `name`, `title` and `version`, `capabilities.tools`, and one tool per operation. It is the
same file **Import to catalog** reads for an MCP server, so it imports back.

Each tool has:

- a **`name`** — the operationId when it is a legal MCP tool name, else one made from it (or from
  the method and path), unique in the descriptor (`listPets`, `GET_orders_id`, `listOrders_2`). A
  name Apiome made up is listed as **synthesized** in the fidelity report;
- a **`description`** — the summary and description, plus a sentence saying what a successful call
  returns;
- an **`inputSchema`** — one object holding the path, query and header parameters and the request
  body, as JSON Schema;
- an **`outputSchema`** (2025-06-18) — the success response's schema, when the response is an
  object. A response that is an array or a single value is described in the description only,
  because MCP requires an object output schema.

Operations that are not callable — events, streams, and the resources and prompts of an imported MCP
server — get no tool, and the fidelity report lists them as dropped. Deprecated operations are left
out unless you turn on **include_deprecated**. A source with no callable operation is greyed out in
the **Export** dialog with that reason.

Options:

- **protocol_version** — `2025-06-18` (default) or `2025-03-26`, which has no `outputSchema`.
- **grouping** — `single` (default), or `per-service`: one descriptor per service,
  `<server>-<service>.mcp.json`, downloaded together as a `.zip`. A tool has the same name either way.
- **output_schema** — on by default. A server that serves these tools must return
  `structuredContent` matching each `outputSchema`; turn it off if yours does not.
- **include_deprecated** — also write a tool for each deprecated operation.

Every tool is checked against the MCP Tool schema of the chosen revision before you download it. The
descriptor describes the tools; it is not a running server. From the CLI, run
`apiome export mcp <item> --out petstore.mcp.json`, or
`apiome export mcp <item> --out <folder> --option grouping=per-service` for one file per service.

### SQL DDL from any source

Exporting to **SQL DDL** writes the item's types as `CREATE TABLE` statements, `<Name>.sql`, for a
database that stores what the API describes. Each object type becomes a table.

- **Columns.** Each field is a typed column: text is `TEXT` (or `VARCHAR(n)` when it has a
  `maxLength`), integers `SMALLINT` / `INTEGER` / `BIGINT`, a decimal `NUMERIC(38, s)` with the scale
  from `multipleOf`, a timestamp `TIMESTAMPTZ`, a UUID `UUID`, and so on. A required field is
  `NOT NULL`, and a field's default is its `DEFAULT`.
- **Rules.** `minimum` / `maximum` (and the exclusive bounds), `minLength`, an `enum` and a `pattern`
  become `CHECK` clauses on the column.
- **Enumerations.** PostgreSQL gets `CREATE TYPE … AS ENUM`, MySQL an inline `ENUM(…)`, and standard
  SQL a `VARCHAR` with `CHECK (… IN (…))`.
- **Names.** Tables and columns are written in `snake_case` (`OrderLine` → `order_line`,
  `placedAt` → `placed_at`). A name that starts with a digit gets a prefix, one that is too long is cut
  with a short hash, two that end up the same get `_2`, and a reserved word such as `user` or `order`
  is quoted.

Options:

- **dialect** — `postgres` (default), `mysql` or `ansi` (standard SQL).
- **nested** — what happens to a field that holds an object, a union, a map or a list:
  - `json` (default): one `JSONB` (PostgreSQL) or `JSON` column. A list of plain values is a native
    array on PostgreSQL (`TEXT[]`) and JSON elsewhere.
  - `tables`: an object becomes a foreign key to its table, and a list becomes its own table — a
    junction table for a list of objects (`order_lines`), or a child table of
    `(owner_id, position, value)` for a list of values (`order_tags`). Every table needs a key for
    this. It uses the table's declared key, else a required `id` field, else a generated `id` column.
- **schema_name** — create the tables in this schema (`CREATE SCHEMA` first, every name qualified).
- **output** — `ddl` (default) writes the SQL script; `dbml` and `prisma` write the same tables in
  another schema language (see [DBML and Prisma](#dbml-and-prisma) below).

Foreign keys come last, as `ALTER TABLE … ADD CONSTRAINT`, so the tables can be created in any order.

Every decision the projection makes up is listed in the fidelity report as **synthesized**: a
generated key, a junction or child table, a renamed table or column, a decimal precision Apiome had to
choose. The same model always gives the same script. What a dialect cannot hold is listed too: a
pattern in standard SQL (no regular-expression check), a UUID in MySQL (`CHAR(36)`), a time zone on a
MySQL `DATETIME`. Operations and channels are left out: a schema describes data only.

An item imported from SQL keeps its primary, unique and foreign keys. Written in the dialect it was
read in, it also keeps its column types, defaults and checks exactly. In another dialect, a default
or check expression written for the original dialect is dropped and listed.

**Checked before you download it.** Every script is parsed with sqlglot in its dialect, and read back
by Apiome's SQL reader. From the CLI, run `apiome export sql-ddl <item> --out schema.sql --option
dialect=mysql --option nested=tables`.

#### DBML and Prisma

Set **output** to write the same tables, columns, keys, enums and foreign keys in another language.
The **dialect**, **nested** and **schema_name** options still apply.

- **`dbml`** writes `<Name>.dbml` for [dbdiagram.io](https://dbdiagram.io) and dbdocs: one `Table` per
  table with the dialect's column types, an `Enum` for each enumeration (in every dialect), the
  `pk`, `not null`, `unique`, `default` and `check` settings, `indexes` for composite keys, and a
  `Ref` for each foreign key.
- **`prisma`** writes `schema.prisma`: one `model` per table, named in PascalCase and mapped back to
  its table with `@@map`. Columns get Prisma types with `@db.*` native types (`String @db.VarChar(40)`,
  `Decimal @db.Decimal(38, 2)`), and each foreign key becomes a named `@relation` on both models.
  Every model needs a key, so each table gets one as with **nested** `tables`. Prisma supports
  `postgres` and `mysql` only, and **schema_name** on PostgreSQL only (`@@schema`).

What the language cannot hold is listed in the fidelity report. Prisma has no `CHECK` constraint, no
interval type and no nullable list. It also cannot relate a foreign key that references a column that
is neither a primary nor a unique key, so that one stays as plain columns.

**Checked before you download it.** A DBML file is parsed by `@dbml/core`, and a Prisma schema must
pass `prisma validate`. From the CLI, run `apiome export sql-ddl <item> --out schema.prisma --option
output=prisma`.

### Apache Avro from any source

#### When to export to Avro

- **Give Kafka producers and consumers the schemas of an API's data.** Any item's types become Avro
  record, enum, union and map schemas, one `.avsc` per type, each with the Schema Registry subject it
  is registered under.
- **Register them on a schema registry.** Push the export to a Confluent-compatible registry through
  a connector; see [Push to a schema registry](./push-avro-to-a-schema-registry.md).

Avro describes data, not APIs: operations and channels are not written, so the export is
**types-only** for every source. Export to OpenAPI or AsyncAPI as well to keep them.

#### Avro export at a glance

| Step | Where | Details |
| --- | --- | --- |
| **Pick** the Avro card and its options | **Export** dialog → **Data schema & graph** → **Apache Avro** | [Where to find the Avro card](#where-to-find-the-avro-card) |
| **See** how types, fields and names are written | The fidelity report on the card | [How the item is written](#how-the-item-is-written-to-avro) |
| **Choose** the subject each schema is registered under | The card's subject options | [Subjects](#avro-subjects) |
| **See** what Avro cannot carry, and the defaults it adds | The fidelity report on the card | [What the fidelity report lists](#what-the-avro-fidelity-report-lists) |
| **Trust** the files: every schema parses | Automatic before every download | [How an Avro export is checked](#how-an-avro-export-is-checked) |
| **Push** the schemas to a registry | The REST API, through a schema registry connector | [Push to a schema registry](./push-avro-to-a-schema-registry.md) |

#### How the item is written {#how-the-item-is-written-to-avro}

Exporting to **Avro** writes one `.avsc` JSON schema per named type, in a folder per namespace
(`com.acme.Order` is `com/acme/Order.avsc`). Set the **output_syntax** option to `avdl` for one
Avro IDL document instead.

- **Types.** An object becomes a `record` with its fields in order, an enum an `enum`, a union an
  Avro union, and a map a `map` with string keys. A list is an `array`.
- **Nullable fields.** A field that may be null is the union `["null", T]`.
- **Logical types.** A `date` is an `int` with `logicalType: date`, a `date-time` a `long` with
  `timestamp-millis`, a `uuid` a `string` with `uuid`, and a `decimal` `bytes` with `decimal`. An item
  imported from Avro keeps its own logical types.
- **Names.** Avro names are letters, digits and `_`: any other character is replaced, and enum
  symbols likewise. The namespace is the item's own, or the **namespace** option for a source that
  has none.

#### Subjects {#avro-subjects}

Each schema has the Schema Registry subject it is registered under, chosen with the
**subject_naming** option:

| `subject_naming` | Subject | Example |
| --- | --- | --- |
| `record_name` (the default) | `{namespace}.{Type}-value`, one subject per type | `com.acme.Order-value` |
| `topic_name` | `{topic}-value`, set **topic** | `orders-value` |
| `topic_record_name` | `{topic}-{namespace}.{Type}-value`, set **topic** | `orders-com.acme.Order-value` |

Set **subject_role** to `key` to end each subject in `-key` instead of `-value`. These are
Confluent's `RecordNameStrategy`, `TopicNameStrategy` and `TopicRecordNameStrategy`.

#### What the fidelity report lists {#what-the-avro-fidelity-report-lists}

- **Operations and channels** are dropped (critical): Avro is types-only.
- **Validation rules** (lengths, ranges, patterns, formats with no logical type) are dropped: Avro
  does not enforce them.
- **Unions** are carried as an Avro union when every member is a record, an enum, a `fixed` or a
  primitive; any other union is approximated.
- **Nullable fields** are approximated as `["null", T]`.
- **Defaults** are synthesized for a nullable field that has none (`null`), because Avro schema
  evolution needs one.

#### How an Avro export is checked {#how-an-avro-export-is-checked}

Every schema is parsed with `fastavro` before the export is delivered, together with the schemas it
references, in whatever order they are written. A schema that does not parse fails the export.

#### Where to find the Avro card {#where-to-find-the-avro-card}

In the **Export** dialog, the **Apache Avro** card is under **Data schema & graph** on the **Target**
step, marked multi-file, so you download every schema in one `.zip`. Its badge is **types-only**.
Pick the card to set **output_syntax**, **namespace**, **subject_naming**, **topic** and
**subject_role**.

From the CLI, `apiome export avro --project <project> --version <version> --output <file>.avsc`
writes the **first** schema only, with the fidelity report. To get every schema, export Avro as one
of several formats, which runs a job and unpacks a folder per format:
`apiome export openapi-3.1 <item> --targets avro --out exports/`. See
[Export from the CLI](./export-from-the-cli.md).

### Protobuf and Thrift from an OpenAPI source

An OpenAPI schema's `type` and `format` become the target's own scalar types:

| OpenAPI | Protobuf | Thrift |
| --- | --- | --- |
| `integer` | `int32` | `i32` |
| `integer`, `format: int64` | `int64` | `i64` |
| `number` | `double` | `double` |
| `number`, `format: float` | `float` | `double` |
| `boolean` | `bool` | `bool` |
| `string` | `string` | `string` |

OpenAPI has no field numbers, so the first export numbers each field in the order the schema lists
it: `1`, `2`, `3` and so on. Apiome remembers those numbers for the item, so every later export to
the same format gives each field the same number, even after fields are added, removed or
reordered. A field added since gets the next number not used yet. The fidelity report lists every
number Apiome assigned as *synthesized*. A source that has its own numbers, such as a Protobuf or
Thrift import, keeps them.

### Thrift from any source

#### When to export to Thrift

- **Move an API to Thrift.** An OpenAPI, gRPC, GraphQL, WSDL or Avro item becomes one `.thrift` file
  of structs, enums, unions, exceptions and services that the Thrift compiler accepts, for services and
  stacks that still speak Thrift. What Thrift cannot carry is listed in the fidelity report before you
  download.
- **Keep clients compatible across exports.** Apiome stores each field id it assigns, so every later
  export of the item gives a field the same id and never reuses a removed one.
- **Round-trip a Thrift item.** An item imported from Thrift exports **lossless**, with its field ids,
  namespaces and `typedef`s.

#### Thrift export at a glance

| Step | Where | Details |
| --- | --- | --- |
| **Pick** the Apache Thrift card and its options (comments, namespaces) | **Export** dialog → **Apache Thrift** (under **RPC**) | [Where to find the Apache Thrift card](#where-to-find-the-apache-thrift-card) |
| **See** how types, errors, services, field ids and names are written | The fidelity report on the card | [How the item is written](#how-the-item-is-written-to-thrift) · [scalar types from OpenAPI](#protobuf-and-thrift-from-an-openapi-source) |
| **See** what Thrift cannot carry | The fidelity report on the card | [What the fidelity report lists](#what-the-thrift-fidelity-report-lists) |
| **Trust** the file: the Thrift compiler, thriftpy2, then re-import | Automatic before every download | [How a Thrift export is checked](#how-a-thrift-export-is-checked) |
| **Export** from the CLI | `apiome export thrift <item> --out <file>.thrift` | [Where to find the Apache Thrift card](#where-to-find-the-apache-thrift-card) |

Exporting to **Apache Thrift** writes one `<Name>.thrift` file that the Thrift compiler accepts.

#### How a Thrift export is checked {#how-a-thrift-export-is-checked}

Each export is checked before you download it:

1. The **Thrift compiler** (`thrift`) compiles it when the server has the compiler. A compile error
   fails the export and quotes the compiler's message and line. An export that `include`s another
   file is not compiled, because the compiler is given one file at a time.
2. **thriftpy2**, a second Thrift parser, reads it too, and must agree with Apiome's Thrift importer on
   every enum, struct, union, exception, field id and service method. This check runs with or
   without the compiler.
3. The export imports again as Thrift.

A failed check names the file and the rule (`thrift.compile`, `thrift.thriftpy2-parse`,
`thrift.parser-disagreement`, `thrift.reimport`). An item imported from Thrift exports and re-imports
unchanged.

#### How the item is written {#how-the-item-is-written-to-thrift}

- **Types.** Objects become `struct`s, enums `enum`s, and unions `union`s. A union that only lists
  its member types gets one optional field per member. Aliases and named scalars become `typedef`s,
  lists `list<…>`, sets `set<…>`, and maps `map<…, …>`. A required field is `required`; every other
  field is `optional`.
- **Errors.** A type returned only as an error response becomes an `exception` and is listed in the
  method's `throws`. An error type also used elsewhere stays a `struct`, and the report says its
  `throws` entry is not written, because Thrift throws only exceptions.
- **Services.** Each service becomes a `service` and each operation a method. A method returns its
  success response's type. An operation with parameters (an OpenAPI path or query parameter, say)
  takes one `<Method>Request` struct that holds them and the body; otherwise it takes its request
  type as `1: T arg`.
- **Field ids.** A Thrift item keeps its own field ids. A field without one (from OpenAPI, say) gets
  the next free id, and Apiome stores it, so the next export of the item gives that field the same
  id. A field you add later gets a new id, and the id of a field you removed is never reused, so
  clients built from an earlier export keep reading the wire correctly.
- **Names.** Thrift names are plain identifiers that are not reserved words. `com.acme.Order` is
  written `com_acme_Order`, `order-id` is `order_id`, and `default` is `default_`. Each rename is in
  the fidelity report, and a clash gets a number (`addPet2`).
- **Namespaces.** Set the **namespaces** option to write one `namespace` line per language, for
  example `{"java": "com.acme.shop", "py": "acme_shop"}`, or `*` for every language. A Thrift item
  keeps its own namespaces and `typedef`s.
- **uuid.** A UUID is written as `string`, because only Thrift 0.21 and later compilers know the
  `uuid` type. An item imported from Thrift keeps `uuid`.
- **Constraints.** Thrift has no validation, so a field's, parameter's or type's constraints are
  written as a comment above it — `// constraints: >= 1; max length 40; pattern ^[A-Z]+$` — for the
  people reading the file. Nothing enforces them.

#### What the fidelity report lists {#what-the-thrift-fidelity-report-lists}

The fidelity report lists what Thrift cannot carry, each on the construct it affects:

| What the source has | What the report says | Kind |
| --- | --- | --- |
| Constraints (pattern, bounds, lengths, format) | Written as a comment, not enforced | approximated |
| A nullable field | Written `optional`: Thrift has no null, so it is absent instead | approximated |
| An HTTP operation | Written as an RPC method | approximated |
| Its HTTP method, path, status codes and parameter locations | Not written | dropped |
| Event operations and channels (AsyncAPI) | Not written: Thrift has no events | dropped |
| A type that extends another (TypeScript, Pydantic, SQL `INHERITS`) | One `struct` holding the inherited fields | approximated |
| A field with no field id | A field id is assigned | synthesized |
| A streaming call | Written as one call | dropped |
| A map type | Written inline as `map<K, V>`; its declaration is not kept | dropped |
| The title, version, description and servers | Not written: an IDL file has no place for them | dropped |
| A renamed type, service or method, or a `<Method>Request` struct | Dropped under its old key and added under the new name, which is how it reads back | dropped / synthesized |

Exporting an OpenAPI, gRPC, GraphQL, WSDL or Avro source to Thrift and reading it back shows no
change the report did not name.

#### Where to find the Apache Thrift card {#where-to-find-the-apache-thrift-card}

In the **Export** dialog, the **Apache Thrift** card is under **RPC** on the
**Target** step, as one file. Its badge is **lossless** for an item imported from Thrift and **lossy**
for any other source. Pick the card to see **Include Comments** (on by default), which writes the
header comment. The **namespaces** option (`namespace` lines per language) is set from the CLI or the
REST API: run `apiome export thrift <item> --out <file>.thrift`, and add
`--option 'namespaces={"java": "com.acme"}'` or `--option include_comments=false`. A lossy export exits
non-zero unless you add `--force`, and `--json` prints the tier. A public item's **Export** dialog on
Browse offers Thrift too, as the `.thrift` file.

### OMG IDL (CORBA or DDS) from any source

#### When to export to OMG IDL

- **Serve a CORBA estate.** With the `corba` profile, an API's services become IDL `interface`s with
  their operations and exceptions, for CORBA middleware (defense, telecom, finance) that omniidl
  compiles.
- **Define DDS topic types.** With the `dds` profile, the item's data types — with `@key` fields and
  one topic per event channel — are written for a DDS application that Cyclone DDS `idlc` compiles.
- **Round-trip a CORBA IDL item.** An item imported from CORBA IDL exports **lossless**, with its
  modules, `typedef`s and parameter directions.

What IDL cannot carry is listed in the fidelity report, for the profile you pick, before you
download.

#### OMG IDL export at a glance

| Step | Where | Details |
| --- | --- | --- |
| **Pick** the CORBA IDL card and its options (profile, module, comments) | **Export** dialog → **CORBA IDL** (under **RPC**) | [Where to find the CORBA IDL card](#where-to-find-the-corba-idl-card) |
| **See** how types, modules, interfaces, keys and names are written | The fidelity report on the card | [How the item is written](#how-the-item-is-written-to-omg-idl) |
| **See** what the profile you picked cannot carry | The fidelity report on the card | [What the fidelity report lists](#what-the-omg-idl-fidelity-report-lists) |
| **Trust** the file: omniidl or `idlc`, then re-import | Automatic before every download | [How an IDL export is checked](#how-an-idl-export-is-checked) |
| **Export** from the CLI | `apiome export idl <item> --out <file>.idl` | [Where to find the CORBA IDL card](#where-to-find-the-corba-idl-card) |

Exporting to **CORBA IDL** writes one `<Name>.idl` file in OMG IDL 4.2 that reference IDL compilers
accept: omniidl for the CORBA parts and Cyclone DDS `idlc` for the annotated data types.

#### How an IDL export is checked {#how-an-idl-export-is-checked}

Each export is checked before you download it:

1. **The profile's IDL compiler** checks it when the server has that compiler: `omniidl` for a
   `corba` export, `idlc` for a `dds` export. A compile error fails the export and quotes the
   compiler's message and line (`idl.compile`).
2. Apiome's CORBA IDL importer reads it back (`idl.reimport`). Without the compiler, this is the check.

#### How the item is written {#how-the-item-is-written-to-omg-idl}

- **Profile.** The **profile** option picks what is written. `corba` (the default) writes interfaces
  and exceptions. `dds` writes only the data types a DDS topic can use: no interfaces, no exceptions
  and no member that refers back to its own type. It also marks identifier fields `@key`. A source
  with no data types cannot be exported with `dds`, and the dialog says why.
- **Types.** Objects become `struct`s, enums `enum`s, and aliases and named scalars `typedef`s. Lists
  become `sequence<…>`. A map becomes a sequence of `<Map>Entry` key/value structs. A union becomes
  a discriminated `union` that switches on a generated `<Union>Kind` enum, with one case per member.
  A nullable field is marked `@optional`.
- **Modules.** The item's namespace becomes nested modules: `com.acme.orders` is written
  `module com { module acme { module orders { … }; }; };`. Set the **module** option (`acme::orders`)
  to choose another path. Every type reference is written in full (`::com::acme::orders::Order`).
- **Interfaces.** Each service becomes an `interface` and each operation an IDL operation. Its
  parameters and request body are `in` arguments, and it returns its success response's type. A list
  in a signature is given a `typedef` (`PetSeq`). A type returned only as an error response becomes
  an `exception` and is listed in the operation's `raises`. Any other error response is left out, and
  the report says so.
- **Keys (DDS).** A field named `id`, `<type>Id` or `<type>_id` gets `@key`. Set the **key_fields**
  option to choose the keys yourself, for example `{"Order": ["region", "number"]}`.
- **Names.** IDL names are identifiers, compared without regard to case. `order-id` is written
  `order_id`, `module` is `module_`, and of two members `id` and `ID` the second becomes `ID2`. A
  member cannot share its type's name, and an enum value must be unique in its module, so it may be
  prefixed with its enum's name (`Status_ACTIVE`). Each rename is in the fidelity report.
- **Recursion.** A type may contain itself only through a `sequence`. A direct reference to itself is
  written as a sequence of at most one element. A member that refers back through another type is
  left out, and so is any recursive member under the `dds` profile.
- **From a CORBA item.** An item imported from CORBA IDL keeps its module, `typedef`s, interfaces and
  parameter directions (`in`, `out`, `inout`).
- **Constraints.** A string's maximum length is written as a bounded string (`string<40>`) and a
  list's maximum size as a bounded sequence (`sequence<Tag, 5>`), so they are kept. IDL has no other
  validation, so every other constraint is written as a comment above the member, typedef or
  operation — `// constraints: >= 1; pattern ^[A-Z]+$` — and nothing enforces it.
- **Channels (DDS).** Under the `dds` profile each event channel is a DDS topic: its message type is
  declared, and a comment names the topic (`// DDS topic "orders.placed": ::shop::Order`). A DDS
  application creates the topic from that name and type.

#### What the fidelity report lists {#what-the-omg-idl-fidelity-report-lists}

The fidelity report depends on the profile:

| What the source has | `corba` | `dds` |
| --- | --- | --- |
| A maximum string length or list size | Kept as a bound — not reported | Kept as a bound — not reported |
| Any other constraint | Written as a comment, not enforced (approximated) | Same |
| An HTTP operation | An IDL operation (approximated); its method, path, status codes and parameter locations are dropped | Dropped: the profile writes data types only |
| Any other operation | An IDL operation | Dropped |
| An event channel | Dropped | A DDS topic named in a comment (approximated) |
| Publish / subscribe operations | Dropped | Dropped (the channel is the topic) |
| A map | A sequence of key/value entry structs (approximated) | Same |
| A union | Its discriminator enum is generated (synthesized) | Same |
| A source's field numbers (Protobuf, Thrift) | Dropped: IDL has none | Same |

An item imported from CORBA IDL exports back **lossless**: its members keep their order, which is all
IDL records about them.

#### Where to find the CORBA IDL card {#where-to-find-the-corba-idl-card}

In the **Export** dialog, the **CORBA IDL** card is under **RPC** on the
**Target** step, as one `.idl` file. Its badge is **lossless** for an item imported from CORBA IDL and
**lossy** for any other source. Pick the card to see **Profile** (`corba` by default, or `dds`),
**Module** (empty: the item's own module or name) and **Include Comments** (on by default). The DDS
`@key` fields are set from the CLI or the REST API with **key_fields**. From the CLI, run
`apiome export idl <item> --out <file>.idl` (`omg-idl` and `corba-idl` work too), and add
`--option profile=dds` or `--option 'key_fields={"Order": ["orderId"]}'`. A CORBA export written
without comments is still checked by omniidl. A lossy export exits non-zero unless you add `--force`,
and `--json` prints the tier. A public item's **Export** dialog on Browse offers IDL too, as the
`.idl` file.

### Smithy from any source

#### When to export to Smithy

- **Move an API to Smithy.** Any REST, RPC, GraphQL, JSON Schema or WSDL item becomes a Smithy 2.0
  model that `smithy validate` accepts: shapes with traits, services and operations, with each HTTP
  binding kept. What Smithy cannot carry is listed in the fidelity report before you download.
- **Round-trip a Smithy item.** An item imported from Smithy exports back **lossless**, with its
  namespace, `$version` and operation order.

#### Smithy export at a glance

| Step | Where | Details |
| --- | --- | --- |
| **Pick** the Smithy card and its options (IDL, JSON AST or both; protocol) | **Export** dialog → **Smithy** (under **RPC** in **Export studio**) | [Where to find the Smithy card](#where-to-find-the-smithy-card) |
| **See** how shapes, traits, services, errors and names are written | The fidelity report on the card | [How the item is written](#how-the-item-is-written-to-smithy) |
| **See** what Smithy cannot carry | The fidelity report on the card | [What the fidelity report lists](#what-the-smithy-fidelity-report-lists) |
| **Trust** the model: `smithy validate`, then re-import | Automatic before every download | [How a Smithy export is checked](#how-a-smithy-export-is-checked) |
| **Export** from the CLI | `apiome export smithy <item> --out <file>.smithy` | [Where to find the Smithy card](#where-to-find-the-smithy-card) |

Exporting to **Smithy** writes a Smithy 2.0 model that `smithy validate` accepts. Set the **output**
option to choose the form: `idl` (the default) writes `<Name>.smithy`, `json-ast` writes the Smithy
JSON AST as `<Name>.json`, and `both` writes the two. They describe the same model, so load one of
them, not both together.

#### How a Smithy export is checked {#how-a-smithy-export-is-checked}

Each export is checked before you download it:

1. The **Smithy CLI** validates each file when the server has it, with the same validators a
   `smithy build` runs. An `ERROR` or `DANGER` event fails the export and names the validator, shape,
   line and column (`Target.UnresolvedShape`). `WARNING` and `NOTE` events do not. Without the CLI,
   Apiome's Smithy reader reads the model instead, and a parse error fails the export.
2. The built model is then imported again. If it does not import, the export fails
   (`smithy.reimport`).

#### How the item is written {#how-the-item-is-written-to-smithy}

- **Shapes.** Objects become `structure`s, unions `union`s, enums `enum`s, maps `map`s, and named
  lists `list`s. A list with no name of its own gets a `<Element>List` shape. A named scalar or an
  alias of a scalar becomes a simple shape (`string AccountId`). An enum value that differs from its
  member name is written `in_progress = "in-progress"`.
- **Traits.** A field that may not be null is `@required`, and a field default becomes `@default`.
  Length limits become `@length`, numeric bounds `@range`, and regular expressions `@pattern`. A list
  that must hold unique items targets a `<Element>Set` shape marked `@uniqueItems`. Descriptions
  become doc comments, and deprecated items get `@deprecated`. A constraint Smithy cannot express,
  such as `multipleOf`, is in the fidelity report.
- **Services.** Each service becomes a `service` and each operation an `operation`. An HTTP
  operation keeps its binding: `@http(method, uri, code)`, with path, query and header parameters
  bound by `@httpLabel`, `@httpQuery` and `@httpHeader`, and the body by `@httpPayload`. When an
  operation needs one, its input and output are generated structures (`<Operation>Input`,
  `<Operation>Output`). GET operations are `@readonly`, PUT and DELETE operations `@idempotent`. A
  GET, HEAD or DELETE request has no body in Smithy, and transport headers such as `Authorization`
  are not bound. The report lists both.
- **Errors.** A type returned only as an error response becomes an `@error` structure, with
  `@httpError` for its status, and is listed in the operation's `errors`.
- **Protocol.** Set the **protocol** option to `restJson1` or `rpcv2Cbor` to mark each service with
  that protocol trait. These traits come from separate Smithy packages, so a build needs them as
  dependencies.
- **Names.** Smithy names are identifiers that must stay unique when case is ignored. `order-id` is
  written `order_id` and keeps its wire name with `@jsonName("order-id")`. A shape cannot reuse a
  prelude name such as `String`, and a clash gets a number (`String2`). Each rename is in the
  fidelity report.
- **From a Smithy item.** An item imported from Smithy keeps its namespace, `$version`, service
  version and operation order. Traits that were imported by name only, such as a `@length` whose
  limits were not kept, cannot be written back, and the report says so. A `resource` is not written
  back either; its operations stay on the service.

#### What the fidelity report lists {#what-the-smithy-fidelity-report-lists}

The fidelity report lists what Smithy cannot carry, on the type, field or operation it concerns.
The report predicts exactly what the export writes:

- **Dropped:** constraints with no Smithy trait (`multipleOf`, a list of allowed values, a length on a
  number), and a default that does not fit its type. Also dropped: parameters Smithy cannot bind
  (cookies, and transport headers such as `Authorization`), the body of a GET, HEAD or DELETE
  request, error responses that are not objects, and event operations and channels. A route that is
  not a valid Smithy URI, or that repeats another, loses its `@http` binding.
- **Approximated:** renamed shapes and members, aliases written as the type they alias, bodies
  wrapped in a `body` member, scalars written as `String`, and a required member made optional to
  break a cycle.
- **The document.** Smithy has no title, description or servers, so for an item not imported from
  Smithy the report lists each one. The version moves to each service, or is dropped when there is
  no service.
- **Carried.** For each operation and type that is carried, the report names the Smithy shape it
  became, such as `operation getPet @http(GET /pets/{id})` or `structure Pet`.

#### Where to find the Smithy card {#where-to-find-the-smithy-card}

In the **Export** dialog, the **Smithy** card is on the **Target** step (under
**RPC** in **Export studio**), as one file. Its badge is **lossless** for an item imported from Smithy
and **lossy** for any other source. Pick the card to see its four options: **Output** (`idl` by
default; `json-ast` or `both`), **Protocol** (`none` by default; `restJson1` or `rpcv2Cbor`),
**Include Comments** (on by default), which writes the IDL header comment, and **Smithy Version**
(`2.0`). From the CLI, run `apiome export smithy <item> --out <file>.smithy`, and add
`--option output=json-ast` or `--option protocol=restJson1`. A lossy export exits non-zero unless you
add `--force`, and `--json` prints the tier. A public item's **Export** dialog on Browse offers Smithy
too: the `.smithy` file, or with `both` a zip of the two views.

### TypeSpec from any source

#### When to export to TypeSpec

- **Move an API to TypeSpec.** Any REST, RPC, GraphQL, JSON Schema or WSDL item becomes one `.tsp`
  file that compiles, ready to edit as the source of truth. What TypeSpec HTTP cannot carry, and what
  is reframed as HTTP, is listed in the fidelity report before you download.
- **Round-trip a TypeSpec item.** An item imported from a `.tsp` file exports back **lossless**, with
  its imports, namespace, routes and decorators.

#### TypeSpec export at a glance

| Step | Where | Details |
| --- | --- | --- |
| **Pick** the TypeSpec card and its options | **Export** dialog → **REST & HTTP** → **TypeSpec** | [Where to find the TypeSpec card](#where-to-find-the-typespec-card) |
| **See** how the document, types, members and operations are written | The fidelity report on the card | [How the item is written](#how-the-item-is-written-to-typespec) |
| **See** what is dropped, approximated or reframed | The fidelity report on the card | [What the fidelity report lists](#what-the-typespec-fidelity-report-lists) |
| **Trust** the file: it compiles and its OpenAPI imports | Automatic before every download | [How a TypeSpec export is checked](#how-a-typespec-export-is-checked) |
| **Export** from the CLI | `apiome export typespec <item> --out <file>.tsp` | [Where to find the TypeSpec card](#where-to-find-the-typespec-card) |

Exporting to **TypeSpec** writes one `.tsp` file that compiles with the TypeSpec compiler Apiome
ships (`tsp` 0.65 with `@typespec/http`), whatever the item was imported from.

#### How a TypeSpec export is checked {#how-a-typespec-export-is-checked}

Each export is checked before it is offered:

1. It is compiled to OpenAPI with `@typespec/openapi3`. A compile error fails the export and names
   the file, line, column and error code (`unknown-identifier`).
2. The OpenAPI the compile writes is imported the way an uploaded OpenAPI would be. If it does not
   import, the export fails (`typespec.openapi-import`).

Without the compiler on the server, the `.tsp` is read back by the TypeSpec importer instead.

Compiling to OpenAPI also shows what choosing TypeSpec costs compared with exporting straight to
**OpenAPI**: `@typespec/openapi3` names each operation `<Interface>_<operation>`
(`PetService_listPets`), writes a plain `integer` as `int32`, and makes a request body required.

#### How the item is written {#how-the-item-is-written-to-typespec}

- **Document.** The title becomes `@service({ title: "…" })` on the namespace, and the description
  becomes its doc comment. The version becomes `@info({ version: "…" })` (from `@typespec/openapi`),
  and each server becomes `@server(url, description)` with its variables.
- **Types.** Objects become `model`s, enums `enum`s, and unions `union`s, with named variants or
  their member types. Maps become `model X is Record<V>`, and named lists `model X is T[]`. A named
  scalar becomes `scalar X extends string` (or `int64`, `utcDateTime` …), and an alias of another type
  becomes `alias X = T`. An enum value that differs from its member name is written
  `inProgress: "in-progress"`, and a numeric enum keeps its numbers.
- **Members.** A field that may be null is optional (`tag?: string`). Length limits become
  `@minLength` and `@maxLength`, numeric bounds `@minValue` and `@maxValue` (or their `Exclusive`
  forms), list sizes `@minItems` and `@maxItems`, and patterns `@pattern`. A string format with a
  TypeSpec type of its own becomes that type (`date-time` is `utcDateTime`); any other format is kept
  with `@format`. A default becomes `= value`. Descriptions become `/** … */` doc comments, and
  deprecated items get `#deprecated`.
- **Operations.** Each service becomes an `interface`. An HTTP operation keeps its verb and
  `@route`, with parameters marked `@path`, `@query`, `@header("Name")` or `@cookie("name")`, and
  the body `@body`. A body that is not JSON names its media types in a `Content-Type` header. A plain
  200 response is the return type. Other responses are variants such as
  `{ @statusCode statusCode: 201; @body body: Pet; }`, a `4XX` range is a status between 400 and 499,
  and a `default` error is an `@error` model. An operation with no HTTP binding is written
  `@post @route("/<Service>/<operation>")`.
- **Decorators.** Tags become `@tag("…")`. A parameter's or header's description becomes
  `@doc("…")`, and a deprecated parameter or header gets `#deprecated`. A list of allowed values
  becomes a union of literals (`sort?: "name" | "age"`). A server variable with allowed values gets
  them as its type, and its description as `@doc`.
- **Names.** Every name is kept: a name that is not a TypeSpec identifier, or is a keyword, is written
  in backticks (`` `order-id` ``). A type cannot reuse a built-in name such as `string`, and a clash
  gets a number (`string2`). Each rename is in the fidelity report.
- **From a TypeSpec item.** An item imported from a `.tsp` file keeps its imports, namespace,
  interface routes, field types and decorators, so it exports and re-imports unchanged.

#### What the fidelity report lists {#what-the-typespec-fidelity-report-lists}

The fidelity report lists what TypeSpec cannot carry, on the type, field or operation it concerns:

- **Dropped:** constraints with no decorator (`multipleOf`, `uniqueItems`), a default that does not
  fit its type, and numeric enum values beside string ones. Also dropped: operations on a method
  TypeSpec has no verb for (such as `OPTIONS`), a second operation on the same route, a path
  parameter missing from its route, multipart media types on a body that is not an object, and
  event operations and channels. A response's own description is dropped too, since an inline
  response gets its status's standard text, and so is the document's id.
- **Approximated:** renames, RPC operations given an HTTP route, aliases (they compile to the type
  they alias), scalars written as `string`, inline schemas written as `unknown`, synthesized path
  parameters and `default` response models. Types from another namespace are declared in the
  document's one namespace.
- **Other API styles.** TypeSpec HTTP describes REST APIs. For a GraphQL, gRPC, event or data-schema
  item the report says the API is reframed as HTTP. Each operation without an HTTP binding is
  listed as a GraphQL query, mutation or subscription, a one-way call or an RPC call, with the
  `POST` route it became. A GraphQL subscription or a streaming call is listed as one request and
  response, and event messages and a second request body are listed as dropped.
- **Carried.** For each operation and type that is carried, the report names what it became, such as
  `op getPet @get /pets/{id}` or `model Pet`.

#### Where to find the TypeSpec card {#where-to-find-the-typespec-card}

In the **Export** dialog, the **TypeSpec** card is under **REST & HTTP** on the
**Target** step, as one file. Its badge is **lossy** for a REST, RPC, GraphQL, JSON Schema or WSDL
source and **lossless** for an item imported from TypeSpec. Pick the card to see its two options, both
on by default: **Include Http Imports** writes the `@typespec/http` import and `using` the document
needs to compile (turn it off only if you add them yourself), and **Include Comments** writes the
header comment. From the CLI, run `apiome export typespec <item> --out <file>.tsp`, and add
`--option include_http_imports=false` or `--option include_comments=false`. A lossy export exits
non-zero unless you add `--force`, and `--json` prints the tier. A public item's **Export** dialog on
Browse offers TypeSpec too, as the `.tsp` file.

### Healthcare exports

Healthcare interfaces describe their data in two generations of HL7 standards: FHIR for modern REST
APIs, and HL7 v2 for the pipe-and-hat messages most hospital integration engines still run on. Apiome
writes both from an item's types, plus the original message for an item imported from HL7 v2. In
**Export studio**, the three cards sit together under **Healthcare** on the **Target** step.

#### When to use which

- **A FHIR server or profile author: FHIR.** Export [FHIR](#fhir-structuredefinition-from-any-source)
  for a StructureDefinition logical model per type (R4 or R5), a CodeSystem and ValueSet per enum, and the
  source's operations summarized in a CapabilityStatement. It is checked by the official HL7 FHIR
  validator when the server has it.
- **An interface partner on HL7 v2: HL7 v2 segment guide.** Export an
  [HL7 v2 segment guide](#hl7-v2-segment-guide-from-any-source) for the message and segment definitions an
  integration engine (Mirth Connect, Rhapsody, Cloverleaf) is configured from: Z-segments, typed fields
  and a user-defined table per enum. It is laid out by the same plan as the X12 and UN/EDIFACT guides.
- **An HL7 v2 message back out: HL7 v2.** An item imported from an HL7 v2 message exports back to
  **HL7 v2**, its segments and envelope as they were imported. It is not offered for any other source.

Moving from HL7 v2 to FHIR? An HL7 v2 item names the FHIR resource each segment maps to; see
[Migrate to FHIR](../bring-in/hl7v2-import.md#migrate-to-fhir).

#### Healthcare exports at a glance

| | FHIR | HL7 v2 segment guide | HL7 v2 |
| --- | --- | --- | --- |
| **From** | Any source | Any source with a record type | An item imported from HL7 v2 |
| **You get** | A `collection` Bundle, or one JSON file per resource | JSON guide, segment CSV, Markdown guide | The HL7 v2 message |
| **Options** | `fhir_version` (`R4`, `R5`), `packaging`, `capability_statement` | `message_type`, `version`, `first_table_number` … | — |
| **Enums become** | A CodeSystem and a ValueSet, with a `required` binding | A user-defined table (`9001` …) | — |
| **Operations** | Summarized in a CapabilityStatement | Left out (types-only) | Left out (types-only) |
| **Checked by** | The HL7 FHIR validator, else Apiome's structural FHIR rules | Apiome's guide rules | Apiome's HL7 v2 parser |
| **CLI** | `apiome export fhir` | `apiome export hl7guide` | `apiome export hl7v2` |

Every length, code, name and identifier an export invents is listed in its fidelity report before you
download.

### FHIR (StructureDefinition) from any source

Exporting to **FHIR** writes each cataloged type as a FHIR **StructureDefinition logical model**
(`kind: logical`), with a **CodeSystem** and **ValueSet** for each enum, in one `collection` Bundle.
Set **fhir_version** to `R4` (4.0.1, the default) or `R5` (5.0.0). Set **packaging** to `per-type` for
one JSON file per resource.

Each export is checked before you download it:

- **With the official HL7 FHIR validator**, when the server has it. Every file is validated against the
  version the export declares (R4 `4.0.1` or R5 `5.0.0`), offline (no terminology server). Each
  `error` or `fatal` issue fails the export and is listed with the validator's own message, the
  resource path and its code (`invariant`, `structure`, `code-invalid`). Warnings do not fail it.
- **Without it**, Apiome's structural FHIR rules check each file and list each broken rule on its own
  with its resource path (`fhir.structure`), then the FHIR reader reads it back (`fhir.reimport`).

**Where to find it.** In **Export studio**, the **FHIR** and **HL7 v2** cards are under
**Healthcare** on the **Target** step. From the CLI, run
`apiome export fhir <item> --option fhir_version=R5 --option packaging=per-type` or
`apiome export hl7v2 <item>`; `apiome export targets --project <item>` lists both. A public item's
**Export** dialog on Browse offers the same two targets.

- **Elements.** Each field is an element. An object used by only one field is nested in its
  parent as a `BackboneElement` (`Pet.owner.name`), and the `explicit-type-name` extension keeps
  its type name. Any other object is a logical model of its own, referenced by its canonical URL
  (`http://example.org/fhir/StructureDefinition/Owner`; set **canonical_base** to use your own).
- **Cardinality.** A field that may not be null has `min` 1, and a list has `max` `*`. `minItems`
  and `maxItems` set the bounds.
- **Types.** FHIR primitives: `string`, `boolean`, `integer`, `decimal`, `date`, `dateTime`, `time`,
  `uri`, `uuid` and `base64Binary`. A 64-bit integer is `integer64` in R5. R4 has no `integer64`,
  so it is written as `integer`, and the report says so.
- **Enums.** Each enum becomes a CodeSystem with one concept per value, plus a ValueSet that
  includes it. The field is a `code` with a `required` binding to that ValueSet.
- **Constraints.** `maxLength`, `minValue[x]` and `maxValue[x]`, and `defaultValue[x]` are written
  as element properties. Patterns, minimum lengths, exclusive bounds, `multipleOf` and allowed
  values become FHIRPath `constraint`s, such as `matches('^[A-Z]+$')`.
- **Unions.** A union whose alternatives are distinct single types (primitives, other models, at
  most one enum) becomes a FHIR **choice element**: a field `value` of that union is written
  `value[x]`, with one type per alternative. Any other union, such as one with two alternatives of
  the same type or a list of the union, becomes a model with one optional element per
  alternative, plus an invariant that exactly one is present.
- **Operations.** FHIR cannot declare operations on logical models. The **capability_statement**
  option (on by default) lists the source's operations in a CapabilityStatement's REST
  documentation, which also carries the title, description and version.
- **From a FHIR item.** An item imported from a FHIR profile or resource is written back in that
  form. An exported logical-model Bundle imports back unchanged.

The fidelity report lists what FHIR logical models cannot express, construct by construct:

| Source construct | In the report |
| --- | --- |
| Operations | Approximated: they are summarized in the CapabilityStatement, and the report warns that the source has operations. Without the CapabilityStatement they are dropped |
| A union of distinct single alternatives | Approximated: a choice element (`[x]`); the alternatives' names are not kept |
| Any other union | Dropped as a type: a model of optional elements with an exactly-one invariant |
| A map, and every field typed by one | Dropped |
| A regular expression, or an `email`, `hostname`, `ipv4` or `ipv6` format | Approximated: a FHIRPath `matches()` constraint, whose regex dialect may differ |
| Another format, `uniqueItems`, a default that does not fit | Dropped |
| A type that contains itself | Approximated: it is modelled by reference, and FHIR tools expand it only to a limited depth |
| A name that is not a FHIR name (`order-line`, `unit-price`) | Synthesized: `OrderLine`, `unitPrice` |
| Event operations, channels, servers | Dropped |
| Aliases, named scalars, coerced primitives | Approximated |

### OData (CSDL) from any source

#### When to export to OData

- **Describe an API as an OData service.** Any REST, RPC, GraphQL, JSON Schema or WSDL item becomes
  CSDL metadata: its resources become entity types with keys and entity sets, and every other
  operation a Function or Action. Keys Apiome had to infer or add, and what CSDL's type system
  cannot hold, are listed in the fidelity report before you download.
- **Round-trip an OData item.** An item imported from OData exports back **lossless**; an OData 2 or
  3 item is written as CSDL 4.01.

#### OData export at a glance

| Step | Where | Details |
| --- | --- | --- |
| **Pick** the OData card and its output (CSDL JSON, XML or both) | **Export** dialog → **REST & HTTP** → **OData** | [Where to find the OData card](#where-to-find-the-odata-card) |
| **See** how types, keys, properties and operations are written | The fidelity report on the card | [How the item is written](#how-the-item-is-written-to-odata) |
| **See** what is approximated, synthesized or dropped | The fidelity report on the card | [What the fidelity report lists](#what-the-odata-fidelity-report-lists) |
| **Trust** the file: OASIS schema, references and keys, re-import | Automatic before every download | [How an OData export is checked](#how-an-odata-export-is-checked) |
| **Export** from the CLI | `apiome export odata <item> --out <file>.csdl.json` | [Where to find the OData card](#where-to-find-the-odata-card) |

Exporting to **OData** writes the service's metadata as **CSDL JSON 4.01** (`<Namespace>.csdl.json`),
the canonical form. Set the **output** option to `xml` for CSDL XML (`<Namespace>.edmx`), or `both`
for the two.

#### How an OData export is checked {#how-an-odata-export-is-checked}

Each export is checked before you download it, with the same checks an OData import runs:

1. The OASIS **CSDL JSON** schema, or for CSDL XML the OASIS **EDMX / EDM** XML schemas. Each
   violation is listed on its own, with the JSON pointer where it is (`/Demo/Product/ID/$Type`).
2. **References and keys.** Every `$Type`, base type, entity set and navigation target must name a
   declared element, and every `$Key` property must exist. A schema accepts
   `"$Type": "Demo.Missing"`; this check does not.
3. The document imports again. With `both`, the two documents must describe the same model.

A failed check names the file, the pointer and the rule (`odata.csdl-schema`,
`odata.csdl-xml-schema`, `odata.unresolved-reference`, `odata.key`, `odata.outputs-disagree`,
`odata.reimport`). An item imported from OData exports and re-imports as it was read; its types are
written in one namespace, and every reference is re-qualified to match.

#### How the item is written {#how-the-item-is-written-to-odata}

- **Entity and complex types.** An object an HTTP operation sends or returns is a resource and
  becomes an `EntityType` with an entity set. Any other object becomes a `ComplexType`. An item
  with no operations (a data schema) exposes each object that no other object contains. An item
  imported from OData keeps its own entity types, complex types and entity sets.
- **Keys.** Every entity type has a `$Key`. An OData item keeps its own key. Otherwise a property
  named `id`, `<Type>Id` or `key` becomes the key, and the report says it was inferred. With no such
  property, a string `Id` property is added as the key, and the report says it was synthesized.
- **Types.** Primitives become their CSDL type: `int64` is `Edm.Int64`, `date-time` is
  `Edm.DateTimeOffset`, and `uuid` is `Edm.Guid`. An unsigned type is widened (`uint32` is
  `Edm.Int64`), and an unknown one is `Edm.String`; the report lists both. Enums become `EnumType`s,
  and a named scalar becomes a `TypeDefinition`. Unions become complex types with one nullable
  property per variant, and maps become open complex types; the report lists both.
- **Properties.** Lists become `$Collection`, and a property whose type is an entity becomes a
  `NavigationProperty`. `maxLength` becomes `$MaxLength` and a default `$DefaultValue`. Patterns,
  ranges, list sizes and allowed values become `Validation` annotations, descriptions
  `Core.Description`, and deprecations `Core.Revisions`.
- **Operations.** An entity set serves the CRUD operations on its resource: `GET /pets`,
  `GET /pets/{id}`, `POST /pets`, and `PUT`, `PATCH` and `DELETE /pets/{id}`. Every other operation
  becomes an unbound **Function** (a `GET` or query that returns a result) or **Action**, imported
  into the entity container. Its path and query parameters and its body become the operation's
  parameters.
- **From an OData 2 or 3 item.** It is written as CSDL 4.01. `MaxLength`, `Precision` and `Scale`
  stay facets, and `Edm.DateTime` becomes `Edm.DateTimeOffset`. The report lists the version
  upgrade and the `sap:` and `m:` annotations, which are not written.

#### What the fidelity report lists {#what-the-odata-fidelity-report-lists}

The fidelity report lists what OData cannot carry, in three groups:

| Group | Source construct | In the report |
| --- | --- | --- |
| Keyless types | An entity with an `id`-like property but no declared key | Approximated: the property becomes the key, and is made non-nullable if it was nullable |
| Keyless types | An entity with no key and no `id`-like property | Synthesized: a string `Id` key is added |
| RPC and events | A unary RPC or a GraphQL query or mutation | Approximated: it becomes an Action, or a Function when it is a query that returns a result |
| RPC and events | A gRPC client or bidirectional stream, a GraphQL subscription | Dropped (critical): it is not written |
| RPC and events | A gRPC server stream | Approximated: it returns a collection of its messages |
| RPC and events | Publish and subscribe operations, channels | Dropped |
| Type coercion | An unsigned or unknown primitive | Approximated: it is widened, or written as `Edm.String` |
| Type coercion | A `format` with no CSDL type, such as `email` or `uri` | Dropped |
| Type coercion | `minLength`, `multipleOf`, `uniqueItems` | Dropped |
| Type coercion | Field numbers (Protobuf, Thrift) | Dropped (info). An OData item's properties keep their order, so they are not listed |

Also dropped: header and cookie parameters, declared error responses (OData uses its standard
error format), defaults that do not fit, servers, and the document's title, description and
version. Also approximated: CRUD operations served by an entity set (their query parameters become
OData query options such as `$top` and `$filter`), unions, maps, aliases and renamed elements.

#### Where to find the OData card {#where-to-find-the-odata-card}

In the **Export** dialog, the **OData** card is under **REST & HTTP** on the
**Target** step, as one file. Its badge is **lossy** for a REST, RPC, GraphQL, JSON Schema or WSDL
source and **lossless** for an item imported from OData. Pick the card to see its two options:
**Output** (`json` by default; `xml` or `both`) and **Include Comments** (on by default), which writes
the comment header in the CSDL XML document. From the CLI, run
`apiome export odata <item> --out <file>.csdl.json`, and add `--option output=xml` or
`--option include_comments=false`. A lossy export exits non-zero unless you add `--force`, and `--json`
prints the tier. A public item's **Export** dialog on Browse offers OData too: the `.csdl.json` file,
or with `both` a zip of the two documents.

### OpenRPC from any source

#### When to export to OpenRPC

- **Describe an API as JSON-RPC 2.0.** A gRPC, REST, GraphQL or event item becomes an OpenRPC
  document of methods and notifications, the description format of the JSON-RPC ecosystem (Ethereum,
  MetaMask, Filecoin, Starknet). REST operations are reframed as methods with by-name `params`, and
  publish and subscribe operations as notifications. What JSON-RPC cannot carry is listed in the
  fidelity report before you download.
- **Round-trip an OpenRPC item.** An item imported from OpenRPC exports **lossless** and re-imports
  unchanged.

#### OpenRPC export at a glance

| Step | Where | Details |
| --- | --- | --- |
| **Pick** the OpenRPC card (one option: `indent`, set from the CLI or the API) | **Export** dialog → **OpenRPC** (under **RPC**) | [Where to find the OpenRPC card](#where-to-find-the-openrpc-card) |
| **See** how the document, methods, notifications, REST operations, events and schemas are written | The fidelity report on the card | [How the item is written](#how-the-item-is-written-to-openrpc) |
| **See** what OpenRPC cannot carry | The fidelity report on the card | [What the fidelity report lists](#what-the-openrpc-fidelity-report-lists) |
| **Trust** the document: the meta-schema, `$ref` resolution, then re-import | Automatic before every download | [How an OpenRPC export is checked](#how-an-openrpc-export-is-checked) |
| **Export** from the CLI | `apiome export openrpc <item> --out <file>.openrpc.json` | [Where to find the OpenRPC card](#where-to-find-the-openrpc-card) |

Exporting to **OpenRPC** writes an `openrpc.json` document that is valid against the OpenRPC
meta-schema.

#### How an OpenRPC export is checked {#how-an-openrpc-export-is-checked}

Each export is checked before it is offered:

1. It is validated against the OpenRPC meta-schema. Each violation is listed on its own, with the
   JSON pointer where it is (`/methods/0/params`).
2. Every `$ref` must name something in the document: a reference to a missing
   `#/components/schemas/…` fails, though the meta-schema alone would accept it.
3. It is imported again by the OpenRPC importer.

A failed check names the rule (`openrpc.meta-schema`, `openrpc.unresolved-ref`, `openrpc.reimport`).
An item imported from OpenRPC exports and re-imports unchanged.

#### How the item is written {#how-the-item-is-written-to-openrpc}

- **Document.** `info` carries the title, version and description. OpenRPC requires a version, so
  an item without one gets `0.0.0`, and the report says so. Servers keep their name, description
  and variables. An item imported from OpenRPC keeps its own `openrpc` version.
- **Methods.** Each operation becomes a method named after the operation. When two services have
  an operation with the same name, the second is written `<Service>.<operation>`. The request
  becomes `params`: an OpenRPC item keeps its own parameter list, and another RPC item gets one
  `params` parameter holding its request type. The response becomes `result`, error responses
  `errors` (`code`, `message` and `data`), tags `tags`, and a deprecated operation gets
  `deprecated: true`.
- **Notifications.** A one-way operation is written as a notification: a method with no `result`.
  An item imported from OpenRPC reads its result-less methods back as notifications.
- **From a REST source.** Each REST operation is reframed as a method, and the report lists each
  one:
  - its path, query, header and cookie parameters and its body become by-name `params`
    (`paramStructure: by-name`), each labeled with where it came from;
  - the success response becomes `result`, and a response with no body is `{"type": "null"}`;
  - numeric error statuses become `errors` with the status as the `code`;
  - the HTTP method and path are kept in the extension `x-http`.
- **Events.** A publish or subscribe operation (from AsyncAPI, for example) becomes a notification.
  Its message and its channel's address parameters become by-name `params`, and the channel address
  is kept in the extension `x-channel`.
- **Schemas.** Named types become `components/schemas`, written with the same JSON Schema mapping
  as the OpenAPI export. Every `$ref` names a written component, and scalars such as `int64` or
  `timestamp` become their JSON Schema form (`{"type": "integer", "format": "int64"}`).

#### What the fidelity report lists {#what-the-openrpc-fidelity-report-lists}

The fidelity report lists what OpenRPC cannot carry. JSON-RPC 2.0 has no HTTP semantics, no
streams and no channels, so each loss of a REST, gRPC or event item is listed on its own:

| Source construct | In the report | Why |
| --- | --- | --- |
| HTTP method and path | Dropped | A method has a name only. `x-http` keeps them, but JSON-RPC clients ignore it. |
| Path, query, header and cookie parameters | Approximated | They become by-name `params`, and each one's description names where it came from. |
| A success status other than 200, such as `201` | Dropped | A result has no status. |
| Error statuses such as `404` | Approximated | They become error codes with the same number. |
| `default` and `4XX` error responses | Dropped | An error needs an integer code. |
| Response headers | Dropped | A result has no headers. |
| gRPC streams, GraphQL subscriptions | Dropped | A JSON-RPC call is one request and one response. |
| Publish and subscribe operations | Approximated | They become notifications. |
| A channel used by an operation | Approximated | Its address is the notification's `x-channel`. |
| A channel no operation uses | Dropped | Nothing carries it. |
| Field numbers (Protobuf, Thrift) | Dropped (info) | JSON Schema properties have no numbers. |

Also dropped: a second success response (a method has one `result`), error payload types (an
OpenRPC error carries a `data` value, not a schema) and repeated field names. Also approximated: a
synthesized version, renamed methods and components, and types with no JSON Schema form (written as
any value).
- **Carried.** For each operation that is carried, the report names the method or notification it
  became, such as `method getPet`.

#### Where to find the OpenRPC card {#where-to-find-the-openrpc-card}

In the **Export** dialog, the **OpenRPC** card is under **RPC** on the **Target**
step, as one `<Name>.openrpc.json` file. Its badge is **lossless** for an item imported from OpenRPC and
**lossy**, with the share it keeps, for an item of any other paradigm: REST (OpenAPI, WSDL, RAML), RPC
(Thrift, Smithy), GraphQL or a data schema. Its one option, **indent** (`2` by default; `0` for compact
JSON), is a number, so the card has no options panel; set it from the CLI or the REST API. From the
CLI, run `apiome export openrpc <item> --out <file>.openrpc.json`, and add `--option indent=0`. The
CLI prints the fidelity report: the tier and preserved share, the counts, and the worst losses first.
A lossy export exits non-zero unless you add `--force`, and `--json` prints the tier. A public item's
**Export** dialog on Browse offers OpenRPC too, as the `.openrpc.json` file.

### Cap'n Proto from any source

#### When to export to Cap'n Proto

- **Move an API to Cap'n Proto.** Any item becomes a `.capnp` schema of structs, enums, unions and
  interfaces that `capnp compile` accepts, for a Cap'n Proto RPC service and its messages.
  What Cap'n Proto cannot carry is listed in the fidelity report before you download.
- **Keep readers compatible across exports.** Apiome stores each field number and the file's `@0x…`
  id, so every later export writes the same ones, and a removed field keeps its slot as
  `obsolete<Name>`.
- **Round-trip a Cap'n Proto item.** An item imported from Cap'n Proto exports **lossless**, with its
  own numbers and file id.

#### Cap'n Proto export at a glance

| Step | Where | Details |
| --- | --- | --- |
| **Pick** the Cap'n Proto card and its option (comments) | **Export** dialog → **Cap'n Proto** (under **RPC**) | [Where to find the Cap'n Proto card](#where-to-find-the-capn-proto-card) |
| **See** how types, services, names, numbers and constraints are written | The fidelity report on the card | [How the item is written](#how-the-item-is-written-to-capn-proto) |
| **See** what Cap'n Proto cannot carry | The fidelity report on the card | [What the fidelity report lists](#what-the-capn-proto-fidelity-report-lists) |
| **Trust** the schema: `capnp compile` | Automatic before every download, when the server has the compiler | [How a Cap'n Proto export is checked](#how-a-capn-proto-export-is-checked) |
| **Export** from the CLI | `apiome export capnp <item> --out <file>.capnp` | [Where to find the Cap'n Proto card](#where-to-find-the-capn-proto-card) |

#### How the item is written {#how-the-item-is-written-to-capn-proto}

Exporting to **Cap'n Proto** writes a `.capnp` schema that compiles with `capnp compile`, whatever
the item was imported from:

- **Types.** An object becomes a `struct`, an enumeration an `enum`, a `oneOf` (or another union) a
  `struct` holding a `union` of its variants, a map a `struct` with a list of `key`/`value` entries,
  and a list `List(T)`. Scalars map as for Protobuf, with Cap'n Proto's own names: `integer` is
  `Int32` (`Int64` with `format: int64`), `number` is `Float64`, `string` is `Text`.
- **Services.** Each service becomes an `interface`, and each operation a method. Its path, query and
  header parameters and its request body are the method's parameters, and its response body is the
  result.
- **Names.** Cap'n Proto wants type names that start with a capital letter and other names in
  camelCase with no underscore, so `first_name` is written `firstName` and `STATUS_ACTIVE` is
  `statusActive`.
- **Numbers.** Fields, enum values and methods are numbered `@0`, `@1`, `@2` in the order the source
  lists them, and the file gets its own `@0x…` id. Apiome remembers both for the item, so every later
  export writes the same numbers and the same file id. A field added since gets the next number.
  Cap'n Proto cannot leave a gap or drop a field, so a field removed from the source stays in the
  schema as `obsolete<Name>`, keeping its number and its size. The fidelity report lists every number
  Apiome assigned as *synthesized*. A Cap'n Proto import keeps its own numbers and file id.
- **Constraints.** Cap'n Proto has no validation rules, so a field's constraints are written as a
  comment just above it (`# constraints: >= 1; <= 100`). Nothing checks them. With
  **include_comments** off they are left out.

#### What the fidelity report lists {#what-the-capn-proto-fidelity-report-lists}

The fidelity report lists, on each operation, type and field, what the schema changed:

| In the source | In the report |
| --- | --- |
| An operation (not from a Cap'n Proto import) | Approximated (warning): an interface method; its HTTP method, path and parameter locations are not kept |
| An operation's error responses | Dropped (warning): Cap'n Proto methods declare no errors |
| An event operation, a channel | Dropped |
| Constraints | Approximated (warning): a comment nothing checks. Dropped with comments off |
| A map | Approximated (warning): a list of key/value entries |
| A field, enum value or method with no Cap'n Proto number; the file id | Synthesized (note) |
| A name that breaks Cap'n Proto's rules | Approximated (note), naming the new name |

#### How a Cap'n Proto export is checked {#how-a-capn-proto-export-is-checked}

When the server has the Cap'n Proto compiler, every export is compiled before it is delivered. A
schema that does not compile fails the export, and the check lists each compiler error with its file,
line and column. A schema that imports other `.capnp` files is not compiled on its own.

#### Where to find the Cap'n Proto card {#where-to-find-the-capn-proto-card}

In the **Export** dialog, the **Cap'n Proto** card is under **RPC** on the
**Target** step, as one `.capnp` file. Its badge is **lossless** for an item imported from Cap'n Proto
and **lossy** for any other source. Pick the card to see **Include Comments** (on by default). The
numbers and file id Apiome stored for the item are reused on every export, so a field you remove keeps
its number as an `obsolete…` placeholder and the next export keeps the same `@0x…` file id. From the
CLI, run `apiome export capnp <item> --out <file>.capnp` (`capnproto` works too). A lossy export exits
non-zero unless you add `--force`, and `--json` prints the tier. A public item's **Export** dialog on
Browse offers Cap'n Proto too, as the `.capnp` file.

### FlatBuffers from any source

#### When to export to FlatBuffers

- **Hand the data types to a FlatBuffers reader.** Any item becomes one `.fbs` schema of tables,
  structs, enums and unions that `flatc` compiles, for games, embedded devices and robotics.
  Operations and channels are left out, and the card says so (**types-only**).
- **Keep readers compatible across exports.** Apiome stores each field id, so every later export
  writes the same ids, and a removed field keeps its slot as `(deprecated)`.
- **Round-trip a FlatBuffers item.** An item imported from FlatBuffers exports **lossless**, with its
  own ids, deprecated slots and `root_type`.

#### FlatBuffers export at a glance

| Step | Where | Details |
| --- | --- | --- |
| **Pick** the FlatBuffers card and its options (root type, comments) | **Export** dialog → **FlatBuffers** (under **Data schema & graph**) | [Options](#flatbuffers-export-options) · [Where to find the FlatBuffers card](#where-to-find-the-flatbuffers-card) |
| **See** how types, scalars, defaults, names and constraints are written | The fidelity report on the card | [How the item is written](#how-the-item-is-written-to-flatbuffers) |
| **See** how field ids are kept from one export to the next | — | [Field ids](#flatbuffers-field-ids) |
| **See** what FlatBuffers cannot carry | The fidelity report on the card | [What the fidelity report lists](#what-the-flatbuffers-fidelity-report-lists) |
| **Trust** the schema: `flatc`, or a re-import without it | Automatic before every download | [How a FlatBuffers export is checked](#how-a-flatbuffers-export-is-checked) |
| **Export** from the CLI | `apiome export flatbuffers <item> --out <file>.fbs` | [Where to find the FlatBuffers card](#where-to-find-the-flatbuffers-card) |

#### How the item is written {#how-the-item-is-written-to-flatbuffers}

Exporting to **FlatBuffers** writes one `<Name>.fbs` schema that compiles with `flatc`, whatever the
item was imported from — for games, embedded devices and robotics. Operations and channels are left
out: a FlatBuffers schema describes data only.

- **Types.** An object becomes a `table`, an enumeration an `enum`, a `oneOf` (or another union) a
  `union`, and a list a vector `[T]`. An object imported from a FlatBuffers `struct` stays a `struct`
  when all its fields fit one (numbers, enums and other structs). An enum gets the smallest integer type
  its values fit (`enum Status : byte`) and lists them in ascending order.
- **Scalars.** Sized integers keep their width (`int32` is `int`, `uint8` is `ubyte`), an unsized
  `integer` is `long`, `number` is `double`, text and timestamps are `string`, and bytes are `[ubyte]`.
  FlatBuffers has no typedef, so an alias is written as the type it stands for.
- **What FlatBuffers cannot hold directly** gets a small table of its own, listed in the fidelity
  report: a map becomes a vector of `<Map>Entry` tables with a `key` (marked `(key)`, so a reader can
  look entries up) and a `value`; a list of lists becomes a vector of `<Name>Item` tables; a union
  member that is not a table (a `string`, say) is wrapped in `<Union><Member>`.
- **Required and defaults.** A required text, bytes, list or object field is marked `(required)`. A
  number, boolean or enum default is written as `= value`; an enum field with no default gets the
  enum's first value when `0` is not one of its values, because FlatBuffers would otherwise default it
  to `0`.
- **Names.** Names use letters, digits and underscores and are not FlatBuffers keywords: `order-id`
  is written `order_id` and a field named `string` is `string_`. Each rename is in the fidelity report.
- **Constraints.** FlatBuffers has no validation rules, so a field's constraints are written as a
  comment just above it (`// constraints: max length 12; pattern ^[A-Z]+$`). Nothing checks them.
  With **include_comments** off they are left out.

#### Field ids {#flatbuffers-field-ids}

Every table field is written with its id, `(id: N)`, in id order — the id is what a
reader matches a field by. Ids start at `0`, and a union field takes two (its hidden `<name>_type`
field and its value). Apiome remembers the ids it assigned for the item, so every later export writes
the same ids and an unchanged item exports byte for byte the same. A field added since gets the next
free id. A field removed from the source keeps its id as a `(deprecated)` placeholder, so readers built
from the earlier schema still read the other fields correctly. A FlatBuffers import keeps its own ids
and deprecated slots.

#### Options {#flatbuffers-export-options}

- **root_type** — the table a buffer starts with, by type name (`Order`) or key. By default it is the
  imported schema's `root_type`, and none for other sources. Naming a type that is not a table is
  refused.
- **include_comments** — on by default; descriptions are written as `///` comments.

#### What the fidelity report lists {#what-the-flatbuffers-fidelity-report-lists}

The fidelity report lists, on each type and field, what the schema changed:

| In the source | In the report |
| --- | --- |
| Operations, services and channels | Dropped (critical). An item that has any also gets a **types-only** warning counting them — export it to OpenAPI or AsyncAPI as well to keep them |
| Constraints | Approximated (warning): a comment nothing checks. Dropped with comments off |
| A map | Approximated (warning): a vector of `<Map>Entry` key/value tables |
| A field with no FlatBuffers id | Synthesized (note), naming the id |
| A wrapper table for a list of lists or a union member | Synthesized (note) |
| An alias, a struct written as a table, a renamed name | Approximated (note) |
| A default FlatBuffers cannot hold, a field whose type holds no value | Dropped |

A FlatBuffers import keeps its own ids, so its report lists no synthesized id.

#### How a FlatBuffers export is checked {#how-a-flatbuffers-export-is-checked}

When the server has the FlatBuffers compiler, every export is compiled with `flatc` before it is
delivered. A schema that does not compile fails the export, and the check lists each compiler error
with its file, line and column. Without the compiler, the export is read back with Apiome's FlatBuffers
importer. A schema that includes other `.fbs` files is not compiled on its own.

#### Where to find the FlatBuffers card {#where-to-find-the-flatbuffers-card}

In the **Export** dialog, the **FlatBuffers** card is under **Data schema &
graph** on the **Target** step, as one `.fbs` file. Its badge is **lossless** for an item imported from
FlatBuffers and **types-only** for any other source (FlatBuffers keeps the tables and leaves out the
operations). Pick the card to see **Include Comments** (on by default) and **Root Type** (the table
`root_type` names; empty picks one). From the CLI, run `apiome export flatbuffers <item> --out <file>.fbs`
(`fbs` works too), and add `--option root_type=Pet`. A types-only export exits non-zero unless you add
`--force`, and `--json` prints the tier. A public item's **Export** dialog on Browse offers FlatBuffers
too, as the `.fbs` file.

### COBOL copybook from any source

Exporting to **COBOL Copybook** writes the item's data types as copybook record layouts, `<Name>.cpy`,
for z/OS Connect, CICS and IMS programs. An item imported from a copybook is written back exactly as
it was imported — its pictures, usages, tables and `REDEFINES` — and the options below do not change it.

#### When to export to a COBOL copybook

- **Hand a record layout to a mainframe program.** Any REST, RPC, JSON Schema or other item becomes
  fixed-width `01` records for z/OS Connect, CICS, IMS or batch COBOL. Lengths, table sizes and names are
  synthesized where the source does not say, operations are left out, and the card says **types-only**.
- **Round-trip a copybook.** An item imported from a copybook exports back **lossless**, with its own
  pictures, usages, tables and `REDEFINES`.
- **Serve a PL/I program.** The same record layout as PL/I `DECLARE` structures, with **mode** `pli`.

#### COBOL copybook export at a glance

| Step | Where | Details |
| --- | --- | --- |
| **Pick** the COBOL Copybook card and its options (numeric usage, format, mode) | **Export** dialog → **Data schema & graph** → **COBOL Copybook** | Below, *Where to find it* |
| **See** how records, names, text, numbers, lists and unions are laid out | The fidelity report on the card | The list below |
| **See** everything the layout had to invent or change, field by field | The fidelity report on the card | The table below |
| **Write** PL/I include structures instead | **mode** `pli` | [PL/I include structure output](#pli-include-structure-output) |
| **Trust** the export: read back, and checked with cb2xml when the server has it | Automatic before every download | Below, *Checked with cb2xml* |
| **Export** from the CLI | `apiome export copybook <item> --out <Name>.cpy` | Below, *Where to find it* |
| **Download** from a public item | Browse → **Export** | Below, *Where to find it* |

Any other item is laid out like this:

- **Records.** Each object that no other object contains is an `01` record. Objects inside it are
  written inline as group items, with levels `05`, `10`, `15` … (a smaller step when a record nests too
  deep to stay within level 49). An object that contains itself is written once; the inner reference is
  left out and listed in the report. A model with no object is refused.
- **Names.** COBOL data names: `orderLineItems` and `order_line_items` are written `ORDER-LINE-ITEMS`,
  a reserved word gets `-X` (`STATUS-X`), and a name is cut to 30 characters. Every name is unique in the
  copybook — a clash gets `-2`, `-3` … within the 30 — so nothing needs `OF` to be referenced, and the
  same item always gets the same names.
- **Text** is `PIC X(n)`, `n` from `maxLength`. Dates are `PIC X(10)` (`YYYY-MM-DD`), times `X(15)`,
  timestamps `X(32)` and UUIDs `X(36)`. Other text gets the **default_string_length** (255), and the
  report lists each.
- **Numbers.** 16-, 32- and 64-bit integers are `PIC S9(4)`, `S9(9)` and `S9(18)` (`9(n)` when the
  minimum is 0 or more), binary (`COMP`). A decimal is packed, `PIC S9(p)V9(s) COMP-3`, with 18 digits in
  all and its scale from `multipleOf` (`0.01` is 2 places), else **decimal_scale**. A float is `COMP-1`
  or `COMP-2`.
- **Booleans and enumerations.** A boolean is a one-character flag with two condition names,
  `88 <NAME>-TRUE VALUE 'Y'` and `88 <NAME>-FALSE VALUE 'N'`. An enumeration is `PIC X(n)` (or a number)
  with one `88` level per value.
- **Lists.** A list of a fixed size is `OCCURS n TIMES`. Any other list is
  `OCCURS min TO max TIMES DEPENDING ON <NAME>-COUNT`, with the counter written just before it; `max` is
  `maxItems`, else **default_occurs** (10). A list inside another list is a fixed table of its maximum,
  because `DEPENDING ON` is not allowed there.
- **Unions** are written as items that share storage: each member after the largest one
  `REDEFINES` it. A union with a member holding a list that varies in size is left out, because COBOL
  cannot overlay an `OCCURS DEPENDING ON` table.
- **Rules a picture cannot hold** — a `pattern`, a `format` such as `email` — are written as comment lines
  just above the item (`* pattern: ^[A-Z]{3}$`).
- **Left out:** maps, operations and channels — a copybook describes record layouts only.

Options:

- **numeric_usage** — `comp` (default): binary integers, packed decimals and floats; `display`: every
  number zoned (`PIC S9(9)`, floats as decimals).
- **default_string_length**, **default_occurs**, **decimal_scale** — what is used when the source does
  not say (255, 10 and 2).
- **fixed_format** — on by default: code in columns 8–72, a long entry continued on the next line, and
  `*` comments in column 7. Turn it off for free format: no column limits and `*>` comments.
- **include_comments** — on by default; turn it off to leave out the header comment.

A copybook is fixed-width and positional, so the fidelity report lists — on each field, by its path in
the source — everything the layout had to invent or change, computed for the options you pick:

| In the source | In the report |
|---|---|
| Operations, services and channels | Dropped (critical). An item that has any also gets a **types-only** warning counting them — export it to OpenAPI or AsyncAPI as well to keep them |
| Text with no `maxLength` | Synthesized (warning): the default `PIC X(n)` |
| A list that varies in size | Synthesized (note): the `<NAME>-COUNT` counter. With no `maxItems`, also approximated (warning): the default maximum |
| A name changed to COBOL's rules (`order_id` → `ORDER-ID`) | Synthesized (note), naming the COBOL name |
| A union | Approximated (warning): `REDEFINES`. Dropped when a member varies in size |
| A `pattern`, a `format` | Approximated: a comment line, which nothing checks |
| An optional field | Approximated (note): a record has no null — the field is always present, and an absent value is written as spaces or zeros, a convention to agree with the record's readers |
| A list inside a list, a float with `display` usage, a type with no COBOL form | Approximated (warning) |
| A map, a record that contains itself, a field whose type holds no value | Dropped |
| A document of another format | Approximated (note): it reads back as a copybook item |

An item imported from a copybook is written back as it was, so its report lists nothing invented.

**Checked with cb2xml.** When the server has cb2xml, it parses every copybook export, the same way a
mainframe toolchain would read it. The export fails when:

- **cb2xml cannot parse it.** The check shows cb2xml's error message, and for a fixed-format copybook
  the line and column.
- **cb2xml reads a different layout.** The records and items, in order, must match the layout Apiome
  planned with your options: each item's level, name, `PIC`, usage, `OCCURS` (and `DEPENDING ON`),
  `REDEFINES` and `88` values. Each difference is listed at the item's path, such as
  `PURCHASE.LINES-X`. Spellings COBOL treats as the same pass: `X(3)` and `XXX`, `COMP` and `BINARY`,
  `COMP-3` and `PACKED-DECIMAL`.

cb2xml reads fixed format only, so a free-format export is laid out in columns 8–72 for the check;
an error in it then has no line number. Without cb2xml, the export is read back by Apiome's copybook
reader.

#### PL/I include structure output {#pli-include-structure-output}

PL/I programs read record layouts as `DECLARE` structures rather than copybooks. Set **mode** to `pli` to
write the same record layout as a PL/I include member, `<Name>.pli`: the same records and items, in the
same order, each taking the same bytes. Everything above about how an item is laid out (names, lengths,
tables, unions, the options) applies; only the declaration syntax changes:

| Copybook | PL/I |
| --- | --- |
| `01` / `05` / `10` … | Levels `1` / `2` / `3` … by depth |
| `CUST-ID`, `FILLER` | `CUST_ID`, `*` (an unnamed member) |
| `PIC X(n)`, `PIC A(n)` | `CHAR(n)` |
| `PIC N(n)` | `WIDECHAR(n)` |
| `PIC S9(p)V9(s) COMP-3` | `FIXED DEC(p+s,s)` |
| `PIC S9(4)`, `S9(9)`, `S9(18)` `COMP` | `FIXED BIN(15)`, `FIXED BIN(31)`, `FIXED BIN(63)` |
| `PIC S9(5)` (zoned) | `PIC'(4)9T'` — `T` is the sign overpunched on the last digit |
| `COMP-1`, `COMP-2` | `FLOAT DEC(6)`, `FLOAT DEC(16)` |
| `OCCURS 10 TIMES` | The dimension `(10)` |
| `OCCURS 0 TO 50 TIMES DEPENDING ON LINES-COUNT` | `(50 REFER(LINES_COUNT))`, in a `BASED` structure, as `REFER` requires |
| `B REDEFINES A` | `A` and `B` as members of a `UNION` |
| `88` condition names | A comment above the item: `/* values: GIFT_TRUE = 'Y', GIFT_FALSE = 'N' */` |

Every structure is declared `UNALIGNED`, so binary and float items are not moved to a word boundary and
the offsets are the copybook's. With **fixed_format** on (the default), the source stays within PL/I's
default margins, columns 2–72; off, each declaration is one line.

The fidelity report lists the same entries as for a copybook — on the same fields, with the same grades —
in PL/I terms (`CHAR(255)` for the default length, `REFER` for a counter, `UNION` for a union). A name that
only needed an underscore is not listed: PL/I keeps `CUSTOMER_NAME` where COBOL wrote `CUSTOMER-NAME`.
PL/I also lists what only it changes:

| In the copybook | In the report |
|---|---|
| `88` condition names | Approximated (note): a comment, which nothing checks |
| A data name with a hyphen (an item imported from a copybook) | Approximated (note), once: each hyphen is an underscore |
| `REDEFINES` beside other items | Synthesized (note): the overlay is wrapped in a `UNION` group, such as `PAYMENT_DETAIL_UNION`, a level the copybook does not have |
| A `REDEFINES` of an item that is not before it | Approximated (warning): written as an item of its own |
| An edited or mixed picture (`Z(5)9.99`) | Approximated (warning): `CHAR(n)` of the bytes it takes, with the picture in a comment |
| A binary number with decimal places (`S9(5)V99 COMP`) | Approximated (warning): `FIXED BIN`, with the decimal places in a comment |
| A `66` `RENAMES` item | Dropped (warning): it takes no storage of its own |

An item imported from a copybook is exported through its own layout in this mode too.

Each PL/I export is checked before you download it. Apiome's PL/I reader must parse it with no attribute
it does not know, and every record and item, in order, must take the bytes the copybook item does. Each
difference is a `pli.layout` finding, such as `PURCHASE.CUSTOMER_NAME takes 39 byte(s); the copybook item
PURCHASE.CUSTOMER-NAME takes 40.`

**Where to find it.** In the **Export** dialog, the **COBOL Copybook** card is under **Data schema &
graph** on the **Target** step. Its badge is computed for the item. Copybook is one of the lossiest
targets: anything that is not a copybook (a REST API, a gRPC service, a JSON Schema) is **types-only**,
with most of its layout synthesized, while an item imported from a copybook is **lossless**. Pick the
card to set **Numeric Usage**, **Fixed Format**, **Include Comments** and **Mode** (`copybook` by
default, or `pli`); the three defaults
(**default_string_length**, **default_occurs**, **decimal_scale**) are set from the CLI. Run
`apiome export copybook <item> --out <Name>.cpy` (`cobol` and `cobolcopybook` work too) and add
`--option numeric_usage=display`, `--option fixed_format=false`, `--option default_occurs=25` or
`--option mode=pli --out <Name>.pli`.
A types-only export exits non-zero unless you add `--force`; `--out -` writes the copybook to
standard output, and `--json` prints the file written and its tier as JSON. A public item's **Export**
dialog on Browse offers the same target.

### EDI and e-invoicing guides

Trading partners agree on the documents they exchange before they exchange any: which segments or elements a
purchase order or an invoice carries, how long each value is, which codes it may hold. Apiome writes that
agreement from an item's types, for the three families B2B partners use and for HL7 v2 healthcare interfaces. Each is a guide or schema partners
build their documents from, not a document itself.

#### When to use which

- **North American partners: X12.** Retail, logistics and healthcare in North America exchange X12
  transaction sets (`850` purchase order, `810` invoice, `837` claim). Export an
  [X12 implementation guide](#x12-implementation-guide-from-any-source).
- **International partners: UN/EDIFACT.** Most other partners exchange UN/EDIFACT messages (`ORDERS`, `INVOIC`,
  `DESADV`). Export a [UN/EDIFACT message guide](#unedifact-message-guide-from-any-source). It is laid out by the
  same plan as the X12 guide, so an item's two guides list the same segments in the same order.
- **E-invoicing and XML business documents: UBL and Peppol.** EU e-invoicing runs on Peppol BIS Billing 3.0,
  whose invoices and credit notes are UBL 2.1 documents. Export **XSD** with the
  [UBL and Peppol BIS profiles](#ubl-and-peppol-bis-profiles) for a UBL document schema, validated against the
  official UBL 2.1 schemas it ships with.
- **Healthcare interface partners: HL7 v2.** Hospital interfaces exchange HL7 v2 messages (`ADT^A01`,
  `ORU^R01`). Export an [HL7 v2 segment guide](#hl7-v2-segment-guide-from-any-source) — the message and
  segment definitions an integration engine is configured from, laid out by the same plan as the X12 guide.

#### EDI and e-invoicing at a glance

| | X12 implementation guide | UN/EDIFACT message guide | UBL / Peppol (XSD profile) || HL7 v2 segment guide |
| --- | --- | --- | --- |--- |
| **Card** (**Data schema & graph**) | **X12 implementation guide** | **UN/EDIFACT message guide** | **XSD**, **Profile** `ubl` or `peppol` | **HL7 v2 segment guide** |
| **You get** | JSON guide, segment CSV, Markdown guide | JSON guide, segment CSV, Markdown guide | Document schema, the OASIS UBL 2.1 schemas, notice, guide | JSON guide, segment CSV, Markdown guide |
| **Pick the document** | **Transaction Set**, **Version** | **Message Type**, **Release** | **Ubl Document** (Peppol: `Invoice` or `CreditNote`) | **Message Type**, **Version** |
| **Units** | Segments and loops, X12 element types | Segments and segment groups, simple and composite data elements | UBL aggregates and data types, `cbc:` components | Z-segments and segment groups, HL7 data types and tables |
| **Checked by** | Apiome's guide rules, pyx12's dictionary when installed | Apiome's guide rules | An XML Schema processor against the UBL 2.1 schemas, the Peppol conventions | Apiome's guide rules |
| **CLI** | `apiome export x12` | `apiome export edifact` | `apiome export xsd --option profile=peppol` | `apiome export hl7guide` |

All four describe types only — operations and channels are left out — and every length, code and identifier
the guide invents is listed in the fidelity report.

### X12 implementation guide from any source

Exporting to **X12 implementation guide** describes the item's types as an X12 transaction set, for
onboarding trading partners. It is not an interchange: it is the guide partners build their
interchanges from. You get three files, downloaded together as a `.zip`:

- `<Name>.x12-guide.json` — the machine-readable guide: the transaction set, every segment with its
  elements, and the structure (positions, loops, usage and maximum use);
- `<Name>.x12-segments.csv` — the segment dictionary, one row per element, for spreadsheet tools;
- `<Name>.x12-guide.md` — the same guide for people to read.

How the types are laid out:

- **Segments.** Each object becomes a segment of its plain values, in field order. Its segment ID is
  made from its name — `PurchaseOrder` is `PUR`, `OrderLine` is `ORD` — unique in the guide and never
  an envelope ID (`ST`, `SE`, `GS` …). Elements are referred to by segment and position: `PUR01`,
  `PUR02` …
- **Loops.** An object inside another object follows it as a child segment. A list of objects is a loop
  that repeats up to `maxItems` (`>1` when there is no limit), and a list of plain values is a segment of
  one element, repeated. The item's top-level objects sit directly in the transaction set, between the
  `ST` header and the `SE` trailer, and positions number the whole structure `0100`, `0200` … (closer
  together when a guide has more than 98 segments, so a position always has four digits)
- **Usage.** A required field is mandatory (`M`), any other optional (`O`).
- **Notes.** A rule an element type cannot enforce — a `pattern`, a `format` such as `email`, a minimum or
  maximum, a set of allowed values — is written as a note on the element (in the JSON, the CSV and the
  Markdown guide).
- **Codes.** An enum value is used as a code when it is upper-case letters and digits no longer than
  **max_code_length** (3). Any other value gets a code made from it — `ON-HOLD` becomes `ONH` — and the
  guide shows the value next to it.
- **Left out:** unions and maps (a segment holds flat values only), an object that contains itself,
  operations and channels. Each is listed in the export's losses.

| In the source | In the guide |
|---|---|
| Text | `AN`, `maxLength` (or the **default_element_length**, 80) as its maximum; a UUID `AN` 36/36 |
| An enumeration, a boolean | `ID` with a code list — the enum's values, or `Y`/`N` |
| An integer | `N0`, as many digits as its width allows (3, 5, 10 or 18) |
| A decimal | `N2` (implied decimal places) when `multipleOf` gives its scale (`0.01`), else `R` |
| A float | `R` |
| A date | `DT` (`CCYYMMDD`) |
| A time | `TM` (`HHMM` to `HHMMSSDD`) |
| A timestamp | Two elements: its date (`DT`) and its time (`TM`) |

An item imported from X12 keeps its segment IDs, its element references and the order of its
interchange, and a position the sample left empty is marked *not used* (`X`).

Options:

- **transaction_set** — the set's 3-digit ID (`850`, `810`, `837` …). By default an imported X12
  item's own, else `850`.
- **version** — the 6-digit X12 version (`005010`, `004010` …). By default an imported X12 item's own,
  else `005010`.
- **default_element_length** — the maximum of a text element whose source has no `maxLength` (80).
- **max_code_length** — the longest enum value used as a code as it is (3).

A model with no object at all is refused: there is nothing to lay out.

X12 is the most constrained target, so its fidelity report lists every change on the field it came
from, computed for the options you pick:

| In the source | In the report |
|---|---|
| A union, a map, an object that contains itself, more than 99 values in one object | Dropped (**critical**) |
| Operations, services and channels | Dropped (**critical**), with a **types-only** warning counting them |
| Text with no `maxLength` | Synthesized (warning): the default element length |
| An enum value that is not a valid code | Synthesized (warning): the code made for it |
| A segment ID made from a name, a marker element for an object with no plain value | Synthesized (note) |
| A list of lists | Approximated (warning): flattened into one list |
| A rule kept only as a guide note | Approximated (warning) |
| A decimal with no known scale | Approximated (warning): `R`, so its precision is not fixed |
| A decimal with implied places (`N2`), a float (`R`), a timestamp split into date and time | Approximated (note) |

**Critical losses need confirming.** When a type would lose a union, a map or other values
outright, the export is a *severe* conversion: the Export dialog, `POST …/dispatch` and export jobs
ask you to confirm before they run, and the warning names each construct and why (in the guard's
`reasons`, and in full in `critical_details`). An item with operations is warned that only its schemas
export, and still lists those constructs.

**Checked before you download it.** A guide cannot be imported back, so every export is checked
instead. The export fails, and lists every problem with its file, its place in the guide (a JSON
pointer such as `/segments/2/elements/0`) and its rule, when:

1. **The JSON guide is not the guide format** (`x12-guide.schema`): a missing `transactionSet`,
   `version`, `segments` or `structure`, or a value of the wrong type.
2. **A segment or element is wrong**: a segment ID that is not 2–3 letters or digits, or is defined
   twice; element references that are not `<ID>01` upward with no gap; an unknown element type; lengths
   where `minLength` is above `maxLength`; usage other than `M`, `O` or `X`.
3. **The structure and the segments disagree**: the structure uses a segment that is not defined, or a
   segment is defined and never used; a loop does not start with its own segment; positions are not four
   digits in increasing order; the guide does not start with `ST` and end with `SE`.
4. **A code list is wrong**: an `ID` element with no codes, a code longer or shorter than the element,
   a code listed twice, codes on an element that is not `ID`, or `ST01` not listing the transaction set.
5. **The files disagree** (`x12-guide.files`): the `.csv` or `.md` file does not list exactly what the
   JSON guide says, or one of the three files is missing.
6. **The X12 dictionary disagrees** (`x12-guide.dictionary`): when the server has pyx12 and pyx12 has
   segment definitions for the guide's version (`005010`, `004010`), the `ST` and `SE` elements must
   have the standard types and lengths, and a segment carried from an imported X12 item must not have
   more elements than the standard segment. A segment Apiome made from a type is not compared with a
   standard segment that happens to share its ID. Without pyx12, or for another version, this check is
   skipped and the export says so; the other checks still run.

A `004010` guide's `ST` has two elements: `ST03` (implementation convention reference) exists from
`004020`.

**Where to find it.** In the **Export** dialog, the **X12 implementation guide** card is under **Data
schema & graph** on the **Target** step, marked multi-file. Its badge is **types-only** for every source,
an imported X12 item included: a guide invents the lengths, codes and segment IDs an interchange does
not state, and leaves operations out. Pick the card and type the **Transaction Set** (`850`, `810`,
`837` …) and **Version** (`005010`, `004010` …); leave them empty for the item's own, else `850` and
`005010`. From the CLI, run `apiome export x12 <item> --out <folder>` (the three files are unpacked into
the folder) and add `--option transaction_set=810` or `--option version=004010`. `apiome export x12`
writes the guide; the X12 interchange itself is `apiome export edix12`. A types-only export exits
non-zero unless you add `--force`, and `--json` prints the tier. A public item's **Export** dialog on
Browse offers the guide too, as a `.zip`. For trading partners who use UN/EDIFACT instead, see the
[UN/EDIFACT message guide](#unedifact-message-guide-from-any-source): the same layout in EDIFACT terms.

### UN/EDIFACT message guide from any source

International trading partners exchange UN/EDIFACT messages — `ORDERS`, `INVOIC`, `DESADV` — rather than
X12 transaction sets. Exporting to **UN/EDIFACT message guide** describes the item's types as one EDIFACT
message, for onboarding those partners. Like the X12 guide, it is the guide partners build their messages
from, not a message. You get three files, downloaded together as a `.zip`:

- `<Name>.edifact-guide.json` — the machine-readable guide: the message, every segment with its data
  elements, and the structure (positions, segment groups, status and maximum repetitions);
- `<Name>.edifact-segments.csv` — the segment directory, one row per data element and per component;
- `<Name>.edifact-guide.md` — the same guide for people to read.

**One layout for both guides.** The EDIFACT guide is laid out by the same plan as the
[X12 implementation guide](#x12-implementation-guide-from-any-source): the same segments, in the same
order, with the same values, the same loops (segment groups here) and the same usage and repetitions.
Only the spelling differs, so an item's two guides never disagree. Everything the X12 section says about
segments, loops, notes and codes applies; in EDIFACT terms:

- **Tags.** A segment's tag is three letters, made from its name (`PurchaseOrder` is `PUR`), and never a
  service tag — none starts with `U`. Data elements are referred to by tag and position: `PUR01`, `PUR02`
  …; a composite's components by `PUR02-1`, `PUR02-2` …
- **Segment groups.** A loop is a segment group, `SG1`, `SG2` … in order, started by its trigger segment.
  The message sits between the `UNH` header and the `UNT` trailer, and positions number the structure
  `0010`, `0020` …
- **Status.** A required field is mandatory (`M`), any other conditional (`C`); a position the item leaves
  empty is not used (`N`).
- **Repetitions.** Every repetition is a number: a list with no `maxItems` repeats at most
  **default_max_use** times (9999).
- **Codes.** An enum's values are the code list of a coded value (what EDIFACT calls a qualifier when it
  says what the next value means), with the same rule for values that are not valid codes as the X12 guide.

| In the source | In the guide |
|---|---|
| Text | `an..35` — `maxLength` (or the **default_element_length**, 35) as its maximum; `an36` for a UUID |
| An enumeration, a boolean | A coded value with its code list — the enum's values, or `Y`/`N` (`an2`, `an1` …) |
| An integer | `n..10`, as many digits as its width allows (3, 5, 10 or 18) |
| A decimal | `n..15` with its `decimals` count when `multipleOf` gives its scale: EDIFACT always sends the decimal mark |
| A float | `n..15` |
| A date | `n8`, format `102` (`CCYYMMDD`) |
| A time | `n..8` (`HHMM[SS]`) |
| A timestamp | One composite of two components, its date and its time |

`UNH02` identifies the message: its type, version `D`, release and agency `UN`.

An item imported from EDIFACT keeps its tags, the order of its segments, and its composites: `NAD02` is a
composite whose components are `NAD02-1`, `NAD02-2` … , and a component the sample left empty is not used.
An item imported from X12 keeps its segments and their order; a segment whose X12 ID is not a valid tag
(`N1`, `PO1`) gets a new one. A service segment the item carries (`UNS`) gets a new tag too.

Options:

- **message_type** — six letters (`ORDERS`, `INVOIC`, `DESADV` …). By default an imported EDIFACT item's
  own, else `ORDERS`.
- **release** — the directory release (`96A`, `01B` …; `D.01B` works too). By default an imported EDIFACT
  item's own, else `01B`.
- **default_element_length** — the maximum of a text value whose source has no `maxLength` (35).
- **max_code_length** — the longest enum value used as a code as it is (3).
- **default_max_use** — how often a segment or group from a list with no `maxItems` may repeat (9999).

The fidelity report lists the same entries as the X12 guide's, on the same fields and with the same
grades, in EDIFACT terms. One entry is the EDIFACT guide's own:

| In the source | In the report |
|---|---|
| A list with no `maxItems` | Synthesized (note): the default maximum repetitions |

**Checked before you download it.** As for the X12 guide, every export is checked instead of read back,
and fails — listing every problem with its file, JSON pointer and rule — when:

1. **The JSON guide is not the guide format** (`edifact-guide.schema`).
2. **A segment or data element is wrong**: a tag that is not three letters, or is a service tag
   (`edifact-guide.segment-tag`), or is defined twice; data element references that are not `<TAG>01`
   upward, or components that are not `<ref>-1` upward (`edifact-guide.element-ref`); a representation that
   is not `an` or `n` with a length, or does not match the lengths (`edifact-guide.representation`,
   `edifact-guide.lengths`); a status other than `M`, `C` or `N`.
3. **The message is wrong**: a message type that is not six letters, a release that is not a directory
   release (`edifact-guide.message`), or `UNH02` not naming them (`edifact-guide.envelope`).
4. **The structure and the segments disagree**: an undefined or unused segment, a segment group that does
   not start with its trigger or is numbered out of order (`edifact-guide.group`), positions not in
   increasing order, a repetition that is not a positive count, or a guide that does not start with `UNH`
   and end with `UNT`.
5. **A code list is wrong**: a code longer or shorter than its value, or listed twice.
6. **The files disagree** (`edifact-guide.files`): the `.csv` or `.md` file does not list exactly what the
   JSON guide says, or one of the three files is missing.

**Where to find it.** In the **Export** dialog, the **UN/EDIFACT message guide** card is under **Data
schema & graph** on the **Target** step, marked multi-file. Its badge is **types-only** for every source,
an imported EDIFACT item included. Pick the card and type the **Message Type** (`ORDERS`, `INVOIC` …) and
**Release** (`96A`, `01B` …); leave them empty for the item's own, else `ORDERS` and `01B`. From the CLI,
run `apiome export edifact <item> --out <folder>` and add `--option message_type=INVOIC` or
`--option release=96A`. A types-only export exits non-zero unless you add `--force`. A public item's
**Export** dialog on Browse offers the guide too, as a `.zip`.

### HL7 v2 segment guide from any source

Hospital integration engines — Mirth Connect, Rhapsody, Cloverleaf — are configured from HL7 v2 message and
segment definitions: which segments a message holds, in what order and how often, and each segment's fields.
Exporting to **HL7 v2 segment guide** writes that definition for the item's types, for onboarding an interface
partner. It is the guide partners build their messages from, not a message (to write an imported HL7 v2 message
back out, export to **HL7 v2**). You get three files, downloaded together as a `.zip`:

- `<Name>.hl7v2-guide.json` — the machine-readable definition: the message, every segment with its fields,
  the tables and the structure (segment groups, optionality and repetition);
- `<Name>.hl7v2-segments.csv` — the segment definitions, one row per field;
- `<Name>.hl7v2-guide.md` — the same guide for people to read, with the message's abstract message syntax
  (`MSH ZPU ZPA { ZOR } [ { ZNO } ]`: `[ ]` optional, `{ }` repeating).

**One layout for every guide.** The HL7 v2 guide is laid out by the same plan as the
[X12 implementation guide](#x12-implementation-guide-from-any-source) and the
[UN/EDIFACT message guide](#unedifact-message-guide-from-any-source): the same segments, in the same order,
holding the same values. Only the spelling differs; in HL7 v2 terms:

- **Segments.** A segment made from a type is a site-defined **Z-segment**, its ID made from its name
  (`PurchaseOrder` is `ZPU`). Its fields are `ZPU-1`, `ZPU-2` … in order.
- **The header.** The message starts with the standard `MSH` segment, with `MSH-9` the message type and
  `MSH-12` the version.
- **Segment groups.** A loop is a segment group named after its record (`ORDER_LINE`).
- **Optionality.** A required field or segment is `R`, any other `O`; a position the item leaves empty is
  not used (`X`).
- **Repetition.** `N` (once), `Y` (any number: a list with no `maxItems`) or the list's `maxItems`.
- **Tables.** Each enum is a **user-defined table**, numbered from **first_table_number** (`9001`, `9002` …),
  listing its codes and the values they stand for; the coded field names its table. An enum value longer
  than **max_code_length**, or not a valid code, gets a shorter code, with the value as its description.

| In the source | In the guide |
|---|---|
| Text | `ST` — `maxLength` (or the **default_field_length**, 199) as its length |
| An enumeration | `IS` (`CWE` from v2.7) bound to the enum's user-defined table |
| A boolean | `ID` bound to HL7 table `0136` (Yes/no indicator: `Y`, `N`) |
| An integer, a decimal, a float | `NM` — HL7 sends the decimal point |
| A date | `DT` (`YYYYMMDD`) |
| A time | `TM` (`HHMM[SS]`) |
| A timestamp | One `TS` field (`DTM` from v2.6), `YYYYMMDDHHMM[SS]` |

An item imported from HL7 v2 keeps its own segments (`MSH`, `PID`, `PV1` …), their order and their field
sequence (`PID-1`, `PID-2` …), and its own message type and version in `MSH-9` and `MSH-12` unless you pick
others.

Options:

- **message_type** — `<code>^<event>`, optionally with the message structure (`ADT^A01`, `ORU^R01`,
  `ORM^O01^ORM_O01`). By default an imported HL7 v2 item's own, else `ZZZ^Z01`, a site-defined message.
- **version** — the HL7 v2 version (`2.3`, `2.5.1`, `2.8` …). By default an imported HL7 v2 item's own,
  else `2.5.1`.
- **default_field_length** — the length of a text field whose source has no `maxLength` (199).
- **max_code_length** — the longest enum value used as a code as it is (20).
- **first_table_number** — the number of the first user-defined table (9001).

The fidelity report lists the same entries as the X12 guide's, on the same fields and with the same
grades, in HL7 v2 terms — a Z-segment ID made from a type's name is synthesized, and so on. One entry is the
HL7 v2 guide's own:

| In the source | In the report |
|---|---|
| An enumeration | Synthesized (note): the user-defined table number the export assigns |

**Checked before you download it.** As for the other guides, every export is checked instead of read back,
and fails — listing every problem with its file, JSON pointer and rule — when:

1. **The JSON guide is not the guide format** (`hl7v2-guide.schema`).
2. **A segment or field is wrong**: an ID that is not three letters or digits starting with a letter
   (`hl7v2-guide.segment-id`), or is defined twice (`hl7v2-guide.duplicate-segment`); fields that are not
   `<ID>-1` upward with no gap (`hl7v2-guide.field-ref`); an unknown data type (`hl7v2-guide.data-type`); a
   length that is not positive (`hl7v2-guide.length`); optionality other than `R`, `O` or `X`
   (`hl7v2-guide.optionality`); a repetition other than `N`, `Y` or a positive count
   (`hl7v2-guide.repetition`).
3. **The message is wrong**: a message type that is not `<code>^<event>`, a version that is not an HL7 v2
   version (`hl7v2-guide.message`), or a structure that does not start with `MSH`, or `MSH-9` and `MSH-12`
   not naming them (`hl7v2-guide.envelope`).
4. **A table is wrong** (`hl7v2-guide.table`): a coded field (`ID`, `IS`, `CWE`) with no table or one the
   guide does not define, a table no field uses, or a code listed twice or longer than its field.
5. **The structure and the segments disagree**: an undefined or unused segment
   (`hl7v2-guide.undefined-segment`, `hl7v2-guide.unused-segment`), or an unnamed or empty segment group
   (`hl7v2-guide.group`).
6. **The files disagree** (`hl7v2-guide.files`): the `.csv` or `.md` file does not list exactly what the
   JSON guide says, or one of the three files is missing.

**Where to find it.** In the **Export** dialog, pick the **HL7 v2 segment guide** card on the **Target**
step (in **Export studio** it is under **Healthcare**, with FHIR and HL7 v2), marked multi-file. Its badge is **types-only** for every source,
an imported HL7 v2 item included. Pick the card and type the **Message Type** (`ADT^A01`, `ORU^R01` …) and
**Version** (`2.5.1`, `2.8` …); leave them empty for the item's own, else `ZZZ^Z01` and `2.5.1`. From the CLI,
run `apiome export hl7guide <item> --out <folder>` and add `--option message_type=ORU^R01` or
`--option version=2.8`. A types-only export exits non-zero unless you add `--force`. A public item's
**Export** dialog on Browse offers the guide too, as a `.zip`.

### WSDL and XSD from any source

#### When to export to WSDL

- **Hand a SOAP description to a SOAP toolchain.** Any REST, RPC, GraphQL or JSON Schema item becomes
  a WS-I document/literal SOAP 1.1 service: one SOAP operation per operation, its types as XML Schema.
  The HTTP method and path, and what JSON says that XML Schema cannot, are listed in the fidelity
  report before you download.
- **Round-trip a WSDL.** An item imported from WSDL exports back **lossless**, with its own messages,
  parts, bindings and SOAP versions.
- **Hand a WSDL 2.0 description to a toolchain that reads 2.0.** Set **Wsdl Version** to `2.0` to get
  a W3C WSDL 2.0 `description` instead of a WSDL 1.1 one. An item imported from WSDL 2.0 round-trips
  unchanged; what a WSDL 1.1 item has that 2.0 cannot say is listed in the fidelity report.

#### WSDL export at a glance

| Step | Where | Details |
| --- | --- | --- |
| **Pick** the WSDL card and its layout (bundle or single file) | **Export** dialog → **REST & HTTP** → **WSDL** | [Where to find the WSDL card](#where-to-find-the-wsdl-card) |
| **Write** WSDL 2.0 instead of 1.1 | **Wsdl Version** `2.0` on the card | [WSDL 2.0](#wsdl-2-0-output) |
| **See** how types, rules, operations and names are written | The fidelity report on the card | [How the item is written](#how-the-item-is-written-to-wsdl) |
| **See** what XML Schema cannot say the way JSON does | The fidelity report on the card | [What the fidelity report lists](#what-the-wsdl-fidelity-report-lists) |
| **Trust** the bundle: packaged, WS-I, valid, re-imports | Automatic before every download | [How a WSDL export is checked](#how-a-wsdl-export-is-checked) |
| **Export** from the CLI | `apiome export wsdl <item> --out <folder>` | [Where to find the WSDL card](#where-to-find-the-wsdl-card) |

#### How the item is written {#how-the-item-is-written-to-wsdl}

Exporting to **WSDL** writes a SOAP 1.1 description in the WS-I document/literal style, whatever the
item was imported from. By default you get two files, downloaded together as a `.zip`:

- `<Name>.wsdl` holds the messages, port types, bindings and service, and
- `<Name>.xsd` holds the types. The WSDL imports it with `xsd:import`.

To get one file with the types inline, set the **layout** option to `single`.

- **Types.** An object becomes an XSD `complexType` with a `sequence`, an enumeration a `simpleType`
  with `enumeration` values, a `oneOf` (or another union) a `complexType` with an `xs:choice` of its
  variants, and a map a list of `entry` elements, each with a `key` and a `value`. A list repeats its
  element (`maxOccurs="unbounded"`, or the schema's `minItems`/`maxItems`). An optional or nullable
  field is `minOccurs="0" nillable="true"`. Descriptions become `xs:annotation` documentation.
- **Precision.** Scalars keep their width: `integer` is `xs:int` (`xs:long` with `format: int64`),
  `number` is `xs:double`, a string with `format: date-time` is `xs:dateTime`, and `decimal` stays
  `xs:decimal`.
- **Rules.** `minLength`, `maxLength`, `minimum`, `maximum`, the exclusive bounds, `pattern` and
  `enum` become XSD facets. A JSON Schema pattern is translated to XSD's dialect (`^[A-Z]{3}$` is
  written `[A-Z]{3}`, because an XSD pattern always matches the whole value). XSD has no facet for
  `multipleOf` or `uniqueItems`, nor for a pattern that uses lookahead, lazy quantifiers or `\b`;
  those rules are not written, and the fidelity report lists each one as dropped.
- **Operations.** Each operation becomes a SOAP operation with a request element named after it,
  carrying its path, query and header parameters and its request body, a `<operation>Response`
  element carrying the response body, and one element per error response (`getPetByIdStatus404Fault`).
  The HTTP method and path are not carried; the fidelity report says so for each operation.
- **Names.** Names must be valid XML names: `GET /pets/{petId}` is written `getPetsPetId`, and two
  names that end up the same get a number (`firstName2`). The fidelity report lists every rename.
- **Namespace.** Every type and operation lives in the WSDL's target namespace: the item's own
  namespace, or `http://example.com/service` when it has none (reported as synthesized).

An item imported from WSDL is written back as it was read: its messages, parts, bindings, SOAP
versions and XSD details round-trip unchanged.

- **Field numbers.** WSDL has no field numbers, only element order. An item imported from WSDL or XSD
  numbers its fields by their order, which the export keeps, so nothing is reported. Real field
  numbers (from Protobuf or Thrift) are not written; the report lists each one.
- **One-way operations.** An operation with no reply is written with an `input` and no `output`.
  WSDL 1.1 has no message-exchange pattern, so importing the file again reads it as a request/response
  operation; the report says so for each one. WSDL 2.0 states the pattern, so a 2.0 export does not
  have this problem.

#### WSDL 2.0 {#wsdl-2-0-output}

Set **Wsdl Version** to `2.0` (the default is `1.1`) to write the same types and operations as a
[W3C WSDL 2.0](https://www.w3.org/TR/wsdl20/) description. The files, the layouts and the XML Schema
are the same as for 1.1; only the description changes:

| WSDL 1.1 | WSDL 2.0 |
| --- | --- |
| `definitions` with a `name` | `description`, which has no name |
| `xsd:import` inside an `xsd:schema` in `types` | `xsd:import` directly in `types` (bundle), or the schema inline (single) |
| `message` and `part` | No messages: each operation's `input` and `output` name their element |
| `portType` | `interface`, with each fault declared once as an interface `fault` |
| No message-exchange pattern | `pattern` on each operation: `in-out`, `in-only` for an operation with no reply, `robust-in-only` when it also has faults, `out-only` for an imported WSDL notification |
| `soap:binding` / `soap12:binding` with a `transport` | `binding` of type `soap` with `wsoap:version` (`1.1` or `1.2`) and `wsoap:protocol`; a `soapAction` is `wsoap:action` |
| `http:binding` | `binding` of type `http` with `whttp:methodDefault="POST"` |
| `service` and `port` | `service` (one interface each) and `endpoint` |

The fidelity report lists what WSDL 2.0 cannot say the way WSDL 1.1 did:

| What the item has | How 2.0 writes it | In the report |
| --- | --- | --- |
| A message with several parts (imported from WSDL 1.1) | One element named after the message, with the parts as its children | Approximated |
| The `rpc` binding style | Document/literal: 2.0 has no SOAP `rpc` style | Approximated |
| A payload that is a built-in type (`xsd:string`) | An element of that type, named after the message (`pingInput`) or the fault | Approximated (info) |
| A WSDL 1.1 service whose ports bind different port types | One service per interface: the later ones are named `<service><interface>` | Approximated (info) |
| The item's name | Not written: a 2.0 `description` has no name, so importing the file again names the item after its first service | Approximated (info) |
| No operations at all (types only) | One empty `interface` named after the item, so the file imports again | Synthesized (info) |

An item imported from WSDL 2.0 has none of these to lose: it exports back unchanged.

#### What the fidelity report lists {#what-the-wsdl-fidelity-report-lists}

For an item that is not XML already (OpenAPI, JSON Schema,
GraphQL, Protobuf …), the report names each place where XML Schema cannot say what JSON says, on the
type or field it concerns:

| What the source has | How it is written | In the report |
| --- | --- | --- |
| A union (`oneOf`, `anyOf`) | An `xs:choice` of child elements: a document wraps the value in the element of its alternative | Approximated |
| A union with no alternatives | An empty `xs:choice`, which no value matches | Dropped |
| A nullable field | `nillable="true" minOccurs="0"`: XML tells an absent element from `xsi:nil`, JSON tells `null` from absent | Approximated (info) |
| Examples | Not written: XML Schema has no examples | Dropped (info) |
| `multipleOf`, `uniqueItems`, a pattern XSD cannot express | Not written: XML Schema has no facet for them | Dropped |

An item imported from WSDL or XSD is XML already, so none of these is listed for it.

#### Where to find the WSDL card {#where-to-find-the-wsdl-card}

In the **Export** dialog, the **WSDL** card is under **REST & HTTP** on the
**Target** step, marked multi-file. Its badge is **lossy** for a REST, RPC, GraphQL or JSON Schema
source (the HTTP method and path, field numbers and JSON-only rules are not carried) and **lossless**
for an item imported from WSDL. Pick the card and choose the **Layout**: **bundle** (the default, the
WSDL and its XSD) or **single** (the types inline), and the **Wsdl Version**: **1.1** (the default) or
**2.0**. The fidelity report on the card follows the version you pick. From the CLI, run
`apiome export wsdl <item> --out <folder>` (the files are unpacked into the folder) and add
`--option layout=single` for one file or `--option wsdl_version=2.0` for WSDL 2.0. A lossy export
exits non-zero unless you add `--force`, and `--json` prints the tier. A public item's **Export** dialog on Browse offers WSDL too, as a `.zip`.

#### How a WSDL export is checked {#how-a-wsdl-export-is-checked}

Every WSDL export is checked before you can download it, the way it arrives once you unzip it:

- **Packaged.** The bundle holds exactly one WSDL, and every `xsd:import`, `xsd:include` and
  `wsdl:import` names a file inside the `.zip`. A link to a web address or outside the folder fails.
- **WS-I.** The description passes the WS-I Basic Profile checks: literal use, one binding style,
  document/literal parts, unique operation signatures and `soapAction`s.
- **Valid.** The WSDL validates against the WSDL 1.1 schema, every XSD type and facet is legal, and
  every message, part, port type, binding and port it names exists. A WSDL 2.0 export validates
  against the W3C WSDL 2.0 schema instead, and every element, fault, interface, binding and operation
  it names exists.
- **Re-imports.** The bundle imports into Apiome as a WSDL.

If a check fails, the export fails and lists each problem with its file and rule (`wsi.literal-use`,
`wsdl.bundle-reference`, `wsdl.structure`). An item imported from WSDL keeps its own bindings, so a
WS-I problem the original WSDL already had is not counted again; the item's lint report shows it.

### JSON Schema from any source

#### When to export to JSON Schema

- **Share the data types on their own.** Any item — an OpenAPI or AsyncAPI API, a gRPC service, an
  Avro or Protobuf schema, a GraphQL schema — becomes a standalone JSON Schema of its types, for
  validation pipelines, Kafka JSON subjects, config contracts and database validators. Operations and
  channels are left out, and the card says so (**types-only**).
- **Target an older validator.** Pick `draft-07` or `draft-04` for a tool that does not read
  2020-12; the fidelity report lists each keyword the older draft cannot carry.
- **Generate strict code.** Pick the `jtd` mode for a JSON Type Definition (RFC 8927) document that
  `jtd-codegen` and ajv read.
- **Round-trip a JSON Schema item.** An item imported from JSON Schema exports back **lossless** with
  the default options.

#### JSON Schema export at a glance

| Step | Where | Details |
| --- | --- | --- |
| **Pick** the JSON Schema card and its options (draft, packaging, `$id` base, mode) | **Export** dialog → **JSON Schema** (under **Data schema & graph**) | [Options](#json-schema-export-options) · [Where to find the JSON Schema card](#where-to-find-the-json-schema-card) |
| **See** how types, rules, enumerations and names are written | The fidelity report on the card | [How the item is written](#how-the-item-is-written-to-json-schema) |
| **See** what the draft you picked cannot carry | The fidelity report on the card, recomputed when you change **Draft** | [What the fidelity report lists](#what-the-json-schema-fidelity-report-lists) |
| **Write** a JSON Type Definition instead | **Mode** `jtd` | [JSON Type Definition (JTD) mode](#json-type-definition-jtd-mode) |
| **Trust** the schema: metaschema, `$ref` resolution, then re-import | Automatic before every download | [How a JSON Schema export is checked](#how-a-json-schema-export-is-checked) |
| **Export** from the CLI | `apiome export jsonschema <item> --out <file>.schema.json` | [Where to find the JSON Schema card](#where-to-find-the-json-schema-card) |

#### How the item is written {#how-the-item-is-written-to-json-schema}

Exporting to **JSON Schema** writes the item's data types as a standalone JSON Schema, whatever it
was imported from — for validation pipelines, schema registries and contract tests. By default you
get one draft **2020-12** document, `<Name>.schema.json`, with every type under `$defs`; the
document itself refers (`$ref`) to the type named after the item, when there is one.

- **Types.** Scalars become JSON types, keeping their width as a `format`: a 32-bit integer is
  `{"type": "integer", "format": "int32"}`, a timestamp `{"type": "string", "format": "date-time"}`,
  bytes `{"type": "string", "contentEncoding": "base64"}`. A field that is not optional is listed in
  `required`; a list is an `array`, a union a `oneOf`, a map an object with `additionalProperties`.
  A type with no JSON form is written as `{}` (any value), and the fidelity report names it.
- **Rules.** `minLength`, `maxLength`, `pattern`, `minimum`, `maximum`, the exclusive bounds,
  `multipleOf` and the item counts are written as the same keywords.
- **Enumerations** are written as their JSON values: names for an Avro or Protobuf enum (their JSON
  encodings carry the name), numbers only for an enum of numbers.
- **Names.** Each type is a `$defs` entry named after it (`Order`); two types with the same name
  keep their full keys (`v1.Pet`, `v2.Pet`).

#### Options {#json-schema-export-options}

- **draft** — `2020-12` (default), `draft-07` or `draft-04`. An older draft gets `definitions` instead
  of `$defs`, a `$ref` with other keywords beside it wrapped in `allOf`, and drops what it has no
  keyword for (`deprecated`; in draft-04 also `contentEncoding` and `examples`). Draft-04 writes an
  exclusive bound as `minimum` / `maximum` with `exclusiveMinimum: true` and `$id` as `id`.
- **packaging** — `bundle` (default), or `per-type`: one `<Type>.schema.json` per type, which refer to
  each other by file name (`{"$ref": "Line.schema.json"}`), downloaded together as a `.zip` with a
  `manifest.json`.
- **id_base** — a base URI such as `https://example.com/schemas`: each document's `$id` becomes
  `https://example.com/schemas/<file name>`, so per-type files resolve each other wherever they are
  published.
- **mode** — `json-schema` (default), or `jtd` for a [JSON Type Definition](#json-type-definition-jtd-mode)
  document instead.

#### How a JSON Schema export is checked {#how-a-json-schema-export-is-checked}

Each export is checked before you download it:

1. Every document validates against the metaschema of the draft it declares. A JTD document is
   checked against the RFC 8927 rules instead.
2. Every `$ref` into the export resolves: a `#/$defs/…` pointer must name a type in the document,
   and a `per-type` file's reference must name another file of the export. A reference to a schema
   published elsewhere (an absolute URL outside the export) is not checked.
3. Every document imports again as a JSON Schema.

If a check fails, the export fails and names the file, the JSON pointer and the rule
(`jsonschema.metaschema`, `jsonschema.unresolved-ref`, `jsonschema.reimport`). An item imported from
JSON Schema is re-exported exactly as it was imported unless you pick another draft, `per-type` or
an **id_base**.
Operations and channels are left out: JSON Schema describes data only.

#### What the fidelity report lists {#what-the-json-schema-fidelity-report-lists}

The fidelity report is computed for the options you pick, so changing **draft** in the export dialog
updates it. It lists:

| In the source | In the JSON Schema export |
|---|---|
| Operations, services and channels | Dropped (critical). An item that has any also gets a **types-only** warning counting them — export it to OpenAPI or AsyncAPI as well to keep them |
| A document of another format | Approximated (note): written as JSON Schema, without what is specific to its format |
| A type whose key has a namespace (`com.example.Status`) | Approximated (note): written as `$defs/Status`, and read back under that name |
| A value with a `format` (`date-time`, `int64`, `email` …) | Approximated (note): `format` is an annotation — a validator checks it only when format assertion is switched on |
| `deprecated` (draft-07 and draft-04) | Dropped |
| `prefixItems` (draft-07 and draft-04) | Approximated: the tuple form of `items`, the other items as `additionalItems` |
| `unevaluatedProperties` (draft-07 and draft-04) | Approximated as `additionalProperties` when nothing else applies beside it, else dropped |
| `$dynamicRef`, `$dynamicAnchor`, `$anchor`, `unevaluatedItems` (draft-07 and draft-04) | Dropped |
| An exclusive bound, `const` (draft-04) | Approximated (note): `minimum` with `exclusiveMinimum: true`, a one-value `enum` |
| `examples`, `contentEncoding`, `readOnly`, `if` / `then` / `else` … (draft-04) | Dropped |

Each downgrade is listed on the type or field it happened in.

#### Where to find the JSON Schema card {#where-to-find-the-json-schema-card}

In the **Export** dialog, the **JSON Schema** card is under **Data schema &
graph** on the **Target** step. Its badge is computed for the item: **types-only** for an item with
operations or channels (a REST API, a gRPC service), which the export leaves out, and **lossless** for
a JSON Schema item exported with the default options. Pick the card to set **Draft**, **Packaging**
and **Mode**. From the CLI, run `apiome export jsonschema <item> --out <file>` (`json-schema` works
too); add `--option draft=draft-07`, `--option packaging=per-type --out <folder>` (the files are
unpacked into the folder) or `--option mode=jtd`. A types-only export exits non-zero unless you add
`--force`, and `--json` prints the file written and its fidelity tier as JSON. A public item's
**Export** dialog on Browse offers the same target and downloads a `per-type` export as a `.zip`.

#### JSON Type Definition (JTD) mode

Set **mode** to `jtd` to get the same types as one [JSON Type Definition](https://www.rfc-editor.org/rfc/rfc8927)
(RFC 8927) document, `<Name>.jtd.json` — the strict, code-generation-friendly sibling of JSON Schema
that ajv and the `jtd-codegen` tools read. **draft**, **packaging** and **id_base** do not apply: leave
them unset, or the export is refused.

- **Types.** Each type is a `definitions` entry, and the document refers (`ref`) to the type named
  after the item. A record lists its required fields under `properties` and the others under
  `optionalProperties`; a list is `elements`, a map `values`, a string enumeration `enum`.
- **Scalars.** `string`, `boolean`, `int32`, `float32` and `float64` keep their JTD type; a timestamp is
  `timestamp`. A description is kept as `metadata.description`.
- Every exported document is checked against the schema rules of RFC 8927.

JTD states far less than JSON Schema, so the fidelity report lists every rule the document cannot
carry, on the type or field it is in:

| In the source | In the JTD export |
|---|---|
| `pattern`, `minimum` / `maximum`, the exclusive bounds, `multipleOf`, lengths, item counts, `uniqueItems` | Dropped |
| A `format` other than `date-time` (`uuid`, `email` …), `contentEncoding` | Dropped: written as a plain `string` |
| A 64-bit or unbounded integer (`int64`, `integer`) | Approximated: `float64`, which does not check that a value is whole or exact above 2^53 |
| A union (`oneOf`), or a value of several types | Approximated: `{}` (any value) — JTD only unions records tagged with a discriminator |
| An enumeration of numbers | Approximated: only the values' type is checked |
| `title`, `deprecated`, `default`, `examples` | Dropped (note) |
| Undeclared properties | Approximated (note): JTD rejects a property a record does not declare; the JSON Schema export allows it |

### Kubernetes CRD from any source

Exporting to **Kubernetes CRD** writes a `CustomResourceDefinition` (`apiextensions.k8s.io/v1`) whose
`openAPIV3Schema` you can apply to a cluster. Platform teams use it to turn a JSON Schema (or any
other data schema) into a custom resource. Kubernetes only accepts a *structural* schema, so the
export does not paste the JSON Schema in as it is:

- **No `$ref`.** Every named type is expanded where it is used. A type that refers back to itself
  (a cycle) cannot be expanded, so that member is written as a free-form `type: object`.
- **One root.** The type the **kind** option names (else the item's title, else its only type) is the
  resource. If it is not shaped like a resource root, its fields are nested under `spec`.
- **Structural rules.** Every node declares a `type`. A union (`oneOf`), `uniqueItems`, a `format`
  Kubernetes does not know, `deprecated`, and a `required` name with no property are not written.
- **Names.** The **group**, **kind**, **plural**, **scope** and **version** options name the CRD
  (`widgets.acme.io`, `Widget`, `v1alpha1`). Without them, the export derives each one from the item
  and the fidelity report says so.

The fidelity report lists what the structural rules cost, on the type or field it concerns:

| In the source | In the report |
| --- | --- |
| A reference cycle, a reference to a type the item does not declare, a `null` type, an enum mixing value types | Approximated: written as a free-form node |
| A root type that is not shaped like a resource | Approximated: nested under `spec` |
| A union (`oneOf` / `anyOf`) | Dropped: a structural union may not declare a `type` |
| `uniqueItems`, an unknown `format`, `deprecated`, a `required` name with no property | Dropped |
| Operations and channels | Dropped: the API server generates a CRD's endpoints |

Each export is checked before you download it:

1. Apiome's **structural-schema rules** check every node the way the API server does.
2. **kubeconform** checks the manifest against the `apiextensions.k8s.io/v1`
   `CustomResourceDefinition` schema, when the server has it. Each problem names its JSON path
   (`/spec/names: missing property 'plural'`). A kubeconform that is installed but cannot validate
   the manifest fails the export too. Without kubeconform, the structural rules decide.

To check the file yourself before you apply it, run `kubeconform -strict -summary <file>.yaml`, or
`kubectl apply --dry-run=server -f <file>.yaml` against a cluster.

### XSD (XML Schema) on its own

Exporting to **XSD** writes just the data types as an XML Schema, without the WSDL around them — for
XML payloads, JAXB / JAXP code generation and standards that publish schemas (ISO 20022 — see the
[ISO 20022 message profile](#iso-20022-message-profile) — and UBL). The
types are written exactly as in a WSDL export (the section above; both exports share one mapping):
objects as `complexType`, a `oneOf` as `xs:choice`, a nullable field as `nillable="true"
minOccurs="0"`, a list as `maxOccurs="unbounded"`, enums as `xs:enumeration`, and `pattern`,
`minLength`/`maxLength` and `minimum`/`maximum` as facets. Each object also gets a global element of
the same name, so a document can start with it.

#### When to export to XSD

- **Give an XML pipeline its schema.** Any REST, RPC, GraphQL, JSON Schema or WSDL item becomes a
  standalone XML Schema for validating XML payloads or generating JAXB / JAXP code. Operations and channels
  are left out (XSD describes data only), and the card says **types-only**.
- **Round-trip an XSD.** An item imported from XSD exports back **lossless**, with its own global
  elements, attributes, occurrences and enumerations.
- **Serve an older XML toolchain.** The same types as a RELAX NG grammar or a DTD, with **mode**.
- **Publish a payments message.** The types as an ISO 20022 message definition, with **profile**
  `iso20022`.
- **Exchange business documents or e-invoices.** The types as a UBL 2.1 document schema, with **profile**
  `ubl`, or a Peppol BIS Billing 3.0 invoice or credit note, with **profile** `peppol`.

Need the operations too? Export to [WSDL](#wsdl-and-xsd-from-any-source): its schema is written by the
same mapping, so the types come out the same in both.

#### XSD export at a glance

| Step | Where | Details |
| --- | --- | --- |
| **Pick** the XSD card and its options (version, mode, profile) | **Export** dialog → **Data schema & graph** → **XSD** | Below, *Where to find it* |
| **See** how types, rules and names are written, and what XML Schema cannot say | The fidelity report on the card | The table below |
| **Write** RELAX NG (`.rng`, `.rnc`) or a DTD (`.dtd`) instead | **mode** | [RELAX NG and DTD output](#relax-ng-and-dtd-output) |
| **Write** an ISO 20022 message definition and its message catalog | **profile** `iso20022` | [ISO 20022 message profile](#iso-20022-message-profile) |
| **Write** a UBL 2.1 document schema, or a Peppol BIS invoice or credit note | **profile** `ubl` or `peppol` | [UBL and Peppol BIS profiles](#ubl-and-peppol-bis-profiles) |
| **Trust** the export: XML, packaging, both XSD processors, re-import | Automatic before every download | The numbered checks below |
| **Export** from the CLI | `apiome export xsd <item> --out <file>.xsd` | Below, *Where to find it* |
| **Download** from a public item | Browse → **Export** | Below, *Where to find it* |

- **Version.** Set **xsd_version** to `1.0` (the default) or `1.1`. An XSD 1.1 schema is marked
  `vc:minVersion="1.1"` and writes `multipleOf: 5` as an assertion facet,
  `<xsd:assertion test="$value mod 5 = 0"/>`. XSD 1.0 has no facet for `multipleOf`, so the fidelity
  report lists it there.
- **Namespace.** The schema's `targetNamespace` is the item's own namespace; an item without one gets
  a no-namespace schema, whose types are referenced by plain name.
- **Several namespaces.** When the item's types live in different namespaces (URIs such as
  `http://example.com/common`), you get one `.xsd` per namespace, downloaded together as a `.zip`:
  `<Name>.xsd` is the main schema, `<Name>-common.xsd` the next, and each schema `xs:import`s the
  others it uses.
- **Operations.** XSD describes data only: operations and channels are left out. The fidelity report
  lists each one, and an item with operations carries a **types-only** advisory saying how many were
  left out — export it to WSDL, OpenAPI or AsyncAPI as well to keep them.

An item imported from XSD is written back with its own global elements, attributes, occurrences and
enumeration values.

Each export is checked before you download it, the way it arrives once you unzip it:

1. Every `.xsd` is safe, well-formed XML, and every `xs:import` and `xs:include` names a file inside
   the export. A link to a web address or outside the folder fails.
2. The schema is built by an XML Schema processor. An XSD 1.0 export must build under **both** the
   1.0 and the 1.1 processor; an XSD 1.1 export under the 1.1 processor. An unknown type, a broken
   facet or an XSD 1.1 construct in a 1.0 schema fails the export.
3. The export imports again as an XSD.

A failed check names the file and the rule (`xsd.bundle-reference`, `xsd.schema-1.0`,
`xsd.schema-1.1`, `xsd.reimport`). An item imported from WSDL is also checked through the WSDL
import: its XSD export, put in place of the WSDL's own schema, imports back unchanged.

The fidelity report lists, construct by construct, what XML Schema cannot say the way the source does:

| In the source | In the XSD export |
|---|---|
| An operation or channel | Dropped (types-only), with the advisory above |
| A free-form object (`additionalProperties: {}` or `{type: object}`, with no properties) | Approximated: `xs:any` — any child elements, named by their keys |
| A map with typed values | Approximated: a list of `entry` elements, each with a `key` and a `value` |
| A `oneOf` (or another union) | Approximated: an `xs:choice` of child elements, so a document wraps the value in the element of its alternative |
| A union with no alternatives | Dropped: an empty `complexType` |
| A nullable value | Approximated (note): `nillable="true" minOccurs="0"` — XML tells an absent element from one marked `xsi:nil`, JSON tells `null` from absent, and either form is accepted |
| A property's examples | Approximated (note): kept as `<xsd:documentation source="example">`, which a validator ignores |
| Properties of a non-XSD item | Synthesized (note): each is written as a child element, not an attribute |
| `multipleOf` (XSD 1.0), `uniqueItems`, a pattern XSD cannot express | Dropped: the rule is not written |
| A deprecated property | Dropped (note): XSD has no deprecation marker |
| A name that is not an XML name (`first name`) | Approximated (note): `firstName` |

#### RELAX NG and DTD output {#relax-ng-and-dtd-output}

Some XML tool chains — DocBook-era publishing, configuration formats — read RELAX NG or a DTD rather than
an XML Schema. Set **mode** to write the same types in one of them instead:

| **mode** | You get | Keeps |
| --- | --- | --- |
| `xsd` (default) | XML Schema, as above | Everything in the table above |
| `relaxng` | One RELAX NG grammar in the XML syntax, `<Name>.rng` | Types, facets and namespaces |
| `relaxng-compact` | The same grammar in the compact syntax, `<Name>.rnc` | The same as `relaxng` |
| `dtd` | One DTD, `<Name>.dtd` | Element names and content models only |

Each mode writes one file, even for an item whose types live in several namespaces, and is written from
the same XML mapping as the XSD export, so element names, occurrences, choices and entry lists are the
same in every mode. **xsd_version** applies to `xsd` only; set with another mode, the export is refused.

- **RELAX NG.** Each type is a `define`; each global element is a `define` (`Pet.element`) that `start`
  chooses from. Occurrence is `optional`, `zeroOrMore` or `oneOrMore`. Facets are datatype parameters
  of the XML Schema datatype library — `xsd:string { minLength = "1" maxLength = "40" }` — and an
  enumeration is a choice of values. The main namespace is the grammar's; an element of another
  namespace names its own (`namespace ns1 = "…"` in the compact syntax). Descriptions are
  `a:documentation`, or `##` comments in the compact syntax.
- **DTD.** A record is a content model — `<!ELEMENT Pet (id?, name?, tags*, owner?)>` — a choice is
  `(email | phone)`, a value is `(#PCDATA)` and free-form content is `ANY`. The first global element is
  named in a `Root element` comment. An element of a namespace declares it as a fixed attribute
  (`xmlns CDATA #FIXED "…"`), so a document is valid with a default namespace and no prefixes. An XSD
  attribute stays an attribute (`CDATA`, or the list of its values when they are plain names).

The fidelity report is computed for the mode you pick, and lists, construct by construct:

| In the source | `relaxng` / `relaxng-compact` | `dtd` |
| --- | --- | --- |
| A value's type (`int`, `date-time`, `decimal` …) | Kept | Dropped: any text is valid |
| Facets: `pattern`, lengths, bounds | Kept | Dropped |
| An enumeration | Kept | Dropped for element content; kept for an attribute of plain names |
| A repeat count other than 0–1, 0 or more, 1 or more (`minItems: 2`, `maxItems: 5`) | Approximated: zero or more, or one or more | Approximated: the same |
| A default value on an element | Dropped | Dropped |
| A nullable value | Approximated (note): optional, so null and absent read the same | Approximated (note): the same |
| A property's examples | Dropped (note) | Dropped (note) |
| Two elements of one name with different content | Kept: each where it is | Approximated: declared once, as `ANY` |
| Namespaces | Kept | Approximated (note): a `#FIXED` `xmlns` attribute per element |

The other rows of the XSD table — operations and channels, unions, maps, renamed names — apply to these
modes too.

Each RELAX NG or DTD export is checked before you download it:

1. A RELAX NG grammar is checked with **jing** when the server has it (`jing`, or `jing -c` for the
   compact syntax): it must parse, every `ref` must have a `define`, and every datatype and parameter
   must exist. Each error names its file, line and column (`relaxng.schema`).
2. The file is read by Apiome's RELAX NG or DTD reader (`relaxng.parse`, `dtd.parse`); a `.rng` must also
   be safe, well-formed XML (`relaxng.xml`). Without jing, this is the check.
3. The export imports again as RELAX NG or as a DTD (`relaxng.reimport`, `dtd.reimport`). Its round trip
   is measured through that import.

#### ISO 20022 message profile {#iso-20022-message-profile}

Banks and payment schemes exchange ISO 20022 messages (`pain.001` credit transfers, `pacs.008`
interbank payments, `camt.053` statements), and each message is published as an XML Schema with strict
conventions. Set **profile** to `iso20022` to write the item's types as such a **message definition**
instead of a plain XSD:

| Convention | What the export writes |
| --- | --- |
| **Message identifier** | `<business area>.<message number>.<variant>.<version>`, for example `pain.001.001.09`, from **message_identifier**. An item imported from ISO 20022 keeps its own. |
| **Namespace and file** | One namespace, `urn:iso:std:iso:20022:tech:xsd:pain.001.001.09`, in `pain.001.001.09.xsd`. Types from other namespaces are written in it. |
| **Root element** | One global element, `Document`. Its type wraps the **business element**: the message type (**message_type**, otherwise the one object no other object uses) as an element named after it, for example `CustomerCreditTransferInitiation` for `CustomerCreditTransferInitiationV09`. |
| **Names** | Every type and element name is UpperCamelCase, ASCII letters and digits only: `customer_id` becomes `CustomerId`, `debtor-name` becomes `DebtorName`. An item imported from ISO 20022 keeps the standard's names (`GrpHdr`, `MsgId`). |
| **Documentation** | Each type's and property's description is its `xs:documentation`. `Document` is documented with the message it carries. |
| **Message catalog** | `message-catalog.json`, beside the schema, lists the message: its identifier, business area, message number, variant and version, namespace, schema file, root and business elements, and its message components and data types. |

The schema and the catalog download together as a `.zip`. An upload of the schema is recognized as an
ISO 20022 message definition, with its message id.

The profile has three options of its own, all optional:

- **message_identifier** — the message, for example `pain.001.001.09`. It must have the
  `xxxx.nnn.nnn.nn` shape.
- **business_area** — four letters, such as `pain`, `pacs` or `camt`. Used when there is no
  **message_identifier**; when both are set they must agree.
- **message_type** — the object `Document` wraps, by name. An unknown name is refused.

The profile writes XML Schema only: with **mode** set to `relaxng`, `relaxng-compact` or `dtd`, the export
is refused. **xsd_version** `1.1` is allowed.

The fidelity report lists what the item could not meet of the conventions, at the top of the report or on
the property concerned:

| When | The report says |
| --- | --- |
| The item names no message identifier | Synthesized: the export uses a placeholder, `xxxx.001.001.01` (or `pacs.001.001.01` with **business_area** `pacs`). Set **message_identifier** to name the message. |
| The item has no `Document` of its own | Synthesized (note): the export adds the `Document` root around the business element |
| A name has nothing an ISO 20022 name can keep (`名前`) | Synthesized: the export invents one (`Field`) |
| A name has characters ISO 20022 names cannot hold (`größe`, `2xx`) | Approximated: the closest name (`Groe`, `X2xx`) |
| A name only needs a different case or no separators (`customer_id`) | Approximated (note): `CustomerId` |
| Several objects could be the message | Approximated: the first is used. Set **message_type** to choose another. |
| Types come from another namespace | Approximated: they are written in the message's namespace |
| The item has no object at all | Dropped: `Document` wraps nothing |

Each ISO 20022 export is checked like any XSD export (above), and also:

1. `message-catalog.json` is JSON with one message, naming the export's schema file and its
   `targetNamespace` (`xsd.iso20022-catalog`).
2. The schema imports again as an ISO 20022 message definition, and its round trip is measured through
   that import.

To try it, export an item to **XSD** with **profile** `iso20022` and **message_identifier**
`pain.001.001.09`, or export the sample `apiome-ui/examples/iso20022/07-pain.001.001.09-message-definition.xsd`
after importing it, with no options.

#### UBL and Peppol BIS profiles {#ubl-and-peppol-bis-profiles}

Business documents — orders, invoices, despatch advice — are exchanged as OASIS **UBL** (Universal Business
Language), and EU e-invoicing runs on **Peppol BIS Billing 3.0**, whose invoices and credit notes are UBL 2.1
documents. Set **profile** to `ubl` to write the item's types as a UBL 2.1 document schema, or to `peppol` for
the same with the Peppol BIS conventions applied.

| Convention | What the export writes |
| --- | --- |
| **UBL data types** | Every value is typed by a UBL data type: `udt:TextType`, `udt:CodeType` (an enumeration), `udt:IdentifierType` (an ID or UUID), `udt:NameType`, `udt:AmountType` (a decimal named like an amount, price or total), `udt:NumericType`, `udt:IndicatorType` (a boolean), `udt:DateType`, `udt:TimeType`, `udt:DateTimeType`, `udt:BinaryObjectType`. |
| **UBL components** | A value whose name and data type match a UBL basic component is a reference to it — `issueDate` is `cbc:IssueDate`, `totalAmount` `cbc:TotalAmount`, `note` `cbc:Note` — so the schema reuses UBL's own definitions. |
| **UBL names** | UpperCamelCase, each value ending with its representation term: `status` (an enumeration) is `StatusCode`, `paid` `PaidIndicator`, `orderId` `OrderID`. An object is an aggregate type, `<Name>Type`. |
| **The document** | One global element, the document (**ubl_document**: `Invoice`, `Order` …), whose type is the document object headed by `cbc:UBLVersionID`, `cbc:CustomizationID` and `cbc:ProfileID`. |
| **Namespace** | The document's own namespace (**ubl_namespace**, by default `urn:apiome:names:specification:ubl:schema:xsd:<Document>-2`); the OASIS namespaces belong to the OASIS documents. |
| **Rules** | UBL data types carry no facets or code lists, so a `maxLength`, a pattern or an enumeration's codes are written as documentation. An optional value is left out when absent (UBL has no `nil`). |

**The UBL schemas ship with it.** The export is a `.zip`: `<Document>.xsd`, the OASIS UBL 2.1 schemas it
imports (`common/UBL-CommonBasicComponents-2.1.xsd`, `UBL-UnqualifiedDataTypes-2.1.xsd`,
`UBL-QualifiedDataTypes-2.1.xsd` and UN/CEFACT's `CCTS_CCT_SchemaModule-2.1.xsd`, unmodified), their
`NOTICE.md`, and a guide, `<Document>.ubl-guide.md`, listing the header and every value with its UBL type,
cardinality and source. Everything a receiver needs to validate documents is in the one download.

**Peppol BIS Billing 3.0** (`peppol`) applies its conventions on top:

- The document is an `Invoice` (the default) or a `CreditNote`.
- `cbc:CustomizationID` and `cbc:ProfileID` are mandatory, and documented with the BIS values
  (`urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0` and
  `urn:fdc:peppol.eu:2017:poacc:billing:01:1.0`).
- `cbc:ID`, `cbc:IssueDate`, the type code (`cbc:InvoiceTypeCode` or `cbc:CreditNoteTypeCode`) and
  `cbc:DocumentCurrencyCode` are mandatory, right after the header. The item's own values are used when it has
  them (a field named `issueDate` of type date is `cbc:IssueDate`); any it lacks are added.

Peppol also publishes Schematron business rules (EN 16931 and the Peppol rules). **The export does not run
them**: it applies the document, header and mandatory-component conventions above. Validate the invoices
themselves with the Peppol validation artifacts too; the guide says so.

The profile options, all optional:

- **ubl_document** — the document element, in UpperCamelCase. By default an imported UBL item's own document,
  else `Invoice` for Peppol, else the item's name. Peppol takes `Invoice` or `CreditNote` only.
- **ubl_namespace** — the schema's target namespace, a URI.
- **document_record** — the object the document is made from, by name. By default the one object no other
  object uses; an unknown name is refused.

Both profiles write XML Schema only: with **mode** set to `relaxng`, `relaxng-compact` or `dtd`, the export is
refused.

The fidelity report lists what the item could not meet of the conventions:

| When | The report says |
| --- | --- |
| Always | Synthesized (note): the document element and its UBL header |
| Peppol, and the item has no value for a mandatory component | Synthesized: the component the export adds, such as `cbc:InvoiceTypeCode` |
| A `maxLength`, pattern or bounds; an enumeration's codes | Approximated: written as documentation, which nothing checks |
| A name that needs a representation term or another case (`status` → `StatusCode`) | Approximated (note) |
| Several objects could be the document | Approximated: the first is used. Set **document_record** to choose another. |
| Types from another namespace | Approximated: written in the document's namespace |

Each UBL or Peppol export is checked like any XSD export (above): the document schema is built by an XML
Schema processor **against the shipped OASIS UBL 2.1 schemas**, reading only the export's own files. Also:

1. Every shipped `common/` schema is the OASIS file, byte for byte (`ubl.bundled-schemas`), and `NOTICE.md`
   is there (`ubl.notice`).
2. A Peppol export meets the conventions above (`ubl.peppol`): an `Invoice` or `CreditNote`, a mandatory
   `cbc:CustomizationID` and `cbc:ProfileID` with the BIS values, and the four mandatory components.
3. The schema imports again as an XSD item.

To try it, export an item to **XSD** with **profile** `peppol`, or import the sample
`apiome-ui/examples/xsd/07-ubl-2.1-invoice-set` and export it with **profile** `ubl`.

**Where to find it.** In the **Export** dialog, the **XSD** card is under **Data schema & graph** on the
**Target** step. Its badge is **lossless** for an item imported from XSD and **types-only** for any
other source (XSD keeps the types and leaves out the operations). Pick the card to see its options:
**Xsd Version** (`1.0` by default, or `1.1`), **Include Xml Declaration** and **Include Comments** (both
on by default), **Mode** (`xsd` by default; `relaxng`, `relaxng-compact` or `dtd`), **Profile**
(`generic` by default, `iso20022`, `ubl` or `peppol`), the ISO 20022 profile's **Message Identifier**,
**Business Area** and **Message Type**, and the UBL profiles' **Ubl Document**, **Ubl Namespace** and
**Document Record**. From the CLI, run `apiome export xsd <item> --out <file>.xsd`, and add
`--option xsd_version=1.1`, `--option include_xml_declaration=false`, `--option mode=dtd --out <file>.dtd`
`--option profile=iso20022 --option message_identifier=pain.001.001.09 --out <file>.zip` or
`--option profile=peppol --option ubl_document=CreditNote --out <file>.zip`. A types-only
export exits non-zero unless you add `--force`, and `--json` prints the tier. A public item's **Export**
dialog on Browse offers XSD too: the `.xsd` file, or a `.zip` when the item spans several namespaces or
uses the ISO 20022, UBL or Peppol profile.

### ASN.1 from any source

#### When to export to ASN.1

- **Hand the data types to an ASN.1 tool chain.** Any item — an OpenAPI or AsyncAPI API, a JSON
  Schema, a gRPC or Avro schema — becomes one X.680 module of its types for telecom (5G, NAS), LDAP,
  PKI and aviation protocols. Operations and channels are left out, and the card says so
  (**types-only**).
- **Keep the rules enforceable.** Lengths, bounds, item counts and simple patterns become ASN.1
  subtype constraints, so `asn1tools` checks them when it encodes. What ASN.1 cannot carry is listed
  in the fidelity report before you download.
- **Round-trip an ASN.1 item.** An item imported from ASN.1 exports **lossless**, back to an
  equivalent module.

#### ASN.1 export at a glance

| Step | Where | Details |
| --- | --- | --- |
| **Pick** the ASN.1 card and its options (module name, OID, automatic tags, comments) | **Export** dialog → **ASN.1** (under **Data schema & graph**) | [Options](#asn1-export-options) · [Where to find the ASN.1 card](#where-to-find-the-asn1-card) |
| **See** how types, scalars, optional fields and names are written | The fidelity report on the card | [How the item is written](#how-the-item-is-written-to-asn1) |
| **See** how each rule becomes subtype notation | The fidelity report on the card | [How constraints are written](#how-constraints-are-written-in-asn1) |
| **See** what ASN.1 cannot carry | The fidelity report on the card | [What the fidelity report lists](#what-the-asn1-fidelity-report-lists) |
| **Trust** the module: `asn1tools` parses and compiles it | Automatic before every download | [How an ASN.1 export is checked](#how-an-asn1-export-is-checked) |
| **Export** from the CLI | `apiome export asn1 <item> --out <file>.asn1` | [Where to find the ASN.1 card](#where-to-find-the-asn1-card) |

#### How the item is written {#how-the-item-is-written-to-asn1}

Exporting to **ASN.1** writes the item's data types as one ITU-T X.680 module, `<Module>.asn1`,
for telecom, PKI and aviation tool chains. The module compiles with `asn1tools`. Operations and
channels are left out: an ASN.1 module describes data only.

- **Types.** Objects become `SEQUENCE`s, unions `CHOICE`s (one alternative per member type), enums
  `ENUMERATED` (numbered when every value is a distinct integer), and lists `SEQUENCE OF`. A map
  becomes `SEQUENCE OF SEQUENCE { key …, value … }`, because ASN.1 has no map type.
- **Scalars.** Text is `UTF8String`, bytes `OCTET STRING`, a timestamp `GeneralizedTime`, a date
  `DATE`, a time `TIME-OF-DAY`, a real `REAL`. A sized integer keeps its width as a range: `uint8` is
  `INTEGER (0..255)`, `int32` `INTEGER (-2147483648..2147483647)`.
- **Optional fields.** A field with a default is written `DEFAULT <value>` (`TRUE`, `3`, `"hi"`, or an
  enum item); any other field that may be left out is `OPTIONAL`.
- **Names.** Type names start with a capital letter and field and enum names with a small one, using
  hyphens between words: `order_id` is written `order-id`, `OPEN` is `open`, and a type named like a
  reserved word (`END`) gets `-Type`. Each rename is in the fidelity report, and a clash gets a
  number (`line-no-2`).
- **Descriptions** are written as `--` comments. An ASN.1 import does not read comments, so the report
  notes each one.

#### How constraints are written {#how-constraints-are-written-in-asn1}

Constraints are kept as ASN.1 subtype notation, so a validator such as `asn1tools` checks them when
encoding:

| In the source | In the ASN.1 export |
|---|---|
| `minLength` / `maxLength` | `UTF8String (SIZE (3..20))`, also on `OCTET STRING` |
| `minItems` / `maxItems` | `SEQUENCE (SIZE (1..50)) OF …` (other rules on a list apply to its items) |
| `minimum` / `maximum` | A value range, `INTEGER (1..100)`, within the integer's width |
| An exclusive bound on an integer | The same range, inclusive: `> 0` is written `1..` |
| An exclusive bound on a real | Approximated: written inclusive, because `asn1tools` cannot read `<` |
| An `enum` of integers | A value set, `INTEGER (1 \| 2 \| 5)` |
| A `pattern` that only lists the allowed characters, anchored at both ends (`^[A-Z0-9_]{3,8}$`, `^\d{4}$`) | A permitted alphabet with its length: `UTF8String (SIZE (3..8)) (FROM ("A".."Z" \| "0".."9" \| "_"))` |
| Any other `pattern` (`^[A-Z]{3}-\d+$`) | A `-- pattern: …` comment above the field — `asn1tools` does not check it |
| `multipleOf`, `uniqueItems`, an `enum` of strings, formats such as `email` | Dropped, and listed in the report |

#### Options {#asn1-export-options}

- **module_name** — the module name, such as `Shop-Orders`. By default it is the imported module's
  name, else the item's namespace when that is already a valid module name, else the item's name.
- **oid** — the module's object identifier, dotted (`1.3.6.1.4.1.99999.1`) or as arcs in braces
  (`{ iso(1) identified-organization(3) 6 }`). It is written after the module name.
- **automatic_tags** — on by default (`AUTOMATIC TAGS`). Turn it off to keep an imported module's
  own tagging.
- **include_comments** — on by default; turn it off to leave out the header, description and pattern
  comments.

An item imported from ASN.1 exports back to an equivalent module that reads back unchanged, built-in
types such as `OBJECT IDENTIFIER` and `PrintableString` included. A type the module imports from
another module has no definition to write, so it is written as `UTF8String` and listed in the report.

#### What the fidelity report lists {#what-the-asn1-fidelity-report-lists}

The fidelity report lists, on each type or field:

| In the source | In the report |
|---|---|
| Operations, services and channels | Dropped (critical). An item that has any also gets a **types-only** warning counting them — export it to OpenAPI or AsyncAPI as well to keep them |
| A rule written as subtype notation (lengths, bounds, item counts, a set of integers) | Carried, naming the notation used (`minLength/maxLength → SIZE`) |
| A pattern written as a permitted alphabet | Approximated (note) |
| Any other pattern, `multipleOf`, `uniqueItems`, a set of strings, a default with no ASN.1 value | Dropped |
| An exclusive bound on a real, a map, a type with no ASN.1 form | Approximated |
| A name respelled to the ASN.1 rules (`order_id` → `order-id`) | Synthesized (note) |
| A type that refers to itself (`Node.next: Node`) | Carried |
| A description, a document of another format, types read back under the module name | Approximated (note) |

#### How an ASN.1 export is checked {#how-an-asn1-export-is-checked}

Each export is checked with **asn1tools** before you download it:

1. The module parses. A syntax error fails the export and names its line and column
   (`asn1.parse`).
2. The module compiles: every type it uses is defined, and every constraint is valid
   (`asn1.compile`).
3. It is one module (`asn1.module-count`), and it defines exactly the types Apiome planned to write
   for the item: a planned type that is missing (`asn1.missing-type`) or an extra one
   (`asn1.unexpected-type`) fails the export.

A failed check fails the export job and lists each problem with its rule.

#### Where to find the ASN.1 card {#where-to-find-the-asn1-card}

In the **Export** dialog, the **ASN.1** card is under **Data schema & graph** on
the **Target** step, as one file. Its badge is **lossless** for an item imported from ASN.1 and
**types-only** for any other source (ASN.1 keeps the types and leaves out the operations). Pick the
card to see its four options: **Module Name**, **Oid**, **Automatic Tags** and **Include Comments**.
For example, an OpenAPI `string` with `minLength: 8, maxLength: 16` is written
`UTF8String (SIZE (8..16))`, a pattern such as `^[A-Z]+$` adds `(FROM ("A".."Z"))`, an `integer`
with `minimum: 1, maximum: 65535` is `INTEGER (1..65535)`, and a `oneOf` is a `CHOICE`. From the
CLI, run `apiome export asn1 <item> --out <file>.asn1`, and add `--option module_name=Acme-Pets` or
`--option oid=1.3.6.1.4.1.99999.1`. A types-only export exits non-zero unless you add `--force`, and
`--json` prints the tier. A public item's **Export** dialog on Browse offers ASN.1 too, as the `.asn1`
file.

### Legacy REST descriptors

Before OpenAPI, two formats described REST APIs, and older toolchains still read them: **WADL**, the
XML description Java (JAX-RS) stacks and some API gateways import, and **Google API Discovery**, the JSON
document Google's API client libraries build a client from. Apiome writes both from any item, and an item
imported from either exports back **lossless**. In **Export studio**, both cards sit under **REST &
HTTP** on the **Target** step.

#### When to use which

- **A JAX-RS stack, a gateway or a tool that imports WADL: WADL.** Export [WADL](#wadl-from-any-source)
  for the resource tree, methods, parameters and status codes, with the types in an XSD grammar — the
  same XSD a WSDL export writes. It downloads as a `.wadl` and its `.xsd` in a `.zip`, or as one file.
- **A client built by Google's API client libraries: Google API Discovery.** Export
  [Google API Discovery](#google-api-discovery-from-any-source) for one JSON document of resources,
  methods, path and query parameters and schemas, with method ids such as `petstore.pets.listPets`.
- **Anything new: OpenAPI.** Neither format is developed any more; prefer
  [OpenAPI](#openapi-32-31-30-and-swagger-20) unless the consumer reads only WADL or Discovery.

Both describe HTTP resources and nothing else. A GraphQL, gRPC, event or data-schema item exports at most
its types, and its fidelity report starts with **WADL captures REST only** or **Google API Discovery
captures REST only**.

#### Legacy REST descriptors at a glance

| | WADL | Google API Discovery |
| --- | --- | --- |
| **From** | Any source | Any source with an HTTP operation or a type |
| **You get** | `<Name>.wadl` and `<Name>.xsd` in a `.zip`, or one `.wadl` | `<name>.discovery.json` |
| **Options** | `layout` (`bundle`, `single`) | `name`, `version` |
| **Types become** | An XSD grammar, with facets for constraints | Discovery's JSON Schema subset (64-bit integers as strings) |
| **Parameters** | Path, query and header | Path and query |
| **Responses** | Every response, by status code | The success body only |
| **Checked by** | The W3C WADL schema, an XML Schema processor, and re-import | The Discovery metaschema, Discovery's rules, and re-import |
| **CLI** | `apiome export wadl` | `apiome export discovery` |

Every parameter, response, server and keyword an export cannot carry is listed in its fidelity report
before you download.

### WADL from any source

Exporting to **WADL** writes a description that validates against the W3C WADL schema, with its
types in an XSD grammar. By default you get two files, downloaded together as a `.zip`:

- `<Name>.wadl` holds the resources and methods, and
- `<Name>.xsd` holds the grammar. The WADL links it with `<grammars><include href="…"/>`.

To get one file with the grammar inline, set the **layout** option to `single`. A model with no types
and no request or response bodies has no grammar, so you get the `.wadl` alone.

- **Resources.** Each path segment becomes a `resource`, nested the way the paths are (`/pets/{petId}`
  is `pets` holding `{petId}`); an operation on `/` gets `<resource path="/">`.
- **Methods.** Each operation is a `method` with its HTTP verb, its description as `doc`, and its
  operation name as `id` when the source names it.
- **Parameters.** Path parameters are `template` params on the resource that names them; query and
  header parameters are request params, with their XSD type (`xsd:long` for a 64-bit integer),
  `required`, `default` and documentation. An array is a `repeating` param.
- **Bodies.** The request body and every response carry a `representation` with the body's media type
  and the grammar element of its type. A list or scalar body gets an element of its own in the grammar
  (`getPetsResponse200`). Each response keeps its status code.
- **Types.** The grammar is the same XSD a WSDL export writes (see the section above): types keep
  their precision, optional fields are `minOccurs="0"`, and constraints become facets.

WADL describes HTTP resources and nothing else, so the fidelity report lists what it cannot carry:

- operations with no HTTP method and path (from gRPC, GraphQL or WSDL sources), and event operations;
- cookie parameters, and status ranges such as `4XX`;
- every server but the first;
- the grouping into services, the version and the description;
- gateway details such as routes, backends and hosts.

When the source has no server, the base URI `https://api.example.com/` is used, and the report says so.

An item imported from WADL is written back as it was read. Import now also reads a WADL root written
as `<wadl:application>`, the query and header params a method's request declares, and — when you
upload the WADL together with its `.xsd` in a `.zip` — the grammar it includes.

**WADL captures REST only.** A GraphQL, gRPC, event or data-schema item gets a warning at the top of its
fidelity report: **WADL captures REST only**. The warning counts the operations and channels that are not
written, and it is critical when no operation can be written, so only the item's types are exported.

**Checked before you download it.** Every WADL export is checked as it will be unpacked, and the job fails,
listing every problem with its file and rule, when:

1. **A file is not safe, well-formed XML** (`wadl.xml`) — a DTD or entity is refused.
2. **The description does not validate against the W3C WADL schema** (`wadl.schema`): an element or
   attribute WADL does not have, or a type that is not a declared QName.
3. **The grammar is missing or does not build**: `<grammars><include>` names a file that is not in the
   export (`wadl.bundle-reference`), or an XML Schema processor rejects the grammar, included or inline
   (`wadl.grammar`).
4. **A representation names an element the grammar does not declare** (`wadl.representation`).
5. **Apiome's WADL importer cannot read the export back** (`wadl.reimport`).

**Where to find it.** In the **Export** dialog, pick the **WADL** card on the **Target** step (in **Export
studio** it is under **REST & HTTP**), marked multi-file. A REST item is badged **lossy**, and an item
imported from WADL exports back **lossless**. Pick the **Layout**: `bundle` (the default) downloads the
`.wadl` and its `.xsd` grammar as a `.zip`, and `single` writes one `.wadl` with the grammar inline. From
the CLI, run `apiome export wadl <item> --out <folder>`, and add `--option layout=single` for one file. A
public item's **Export** dialog on Browse offers WADL too.

### Google API Discovery from any source

Google's API client libraries and generated clients are built from **Discovery documents**: one JSON
description of an API's resources, methods, parameters and schemas. Exporting to **Google API
Discovery** writes the item as one, `<name>.discovery.json`. It follows the Discovery format's own
metaschema, and Google's API client library for Python builds a working client from it, with a call for
every method.

- **Document.** `kind` `discovery#restDescription`, the API's `name` (lower-case letters and digits,
  made from the item's name: *Pet Store* is `petstore`), its `version` (the item's, else `v1`), `id`
  `<name>:<version>`, the title and description. The first server gives `rootUrl` (scheme and host) and
  `servicePath` (its path, `api/v1/`); server variables take their defaults. Set the **name** and
  **version** options to choose others.
- **Resources and methods.** An operation is filed under the resource its path starts with
  (`/pets/{petId}` is in `pets`) and named after its operation name (`listPets`); an operation whose path
  starts with a parameter is a top-level method. Each method has an `id` (`petstore.pets.listPets`), a
  `path` relative to `servicePath`, its HTTP verb and description.
- **Parameters.** Path and query parameters, with their type, `required`, `default`, `enum`, `pattern`,
  `minimum` and `maximum`. A list is a `repeated` parameter. A path parameter is always required, and
  the required parameters are listed in `parameterOrder`, path ones first.
- **Bodies.** The request and the success response are `$ref`s to schemas. A body that is not one named
  type (a list, a scalar, an inline schema) gets a schema of its own, `ListPetsResponse`.
- **Schemas.** Each type, in Discovery's JSON Schema subset, through the same draft-04 mapping as a
  [JSON Schema export](#json-schema-from-any-source). A required field is marked `required: true`, and
  `deprecated` is kept.

| In the source | In the Discovery document |
|---|---|
| A 32-bit or unsized integer | `integer`, `format: int32` |
| A 64-bit integer | `string`, `format: int64`: Discovery sends 64-bit integers as strings |
| A float or a double (a decimal too) | `number`, `format: float` or `double` |
| Base64 bytes, a date, a date-time | `string`, `format: byte`, `date` or `date-time` |
| An enum | `string` with `enum`, and each value's description in `enumDescriptions` |
| A map | `object` with `additionalProperties` |
| A union, or a type that may be several | `type: any`, its alternatives named in the description |

An item imported from Discovery keeps its name, resource tree, method names and ids, and its parameters'
values, so it reads back unchanged. When its `baseUrl` leaves out its `servicePath`, the export writes the
full `baseUrl`, and the report says so.

The fidelity report lists what a Discovery document cannot carry:

- operations with no HTTP method and path (from gRPC, GraphQL or WSDL sources), event operations and
  channels;
- header and cookie parameters: Discovery parameters go in the path or the query;
- every response but the success body (a Discovery method has one response; errors are Google's
  standard error), and every server but the first;
- schema keywords Discovery has no place for: lengths, list sizes, `multipleOf`, closed objects,
  non-string enums, object defaults and string formats other than `byte`, `date` and `date-time`;
- what it changes: nullable types written as their type, exclusive bounds written inclusive, renamed path
  parameters, and 64-bit integers as strings;
- how it reads back: services become one API named after the title, an operation is named by its method
  id and keyed by its full path (`servicePath` included), and `required: true` is a hint Discovery clients
  do not enforce, so a required field reads back optional.

A source with no HTTP operation and no type has nothing a Discovery document can hold, so the card is
greyed out for it.

**Google API Discovery captures REST only.** A GraphQL, gRPC, event or data-schema item gets a warning at
the top of its fidelity report: **Google API Discovery captures REST only**. The warning counts the
operations and channels that are not written, and it is critical when only the item's types are exported.

**Checked before you download it.** Every Discovery export is checked, and the job fails, listing every
problem with its JSON pointer and rule, when:

1. **The document does not validate against the Discovery metaschema** (`discovery.schema`): a missing
   `kind`, `name`, `version`, `rootUrl` or `servicePath`, a parameter with no `type` or `location`, a
   `location` other than `path` or `query`, or a lower-case HTTP method.
2. **The URLs disagree** (`discovery.urls`): `rootUrl` is not an absolute URL ending in `/`, `servicePath`
   starts with `/`, or `baseUrl` is not `rootUrl` + `servicePath`.
3. **A schema is wrong**: its `id` is not its key (`discovery.schema-id`), a `$ref` names no schema of the
   document (`discovery.ref`), or a `type` / `format` pair is not one of Discovery's
   (`discovery.type-format`).
4. **A method is wrong**: its id is used twice (`discovery.method-id`), its path names a variable that is
   not a required path parameter, or a path parameter is not in its path (`discovery.path-parameter`), or
   `parameterOrder` lists an undeclared parameter (`discovery.parameter-order`).
5. **Apiome's Discovery importer cannot read the document back** (`discovery.reimport`).

When the source has no server, `https://api.example.com/` is used, and the report says so.

**Where to find it.** In the **Export** dialog, pick the **Google API Discovery** card on the **Target**
step (in **Export studio** it is under **REST & HTTP**). A REST item is badged **lossy**, and an item
imported from Discovery exports back **lossless**. Leave **Name** and **Version** empty for the item's own
(else a name made from the item's name, and `v1`), or type others (`pets`, `v2`). From the CLI, run
`apiome export discovery <item> --out petstore.discovery.json`, and add `--option name=pets` or
`--option version=v2`. A public item's **Export** dialog on Browse offers the document too.

### RAML from any source

#### When to export to RAML

- **Supply a tool that still reads RAML.** A REST item is written as one RAML 1.0 document with its
  resources, methods, types and facets. RAML is no longer actively developed, so prefer OpenAPI for
  new work; the fidelity report lists what RAML cannot carry before you download.
- **Round-trip a RAML item.** An item imported from RAML exports back **lossless**, with its resource
  types and traits already applied to each method.

RAML describes REST APIs only. A GraphQL, gRPC, event or data-schema item exports at most its types,
and its report starts with **RAML captures REST only**.

#### RAML export at a glance

| Step | Where | Details |
| --- | --- | --- |
| **Pick** the RAML card and its options | **Export** dialog → **REST & HTTP** → **RAML** | [Where to find the RAML card](#where-to-find-the-raml-card) |
| **See** how the document, types and resources are written | The fidelity report on the card | [How the item is written](#how-the-item-is-written-to-raml) |
| **See** what RAML cannot carry | The fidelity report on the card | [What the fidelity report lists](#what-the-raml-fidelity-report-lists) |
| **Trust** the file: AMF validation and re-import | Automatic before every download | [How a RAML export is checked](#how-a-raml-export-is-checked) |
| **Export** from the CLI | `apiome export raml <item> --out <file>.raml` | [Where to find the RAML card](#where-to-find-the-raml-card) |

Exporting to **RAML** writes one `<Name>.raml` file in RAML 1.0, starting with the `#%RAML 1.0` header
line that RAML tools require.

#### How the item is written {#how-the-item-is-written-to-raml}

- **Document.** The item's title, description and version, its first server as `baseUri` (server
  variables become `baseUriParameters`), and a `mediaType`: a RAML item keeps its own; otherwise it is
  the media type the bodies use most, or `application/json`. Set the **media_type** option to choose
  another default.
- **Types.** Objects keep their fields in order, and an optional field is written `name?`. Enums are
  `string` types with `enum`, unions are `Cat | Dog`, and maps are objects with a `//` property.
  Numbers keep their width (`integer` with `format: int64`) and dates their type (`datetime`,
  `date-only`). Lengths, ranges, patterns, list sizes, enums and defaults become RAML facets.
- **Resources.** Each path is one resource (`/pets/{petId}`), with its path parameters as
  `uriParameters`. Each operation is a method with its operation name as `displayName` (when the
  source names it), its description, query parameters, headers and body, and its responses by status
  code with their description, headers and body.

#### What the fidelity report lists {#what-the-raml-fidelity-report-lists}

RAML describes REST APIs only. An item from GraphQL, gRPC, an event or data-schema format, or an agent
descriptor gets a warning at the top of its fidelity report: **RAML captures REST only**. The warning
counts the operations and channels that are not written. It is critical when no operation can be
written and only the item's types are exported.

The fidelity report lists what RAML cannot carry:

- operations with no HTTP method and path (from gRPC, GraphQL or WSDL sources), a `TRACE` or `CONNECT`
  method, event operations and channels, and a second operation on the same method and path;
- cookie parameters, and status ranges such as `4XX`;
- every server but the first, and the grouping into services;
- exclusive bounds, string formats RAML has no type for (`email`, `uuid`), and a facet the type does
  not allow;
- deprecation flags, tags, and source details such as gateway routes — on the document, an
  operation, a parameter or a type;
- renamed types: RAML type names cannot contain dots or spaces, so `com.acme.Order` is written
  `Order` (or `Order2` when the name is taken). The report drops the type under its old key and adds
  it under the new name, which is how it reads back;
- services: a RAML document is one API, so the item's services are dropped and it reads back as one
  service named after the title;
- field numbers: RAML keeps the order of an object's properties but not their numbers, so the
  properties read back numbered by position.

An item imported from RAML is written back as it was read. Its resource types and traits are already
applied to each method when it is imported, so the export writes the methods in full, without `type:`
or `is:`, and the report says so.

#### How a RAML export is checked {#how-a-raml-export-is-checked}

Each export is checked before you download it:

1. **AMF** validates it against RAML 1.0 when the server has the AMF toolchain. A violation fails the
   export and names its rule, line and column (`example-validation-error`); warnings do not. Without
   AMF, the RAML importer reads the document instead, and a parse error fails the export.
2. The document is then imported again. If it does not import, the export fails (`raml.reimport`).

An item imported from RAML exports and re-imports unchanged. From any other source, the re-import
shows what RAML could not keep, and the fidelity report names each of those changes. One change is not
in the report: Apiome's RAML reader does not read `displayName`, so an operation's name reads back as
its method and path (`DELETE /reindex`).

#### Where to find the RAML card {#where-to-find-the-raml-card}

In the **Export** dialog, the **RAML** card is under **REST & HTTP** on the
**Target** step, as one file. Its badge is **lossless** for an item imported from RAML and **lossy**
for any other source. A GraphQL, RPC or data-schema item's fidelity report, on the **Fidelity** step,
starts with **RAML captures REST only**. Pick the card to see its two options: **Include Comments** (on
by default) writes the generated-file comment under the `#%RAML 1.0` line, and **Media Type**
(`application/json` by default) is the document `mediaType` when the item names none. From the CLI,
run `apiome export raml <item> --out <file>.raml`, and add `--option include_comments=false` or
`--option media_type=application/xml`. The CLI prints the report's warnings, the REST-only one
included. A lossy export exits non-zero unless you add `--force`, and `--json` prints the tier. A
public item's **Export** dialog on Browse offers RAML too, as the `.raml` file.

### Arazzo from any source

**Arazzo** describes workflows: sequences of API calls. It is not a description of the API itself,
so exporting a plain REST, RPC or event API to Arazzo gives you only the sequencing Apiome can make
of it. The fidelity report warns about this first: *this target captures workflows, not the full API
surface*.

#### When to export to Arazzo

- **Round-trip an Arazzo document.** An item imported from Arazzo 1.0 or 1.1 exports back
  **lossless**, with its workflows, steps, inputs and outputs as you wrote them.
- **Start workflows for an API you already have.** A REST, RPC or GraphQL item exports to a
  starting point: one workflow per service, one step per operation, ready for you to edit into the
  real sequences.

A published project version also serves an Arazzo document of its own, generated per class
(`/v1/arazzo`, `apiome schema arazzo`). That is a different document; see
[Download Arazzo or JSON Schema by slug](#download-arazzo-or-json-schema-by-slug).

#### Arazzo export at a glance

| Step | Where | Details |
| --- | --- | --- |
| **See** what the export keeps, approximates and synthesizes | The fidelity report on the **Arazzo** card | [What is written](#what-is-written-to-arazzo) |
| **Choose** the Arazzo version and YAML style | **Export** dialog → **REST & HTTP** → **Arazzo** | [Where to find it](#where-to-find-the-arazzo-card) |
| **Export** from the CLI | `apiome export arazzo <item> --out <file>.arazzo.yaml` | [Where to find it](#where-to-find-the-arazzo-card) |
| **Trust** the file: schema check and re-import | Automatic before every download | [Arazzo export checks](#arazzo-export-checks) |
| **Replace** the placeholder source description | In the downloaded file, before you run the workflow | [What is written](#what-is-written-to-arazzo) |

#### What is written to Arazzo {#what-is-written-to-arazzo}

- **An item imported from Arazzo** is written back as it was read, with its own workflows, steps,
  inputs and outputs.
- **Any other item** gets one workflow per service. The workflow's steps call that service's
  operations by id, in the order they are declared. The source declares no such workflow, so the
  report marks it **synthesized**. When an operation has no id of its own, the step uses the
  operation's key (`POST /orders`), and the report marks that synthesized too.
- **Each operation** becomes a step and is marked **approximated**. Its parameters, request and
  response schemas stay in the source description and are not written.
- **Types, servers and event channels** are not written. Types and channels are marked **dropped**.
- **A source description** is required by Arazzo. When the item names none, the document gets one
  entry named after the API, pointing at a placeholder such as `./shop-orders.openapi.yaml`.
  **Replace that URL** with the address of the real API description before you run the workflow.
  The report marks the entry **synthesized**.
- **A version** is required too. An item without one is written as version `1.0.0`, marked
  **synthesized**.
- **An item with nothing to sequence**, such as a set of types or an event API, cannot be exported
  to Arazzo: a valid Arazzo document needs at least one workflow. Arazzo is not offered for it, and
  the export is refused with the reason.

Every export from a non-Arazzo item shows the fidelity warning before you download.

#### Where to find the Arazzo card {#where-to-find-the-arazzo-card}

In the **Export** dialog, the **Arazzo** card is under **REST & HTTP** on the
**Target** step, as one `<name>.arazzo.yaml` file. Its badge is **lossless** for an item imported from
Arazzo (1.0 or 1.1) and **lossy** for an item of any other paradigm with operations: REST (OpenAPI,
WSDL, RAML), RPC (Thrift, Smithy) or GraphQL. For an item with nothing to sequence, such as a JSON
Schema set of types, the card is greyed out. Pick the card to set its options:

| Option | Default | What it does |
| --- | --- | --- |
| **Pretty Print** | On | Writes block-style YAML, one key per line. Turn it off for compact flow-style YAML. |
| **Arazzo Version** | Empty | The Arazzo version to write, `1.0.1` or `1.1.0`. Empty keeps the version the item was imported from; otherwise `1.1.0` when the item has an AsyncAPI source description and `1.0.1` when it does not. |

From the CLI, run `apiome export arazzo <item> --out <file>.arazzo.yaml`, and add
`--option pretty_print=false` or `--option arazzo_version=1.1.0`. The CLI prints the fidelity report:
the tier and preserved share, the counts, and the losses worst first, with the *workflows, not the
full API surface* warning among them. A lossy export exits non-zero unless you add `--force`, and
`--json` prints the tier. For an item with nothing to sequence, the CLI stops with the reason before
it starts an export. A public item's **Export** dialog on Browse offers Arazzo too, as the
`.arazzo.yaml` file.

#### Arazzo export checks

Before you download, Apiome checks the document:

1. **Schema** (`arazzo.schema`). A document Apiome built from a non-Arazzo item must pass the official
   Arazzo JSON Schema for the version it declares (1.0 or 1.1). Each problem names its location, such
   as `/sourceDescriptions`. A document that fails is not delivered.
2. **Re-import** (`arazzo.reimport`). Every document is read back through the Arazzo importer, the
   same way an upload is, and compared with the item.

An item imported from Arazzo is your own document, written back as it was read, so it is checked by
re-import only. Apiome reads some spellings the schema does not allow, such as `name` instead of
`workflowId`; those are listed in the round-trip report but do not block the export.

### API Blueprint from any source

#### When to export to API Blueprint

- **Publish human-readable docs.** A REST item becomes one Markdown `.apib` file people can read, with
  its resources, actions and MSON data structures. It is documentation, not a contract: validation
  rules MSON cannot express are left out, and the fidelity report lists each one. API Blueprint is no
  longer actively developed, so prefer OpenAPI for a machine-readable contract.
- **Round-trip an API Blueprint item.** An item imported from API Blueprint exports back **lossless**.

#### API Blueprint export at a glance

| Step | Where | Details |
| --- | --- | --- |
| **Pick** the API Blueprint card and its options | **Export** dialog → **REST & HTTP** → **API Blueprint** | [Where to find the API Blueprint card](#where-to-find-the-api-blueprint-card) |
| **See** how the document, resources and data structures are written | The fidelity report on the card | [How the item is written](#how-the-item-is-written-to-api-blueprint) |
| **See** what API Blueprint cannot carry | The fidelity report on the card | [What the fidelity report lists](#what-the-api-blueprint-fidelity-report-lists) |
| **Trust** the file: drafter, then re-import | Automatic before every download | [How an API Blueprint export is checked](#how-an-api-blueprint-export-is-checked) |
| **Export** from the CLI | `apiome export apiblueprint <item> --out <file>.apib` | [Where to find the API Blueprint card](#where-to-find-the-api-blueprint-card) |

Exporting to **API Blueprint** writes one `<Name>.apib` file in API Blueprint 1A: Markdown, with
its data structures in MSON. It is meant to be read by people, as documentation of the API, so it
writes what a reader needs and leaves out validation rules MSON cannot express.

#### How the item is written {#how-the-item-is-written-to-api-blueprint}

- **Document.** The `FORMAT: 1A` line and the first server as `HOST` come first, then the item's
  title and description.
- **Resources.** Each path is one resource (`## Pets [/pets/{petId}]`) with its path parameters.
  Each operation is an action with its name, method and description. Its query parameters go in the
  action's URI (`[GET /pets{?limit}]`) and are listed under **Parameters**. Its request and its
  responses, one per status code, name their media type and body (`+ Attributes (Pet)`). A body
  given as an inline JSON Schema is written as a `+ Schema` section.
- **Data structures.** Objects list their fields in order as MSON properties, such as
  `+ id (string, required) - Pet id.`. A default is a nested `+ Default:` line. Enums list their
  members, and an alias is a named type based on what it wraps.
- **Types.** MSON has three value types: `string`, `number` and `boolean`. A 64-bit integer becomes a
  `number`, and a date becomes a `string`.

#### What the fidelity report lists {#what-the-api-blueprint-fidelity-report-lists}

The fidelity report lists what API Blueprint cannot carry:

- validation rules: lengths, ranges, patterns and formats are marked **dropped** wherever they sit (a
  field, a parameter, a named scalar, an alias or an object), next to anything else about how that
  part is written;
- operations with no HTTP method and path (from gRPC, GraphQL or WSDL sources), event operations and
  channels, and a second operation on the same method and path;
- header and cookie parameters, status ranges such as `4XX`, and response headers and descriptions;
- every server but the first, server variables, the version, and the grouping into services;
- types MSON writes differently: wider numbers and dates as `number` and `string`, aliases, named
  scalars and maps as named types (marked **approximated**), and unions, which MSON lacks (marked
  **dropped**);
- deprecation flags, tags, and source details such as gateway routes;
- renamed types: MSON type names here are letters, digits and `_`, so `com.acme.Order` is written
  `com_acme_Order`.

An item imported from API Blueprint is written back as it was read. Import now also reads an
action's description, query parameters from the URI (`{?limit}`), a data structure's description,
`+ Default:` values, and property names in backticks.

#### How an API Blueprint export is checked {#how-an-api-blueprint-export-is-checked}

Each export is checked before you download it:

1. **drafter**, the API Blueprint parser, reads it when the server has it. A good blueprint has no
   warnings, so any drafter **error or warning** fails the export and names its code, line and
   column. Without drafter, the API Blueprint importer reads the document instead, and a parse error
   fails the export.
2. The document is then imported again. If it does not import, the export fails
   (`apiblueprint.reimport`).

An item imported from API Blueprint exports and re-imports unchanged. From any other source, the
re-import shows what API Blueprint could not keep; the fidelity report names those losses.

#### Where to find the API Blueprint card {#where-to-find-the-api-blueprint-card}

In the **Export** dialog, the **API Blueprint** card is under **REST & HTTP** on
the **Target** step, as one file. Its badge is **lossless** for an item imported from API Blueprint and
**lossy** for any other source. On the **Fidelity** step, the export is described as one for
human-readable docs, and the report lists each constraint MSON cannot express (`format`, `minimum`,
`maximum`, exclusive bounds) as dropped. Pick the card to see its three options: **Format Version**
(`1A`, the `FORMAT` line), **Include Comments** (on by default), which writes the generated-file comment
under the title, and **Media Type** (`application/json` by default), for a request body whose item
names none. From the CLI, run `apiome export apiblueprint <item> --out <file>.apib`, and add
`--option include_comments=false` or `--option media_type=application/xml`. The CLI prints the
dropped constraints. A lossy export exits non-zero unless you add `--force`, and `--json` prints the
tier. A public item's **Export** dialog on Browse offers API Blueprint too, as the `.apib` file.

| Format | Kind | Exports from |
| --- | --- | --- |
| Apache Avro | Data schema | Any source |
| Apache Thrift | RPC | Any source |
| API Blueprint | REST | Any source |
| Apigee API proxy | REST | Any source |
| Arazzo | REST | A source with an operation to sequence |
| ASN.1 | Data schema | Any source |
| AsyncAPI 3.1 | Events | Any source |
| AWS API Gateway | REST | Any source |
| Azure API Management | REST | Any source |
| Bruno | REST | Any source |
| Cap'n Proto | RPC | Any source |
| CDDL | Data schema | Any source |
| CloudEvents | Events | Any source |
| COBOL Copybook | Data schema | Any source |
| Connect RPC | RPC | Any source |
| CORBA IDL | RPC | Any source |
| EDI X12 | Data schema | A source imported as EDI X12 |
| Envoy xDS RouteConfiguration | REST | Any source |
| FHIR | REST | Any source |
| FIX | Data schema | A source imported as FIX |
| FlatBuffers | Data schema | Any source |
| Gateway API HTTPRoute | REST | Any source |
| Google API Discovery | REST | Any source |
| GraphQL SDL | Graph | Any source |
| HL7 v2 | Data schema | A source imported as HL7 v2 |
| HL7 v2 segment guide | Data schema | Any source with a record type |
| Hoppscotch | REST | Any source |
| HTTP Request File | REST | Any source |
| Insomnia | REST | Any source |
| ISO 20022 | Data schema | A source imported as ISO 20022 |
| ISO 8583 | Data schema | A source imported as ISO 8583 |
| Istio VirtualService | REST | Any source |
| JSON Schema | Data schema | Any source |
| JSON Type Definition | Data schema | Any source |
| Kafka Connect Schema | Data schema | Any source |
| Kong Declarative Config | REST | Any source |
| Kubernetes CRD | Data schema | Any source |
| LLM Tool Definitions | Agent tools | Any source |
| MCP Tool Definitions | Agent tools | A source with an operation an agent can call |
| OData | REST | Any source |
| ODCS Data Contract | Data schema | Any source |
| ONC RPC | RPC | Any source |
| OpenAPI 3.1 | REST | Any source |
| OpenRPC | RPC | Any source |
| Postman | REST | Any source |
| Protocol Buffers (proto3) | RPC | Any source |
| RAML | REST | Any source |
| SAP IDoc | Data schema | A source imported as SAP IDoc |
| Smithy | RPC | Any source |
| SQL DDL | Data schema | Any source with a record type |
| Thunder Client | REST | Any source |
| Traefik dynamic configuration | REST | Any source |
| TypeSpec | REST | Any source |
| UN/EDIFACT message guide | Data schema | Any source with a record type |
| WADL | REST | Any source |
| WIT (WebAssembly) | RPC | Any source |
| WSDL | REST | Any source |
| X12 implementation guide | Data schema | Any source with a record type |
| XML-RPC | RPC | A source with an RPC operation |
| XSD | Data schema | Any source |
| z/OS Connect | REST | A source imported as z/OS Connect |

---

## With the CLI

[Export from the CLI](./export-from-the-cli.md) walks through `apiome export` end to end: every format,
the fidelity report, and gating a CI job on it.

```bash
# OpenAPI (default), JSON, to a file
apiome spec export --project <id-or-slug> --version <id-or-label> --output petstore.json

# YAML
apiome spec export --project <id-or-slug> --version <id-or-label> --yaml -o petstore.yaml

# Exporting to another format (AsyncAPI, GraphQL, Proto3, Avro, …)? Check what will be
# preserved — and why anything changes — before you generate:
apiome export targets  --project <id-or-slug> --version <id-or-label>
apiome export evidence --project <id-or-slug> --version <id-or-label> --target avro

# Arazzo workflow document instead of OpenAPI
apiome spec export --project <id-or-slug> --version <id-or-label> --format arazzo -o flows.json
```

Use `-o -` to stream to stdout. `--format` accepts `openapi` (default) or `arazzo`.

### Download Arazzo or JSON Schema by slug

`apiome schema arazzo` and `apiome schema json` take the published version as one
`tenant/project/version` argument (slugs, as in the REST route) and write to stdout by default,
so they suit a redirect, a pipe or a build step. They share the same flags; only the default
`--format` differs — **yaml** for Arazzo, **json** for JSON Schema.

```bash
# JSON Schema (2020-12) bundle, every class
apiome schema json acme-corp/payments-api/2.1.0 > schema.json

# One class's schema, straight into a code generator
apiome schema json acme-corp/payments-api/2.1.0 --class Charge \
  | npx quicktype --src-lang schema --lang go > charge.go
```

The JSON Schema is streamed exactly as the server emits it (`$schema:
https://json-schema.org/draft/2020-12/schema`); the CLI does not transform it.

```bash
# Full Arazzo bundle
apiome schema arazzo acme-corp/payments-api/2.1.0 > workflows.arazzo.yaml

# One class's workflow (the per-class route)
apiome schema arazzo acme-corp/payments-api/2.1.0 --class Charge > charge.arazzo.yaml

# JSON instead of YAML, written to a file
apiome schema arazzo acme-corp/payments-api/2.1.0 --format json --output workflows.arazzo.json

# Pin the exact bytes in CI: exit 6, and nothing written, if the document changed
apiome schema arazzo acme-corp/payments-api/2.1.0 -o workflows.arazzo.yaml \
  --expect-sha256 <sha256-from-a-first-run>
```

| Flag | What it does |
|---|---|
| `--class NAME` | Download only that class's workflow or schema. An unknown class exits 2. |
| `--format json\|yaml` | Serialization. Default **yaml** for `schema arazzo` (the usual form for Arazzo), **json** for `schema json`. |
| `--output FILE`, `-o` | Write to a file. Default `-`, stdout. |
| `--expect-sha256 HEX` | Compare the document's SHA-256 first; on a mismatch print both digests, write nothing and exit **6**. A `sha256:` prefix is accepted. |

The document is written byte for byte as the server sent it. A summary — bytes written, format and
`Checksum: sha256:…` — goes to stderr, so copy the checksum from a first run into
`--expect-sha256`. With the global `--json`, the summary is one JSON object: on stdout when the
document goes to a file, on stderr when the document goes to stdout.

The version must be published. An unknown or unpublished version, or a private one without an API
key, exits 2; set `APIOME_API_KEY` for private versions. No tenant configuration is needed — the
tenant is in the argument.

## With the REST API

```http
GET /v1/schema/{tenant_slug}/{project_slug}/{version_slug}
Accept: application/json          # default; use application/yaml for YAML
```

Other representations of the same version:

| Format | Route |
|---|---|
| OpenAPI | `GET /v1/schema/{tenant}/{project}/{version}` |
| Arazzo | `GET /v1/arazzo/{tenant}/{project}/{version}` (one class: append `/{class}`) |
| JSON Schema | `GET /v1/json/{tenant}/{project}/{version}` (one class: append `/{class}`) |

For private versions, pass an in-scope API key via the `X-API-Key` header (or the `api_key` query
parameter).

Every export runs as a job: [How an export runs](./export-jobs.mdx) covers the pipeline, the job
states, the transcoding guard and the failure codes.

### Export to several formats in one job

To publish a version in several formats at once, send one export job with a `targets` list instead
of a single `target`. Apiome emits the version to every listed format and hands back **one zip**.

```http
POST /v1/export/{tenant_slug}/jobs
{
  "artifact": "<project-id>",
  "version": "1.0.0",
  "targets": [
    { "target": "openapi" },
    { "target": "graphql" },
    { "target": "protobuf", "options": { "package": "acme.payments.v1" } }
  ]
}
```

1. The `202` response carries a `status_path`. Poll it until `state` is `completed` or `failed`.
2. Download the zip from `result.download_path`. Each format sits in its own folder, named after
   the resolved format key (`openapi-3.1/`, `graphql/`, …), and a root `manifest.json` lists
   every folder, its files, its fidelity tier and the version that produced it.
3. Read the fidelity on the job result:
   - `result.targets[]` has one entry per format, in the order you sent them: its full fidelity
     report, transcoding guard, validation report, delivery decision and the files it added to
     the zip.
   - `result.fidelity_rollup` sums them up: the worst tier, the lowest and average preserved
     share, how many formats landed in each tier, and which formats are lossy or need
     confirmation.

| Rule | Behavior |
|---|---|
| `target` vs `targets` | Send one or the other. Mixing them, or putting `options` / `acknowledged_snapshot` at the top level next to `targets`, is rejected with `422`. |
| Per-format settings | `options` and `acknowledged_snapshot` go on each `targets` entry. |
| How many | Up to 16 entries in `targets`. Two entries that resolve to the same format (`openapi` and `openapi-3.1`) are rejected with `400`. |
| `dry_run: true` | Every format's fidelity report and the rollup, no zip. |
| Severe conversions | If any format needs confirmation, the job fails with `TRANSCODE_CONFIRMATION_REQUIRED` before anything is generated. Resubmit with `"confirm": true`. |
| Failures | All or nothing: the first format that fails fails the job, and `error.context.target` names it. No zip is kept. |
| Attestation | Each format is attested separately against the zip. Fetch one with `GET …/jobs/{job_id}/attestation?target=<format key>`. |

The same rules for snapshots and acknowledgements apply to each format; see
[Understand export fidelity](./export-fidelity.md#snapshots-and-the-risk-acknowledgement).

### Export a whole project or several versions in one job

To export more than one version of a project, send one export job with a `versions` list (version
labels or revision ids) or `"all_versions": true` instead of `version`. Every version is exported
to every target you name, and you get back **one zip**.

```http
POST /v1/export/{tenant_slug}/jobs
{
  "artifact": "<project-id>",
  "versions": ["1.0.0", "1.1.0", "2.0.0"],
  "targets": [
    { "target": "openapi" },
    { "target": "graphql" }
  ]
}
```

Each version × format pair is an **item**. An item that fails does not stop the others.

1. The `202` response carries a `status_path`. Poll it until `state` is `completed` or `failed`.
2. Read `result.batch` on the completed job:
   - `completed_count` and `failed_count` say how many items made it into the zip.
   - `items[]` has one entry per item: its version, format, `state`, folder in the zip, fidelity
     tier and preserved share, delivery decision, files, and, for a failed item, an `error` with
     the same `code`, `message` and `remediation` a failed single export carries.
   - `result.fidelity_rollup` sums up the fidelity of the completed items.
3. Download the zip from `result.download_path`. Each completed item sits in a
   `<version>/<format>/` folder (`1.0.0/openapi-3.1/`, `1.0.0/graphql/`, …). The root
   `manifest.json` lists every item, including the failed ones and why they failed.

| Rule | Behavior |
|---|---|
| Choosing versions | Send `versions` (up to 50 distinct entries) or `"all_versions": true`, never together and never with `version`. `all_versions` takes every version of the project, newest first. |
| Formats | Use `target` (with `options`) for one format, or a `targets` list for several. |
| How many | Up to 100 items (versions × formats). A longer `versions` list is rejected with `422`; an `all_versions` job over a bigger project fails with `EXPORT_BATCH_TOO_LARGE`. |
| Snapshots | `acknowledged_snapshot` is not accepted: a snapshot describes one version. Preview a version on its own to acknowledge it. |
| Failures | Per item. A version that does not exist, a format that fails, a severe conversion without `"confirm": true` or a blocked delivery fails only that item, and the job still completes. The job fails with `EXPORT_BATCH_FAILED` only when every item failed; `error.context.items` lists each one. |
| Same version twice | A label and its own revision id count as one version; the second is skipped with a `BATCH_VERSION_DUPLICATE` warning. |
| `dry_run: true` | Every item's fidelity tier and the rollup, no zip. |
| Attestation | Each completed item is attested against the zip. Fetch one with `GET …/jobs/{job_id}/attestation?version=<version>&target=<format key>`. |

### Export several items in one job

To export several catalog items or projects at once, send `items` instead of `artifact`. Each entry
names an `artifact` and, optionally, a `version`; without one the item's latest version is exported.

```http
POST /v1/export/{tenant_slug}/jobs
{
  "items": [
    { "artifact": "<orders-item-id>" },
    { "artifact": "<pets-item-id>", "version": "1.0.0" }
  ],
  "targets": [{ "target": "openapi" }]
}
```

It runs as a batch, so everything above applies: each item × format pair succeeds or fails on its
own, `result.batch.items[]` reports each one (now with its `artifact`), and you get back one zip.

- Each item's files sit in a folder named after the item's slug: `orders-api/openapi-3.1/`. An item
  that names a version adds the version: `pets-api-1.0.0/openapi-3.1/`.
- The root `manifest.json` gives each item's `artifact`, and `artifact_count` says how many distinct
  items the job covered.
- `items` cannot be combined with `artifact`, `version`, `versions` or `all_versions`. Entries must be
  distinct, and the job runs at most 100 item × format pairs. A request that breaks a rule is
  rejected with `422`.

The Catalog's bulk **Export…** and `apiome export <format> --items` send this request for you.

### From the CLI: several formats or several items

`apiome export <format>` exports through the same job pipeline. Two flags turn it into one job that
writes one archive. They work for every format with no dedicated command; `openapi`, which has one,
can still be one of the `--targets`.

```bash
# One version to three formats: a folder per format
apiome export graphql payments-api --targets openapi,avro --out exports/

# Three catalog items, each at its latest version (or ITEM@VERSION), to one format
apiome export graphql --items orders-api,pets-api@1.0.0,events-bus --out exports.zip
```

| Flag | Behavior |
|---|---|
| `--targets FORMAT,…` | More formats after `<format>`, in one all-or-nothing job. `--option` applies to `<format>` only; the other formats use their defaults. |
| `--items ITEM[@VERSION],…` | Ids or slugs, instead of `ARTIFACT`. Runs a batch job; `--version` does not apply (use `@VERSION`). |
| `--out` | A directory to unpack into, or a `.zip` path. `-` (stdout) is refused. |

The command prints one row per item × format, with its state, fidelity tier and folder (or error).
It exits **0** when every item completed, **7** when the archive was written but some items failed,
and **1** when every item failed. `--min-grade` and `--fail-on` gate a single export, so they are
refused with these flags.

### Apply overlays when you export

An [OpenAPI Overlay](../bring-in/overlays.md) changes the exported document without changing the
version: a partner's servers, public descriptions, `x-` extensions. Send the overlays with the job,
in the order they should apply:

```http
POST /v1/export/{tenant_slug}/jobs
{
  "artifact": "<project-id>",
  "version": "1.0.0",
  "target": "openapi",
  "overlays": [
    { "name": "partner.yaml", "document": { "overlay": "1.0.0", "info": { "title": "Partner", "version": "1" },
      "actions": [{ "target": "$.servers", "update": [{ "url": "https://partner.example.com" }] }] } }
  ]
}
```

- The overlays apply to the version's OpenAPI document **before** anything else runs. Fidelity, the
  emitter, validation and the export quality policy all judge the overlaid document, and the
  delivery grade recorded for the export is the overlaid document's.
- `result.overlay` lists what changed: `applied` (the overlays, in order), `ledger` (one row per
  changed value — `pointer`, `kind`, the `overlay` that changed it; at most 500 rows, then one row
  saying how many more changed), `changes` and `findings`. An action whose target matches nothing is
  an `overlay.unmatched-target` finding, and the document is left as it was. The job also logs an
  `OVERLAYS_APPLIED` event and one `OVERLAY_FINDING` warning per finding.
- Send the same `overlays` to `POST /v1/export/{tenant_slug}/verify`, so the verify snapshot you
  acknowledge matches the job's.
- At most 10 overlays, each at most 1 MiB. They work with one `target` or a `targets` list, but not
  with a batch (`versions`, `all_versions` or `items`), because an overlay is written for one
  document.
- A version imported from another format fails with `OVERLAY_SOURCE_UNSUPPORTED`. An overlay with an
  unsupported revision or no `actions` fails with `OVERLAY_INVALID`.

From the CLI, add `--overlay FILE` (JSON or YAML), once per overlay:

```bash
# OpenAPI with a partner's servers and descriptions (runs as a job; writes JSON)
apiome export openapi --project payments-api --version 1.0.0 -o partner.json \
  --overlay base-public.yaml --overlay partner.yaml

# Any other format, or several formats at once
apiome export openapi-3.1 payments-api --out exports/ --targets avro --overlay partner.yaml
```

The command prints `Overlays: applied … — N value(s) changed` and one line per finding. `--overlay`
cannot be combined with `--items`, or with `--yaml` on `export openapi`.

## Limits

Every export job runs inside these limits. A request that hits one is refused with a message naming
the limit, so you know what to change. An administrator can change each one with the setting shown;
`0` turns a limit off.

| Limit | Default | When it is hit | Setting |
|---|---|---|---|
| Jobs running at once, per workspace | 5 queued or running | A new job is refused with `429` until one finishes or is cancelled | `APIOME_EXPORT_MAX_CONCURRENT_JOBS_PER_TENANT` |
| How long one job may run | 30 minutes | The job stops and fails with `EXPORT_JOB_TIMED_OUT` | `APIOME_EXPORT_JOB_TIMEOUT_SECONDS` |
| Size of the download | 32 MiB | The job fails with `EXPORT_ARTIFACT_TOO_LARGE` | `APIOME_EXPORT_ARTIFACT_MAX_BYTES` |
| Items in one batch | 100 items × formats; 50 versions; 16 entries in `targets` | The request is refused with `422`, or an `all_versions` job fails with `EXPORT_BATCH_TOO_LARGE` | Fixed |
| How long a download is kept | 24 hours | The download answers `410 Gone`; run the export again | `APIOME_EXPORT_ARTIFACT_RETENTION_HOURS` |

Every member's jobs count toward the workspace's five. A download past its retention time is
deleted, not just hidden. The job itself stays in the job list (`GET /v1/export/{tenant_slug}/jobs`)
until it is cleared: 7 days after it finished or was cancelled, 30 days after it failed.

### File names in a download

File and folder names in a download come from your source: the API's title, a type's name, an Avro
namespace. Apiome keeps every name inside the download. A name that would leave the folder you
unpack into (one starting with `/` or a drive letter, or containing `..` or `\`) is rewritten to
stay inside it: an Avro namespace `com.acme` becomes the folders `com/acme`, and parts that are not
legal Avro names become `_`. A file name in any script, such as `注文-api.jtd.json`, keeps its
characters when you download it. Every download is sent as an attachment, and browsers are told not to guess its type.

## Verify

The exported document is valid OpenAPI and contains the classes and paths you edited. The
[Golden Path](https://github.com/apiome/apiome/blob/main/docs/GOLDEN_PATH.md) does exactly this — it exports via the real CLI and re-validates the
downloaded document with `openapi-spec-validator`.

## Test-drive it

For OpenAPI targets, the [Export studio](./export-studio.mdx)'s Review step can turn the artifact you just generated into
a **live mock** for a few minutes — a base URL you can `curl`, responses generated from
the document's own response schemas, and a log of everything it served. It is the strongest check
available: a document that cannot answer its own operations is a finding no static validation would
surface.

```http
POST /v1/export/{tenant_slug}/mock
{ "artifact": "<project-id>", "version": "1.0.0", "target": "openapi" }
```

The mock expires by itself, and servers without the Mock Server deployed report the capability as
unavailable rather than offering a button that cannot work. See
[export_mock_test_drive.md](https://github.com/apiome/apiome/blob/main/apiome-rest/docs/export_mock_test_drive.md) for the endpoints,
the lifetime rules and the configuration, and [Mock try-out](./mock-try-out.mdx#test-drive-an-export) for the panel.

## Related

- [Supported formats](../bring-in/supported-formats.md) — every format Apiome imports and exports,
  generated from the registries
- [Export studio](./export-studio.mdx) — the same export step by step, with verify and a job
- [Export catalog items](./export-catalog-items.mdx) — one item or many, every target's fidelity tier
- [Understand export fidelity](./export-fidelity.md) — cross-format exports: what is preserved,
  what is lost and why, and the risk acknowledgement
- [Export to an API gateway](./export-to-a-gateway.md) — Kong, Gateway API, Envoy, Istio, Traefik,
  AWS API Gateway, Azure API Management and Apigee configuration
- [Export to an API client](./export-to-an-api-client.md) — Hoppscotch and Thunder Client
  collections, with their environments
- [Browse published specs](./browse-published-specs.md) — view the same spec rendered
- [Compare published versions](./compare-published-versions.md) — diff two published versions
  with `apiome schema diff`
- [CLI quick-start](../reference/cli-quickstart.md) — full CLI reference
