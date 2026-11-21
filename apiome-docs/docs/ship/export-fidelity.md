---
title: "Understand export fidelity"
description: "See what an export preserves, changes or loses, and why, before generating."
sidebar_position: 6
tags: [export]
---

When you export a version or catalog item to another format (OpenAPI 3.1, AsyncAPI 3,
GraphQL SDL, Proto3, Avro, …), apiome predicts **before generation** what will be
preserved, what will change, and what will be lost — and shows you *why*, per construct,
with a link to the destination format's official documentation when the limitation is
the format's own. This page explains how to read that evidence and how the risk
acknowledgement works.

> **Rule of thumb:** the one-word tier is a triage badge, not a guarantee. Always check
> the projection map (or the `export evidence` table) before relying on a lossy or
> types-only export — and even a `lossless` badge only covers the constructs apiome
> could analyze (see [Unavailable evidence](#unavailable-evidence)).

---

## Quality tiers

Every target card shows a coarse fidelity tier plus a preserved-% estimate:

| Tier | Meaning |
|---|---|
| `lossless` | Every analyzed source construct is carried faithfully. |
| `lossy` | Some constructs are approximated, reframed, or dropped. |
| `types-only` | A schema-only target keeps type definitions and drops all operations/channels. |

**A tier alone never proves full preservation.** It is computed from construct
*categories*, so two `lossy` exports can differ enormously, and constructs apiome could
not inspect (`unavailable`) are not "preserved" — they are unknown. Use the
per-construct evidence below to see exactly what happens to your API.

## Target readiness (the pre-flight ranking)

The target grid does not just badge each target — it **ranks** them by expected outcome,
before any job runs. The ranking comes from the export pre-flight
(`POST /v1/tenants/{tenant}/export/preflight`), which lints the **source** under your
tenant's style guide and then, per target, mixes three things into one score:

| Input | What it answers |
|---|---|
| Projected fidelity (preserved %) | How much of this source survives the trip? |
| Source lint score | How good is the thing you are exporting in the first place? |
| Capability fit | Can the target carry the *kinds* of construct this source is made of? |

Each card then falls into a band, and the grid sorts by band first:

| Band | Meaning |
|---|---|
| `ready` | Go. Good fidelity, no policy shortfall. |
| `check first` | Usable — read the rationale before you commit. |
| `blocked` | Your tenant's export quality policy refuses this delivery. The card stays visible with the reason; it cannot be selected until the shortfall is fixed or waived. |
| `unavailable` | The emitter's toolchain is not installed in this runtime. |

Every card carries a one-line **rationale** ("Type shapes only: 50% preserved, 5
constructs dropped. Source grade B. Apache Avro cannot carry operations.") and the grid
prints the source's own grade above it. Prefer another order? The **Sorted by
readiness / Sorted by name** toggle restores the original registry ordering.

The ranking is deterministic for a fixed source revision, style guide, and policy — the
report's `ranking_fingerprint` is a stable hash of it — and the pre-flight emits nothing:
no job, no artifact. The fidelity numbers it shows are the same ones the eventual job
attaches to its result.

Quality floors and waivers are configured per tenant in the
[import & export quality policy](../govern/style-guides.mdx#import--export-policy) on **Govern →
Style guides** (or over the [REST API](../reference/rest/governance.md#put-quality-policy-v1-tenants-tenant-slug-governance-quality-policy-put));
see [Import a specification](../bring-in/import-a-spec.md) for how the same policy gates intake.

## The projection map (graph + table)

The quick **Export** dialog (Fidelity step) and **Export studio → Verify**
(`/ade/dashboard/export/studio`) both render a **Projection map**: a three-column
diagram from **source/native construct → canonical model → destination location**,
banded into *in-destination*, *omitted*, and *unavailable* lanes, with a synchronized
table underneath. Graph and table are rendered from the same server evidence, so their
counts always agree — if you prefer the table (or use a screen reader), you lose
nothing.

- **Select any node or row** (pointer, or keyboard: arrow keys / Home / End, Enter or
  Space to open, Escape to reset the view) to open the **evidence drawer**: the
  construct, its status and severity, the cause category, the reviewed explanation, the
  destination location when one exists, and a documentation link when applicable.
- **Status is readable without color** — every outcome carries a text label and symbol.
- **Large exports aggregate**: above a documented threshold, clean (`retained`,
  info-severity) rows collapse into expandable groups. Dropped, unavailable,
  approximated, synthesized, and warning/critical rows are **never** aggregated away.
  Use **Load more evidence** to page in the rest; the summary chips always show the
  full status counts from the manifest, even before every page is loaded.

## Statuses: the fate of each construct

| Status | Meaning | Example |
|---|---|---|
| `retained` | Meaning represented without material change. | An object schema becomes an Avro record. |
| `transformed` | Meaning survives a documented target transformation. | A REST operation becomes a GraphQL mutation. |
| `approximated` | A related construct exists, but not all semantics are kept. | A validation constraint emitted as documentation text. |
| `synthesized` | apiome invented content the target's conventions require. | A Proto3 field number assigned to a field that never had one. |
| `dropped` | The construct is not emitted at all. | HTTP paths in a format with no path concept. |
| `unavailable` | apiome could not reliably inspect the source data. | A detail the parser did not capture. |
| `not-applicable` | The construct does not apply to this target or source. | "No event channels exist in this source." |

## Reasons: *why* it happened, and what to do

Every non-preserved status carries exactly one cause category. The wording is reviewed
so a destination-format limit is never blamed for an apiome-side gap (and vice versa):

| Reason code | Category label | Whose limitation | What you can do |
|---|---|---|---|
| `destination_unsupported` | Destination limit | The target format's specification | Choose a destination that supports the construct, or accept the loss. This is the **only** category that shows a destination-format documentation link. |
| `emitter_unsupported` | Not yet emitted | apiome's emitter (the format could carry it) | Track emitter support; not a format limit. |
| `source_incomplete` | Source incomplete | Your source definition | Complete the source and re-export. |
| `source_parse_limit` | Parser limit | apiome's parser | The source data itself may be intact; apiome cannot determine its fate. |
| `option_excluded` | Option excluded | An export option you selected | Change the option and preview again. |
| `security_redacted` | Redacted | A security/privacy policy | Adjust the redaction policy if the construct should export. |
| `target_tool_unavailable` | Toolchain unavailable | The runtime's missing external tool | Install/enable the destination's toolchain and re-export. |
| `not_applicable` | Not applicable | Nobody | No action needed. |

## Severity and the advisory

Every loss also has a **severity**, independent of its status, that says how much you should care:

| Severity | Means |
| --- | --- |
| `info` | Cosmetic or metadata only; safe to ignore (a description written as a comment). |
| `warn` | A meaningful degradation; review it (a validation rule the target cannot express). |
| `critical` | A semantic loss: the export may not behave like the source (a union with no form in the target, an operation that cannot be written). |

From the counts and the worst severity, Apiome writes one **advisory** — *“Exporting to Protobuf may
lose some fidelity. The destination format can't represent everything in this API, so 7 constructs
will be dropped or approximated — review the fidelity report before downloading.”* The Export dialog,
the Export studio, Browse, the CLI and the [MCP tools](./export-over-mcp.md) all show this same
sentence, word for word, so the warning never reads differently in two places. It is hidden for a lossless export, and when any loss is `critical` it
also asks for an explicit acknowledgement before you continue. The REST API returns
it as `advisory` on every preview and export (`show`, `severity`, `requires_ack`, the counts,
`headline` and `message`); pass `min_severity` to raise it only for `warn` or `critical` losses.

## Validation rules from Protovalidate {#protovalidate-rules}

A Protobuf source can carry [Protovalidate](https://protovalidate.com/) rules (`buf.validate`
options). On import the standard rules become ordinary validation constraints; the rest are kept as
written on their field or message
([the rule table](../bring-in/catalog-format-details.md#protobuf-protovalidate-rules)). What each
target does with them:

| Target | Standard rules with a constraint (`min_len`, `pattern`, ranges, `in`, item counts, `required`) | Rules kept as written (`prefix`, `defined_only`, timestamp and duration bounds, …) | CEL expressions |
| --- | --- | --- | --- |
| **Protocol Buffers (proto3)**, **Connect RPC** | Written back as `buf.validate` rules: *retained* | Written back unchanged: *retained* | Written back unchanged, never evaluated |
| **JSON Schema**, **OpenAPI** and other targets with validation keywords | Written as keywords (`minLength`, `pattern`, `minimum`, `enum`, `required`, …) | *Approximated*: the report names each rule that was not carried | *Approximated*: named in the report, not carried |
| Targets with no validation keywords | *Approximated*, as for any other constraint | *Approximated* | *Approximated* |

The rule is symmetric: every constraint the Protobuf import reads from a rule, the Protobuf export
writes as that rule. The same holds for constraints that came from somewhere else. An OpenAPI
`minLength: 3` exported to Protobuf is written as `(buf.validate.field).string.min_len = 3`. A
constraint with no standard rule for the field's type (`multipleOf`, a `date-time` format) is
reported as *dropped*, by name. To export without Protovalidate rules, see
[Validation rules in a Protobuf export](./export-a-spec.md#protovalidate-rules).

## Check the prediction with a round trip

The report is a **prediction**, made before anything is written. To test it, run a round trip: Apiome
exports the source, reads the file back and compares the result with the source, then says whether
the report explained every difference. Each difference it did not predict is listed, as is each
predicted drop that did not happen. See
[Check a round trip](./export-studio.mdx#check-a-round-trip) in the Export studio, and
[Measured loss from the API](./export-studio.mdx#measured-loss-from-the-api) for the `measurement`
the REST API returns.

## OpenAPI exports {#openapi}

An item imported from OpenAPI 3.0, 3.1 or 3.2 and exported as OpenAPI at the same version comes back
as it was read. Apiome keeps a copy of each imported operation and schema, and of the document's
other parts. These include callbacks, links, webhooks, `discriminator`, `x-` extensions,
`externalDocs`, examples, `$self`, `jsonSchemaDialect`, `$dynamicRef`, `itemSchema`, streaming media
types, `QUERY` and custom methods, and tag `parent` and `kind`. The export writes that copy back.
The [OpenAPI construct matrix](../reference/openapi-construct-matrix.md) lists every construct and
version, measured on the OpenAPI Initiative's own test documents.

| You export | To | What the report says |
| --- | --- | --- |
| An item imported from OpenAPI | The **same** OpenAPI version | Nothing is lost. |
| An item imported from OpenAPI 3.0 | **OpenAPI 3.1** or **3.2** | Nothing is lost. Schemas are rewritten into JSON Schema 2020-12 (`nullable: true` becomes a `"null"` type), and each rewritten schema is listed. A `nullable` beside a `$ref` is listed as a loss, because 3.0 ignored it. |
| An item imported from OpenAPI 3.1 or 3.2 | **OpenAPI 3.0** | Each construct 3.0 cannot hold is **dropped** and listed: `webhooks`, `jsonSchemaDialect`, `$dynamicRef`, `$anchor`, keywords beside a `$ref`, and the 3.2-only constructs. A declared dialect other than the OpenAPI default (draft-07, say) is named in the report. |
| An item imported from OpenAPI 3.2 | **OpenAPI 3.1** | Each 3.2-only construct is **dropped** and listed: `$self`, `itemSchema`, `in: querystring` parameters, server `name`, response `summary`, tag `parent` and `kind`. |
| An item imported from OpenAPI | **Swagger 2.0** | The file is built from the canonical model, and the report says the OpenAPI 3.x constructs are not written. |
| An item imported from another format (RAML, Postman, gRPC, GraphQL, an agent card, a JSON Schema, …) | **OpenAPI** | `lossy`. The file is built from the canonical model, and the report lists what that changes. See [Exports from another format](#cross-format). |
| An item imported from AWS API Gateway or Azure API Management | **OpenAPI** | `lossy`. The gateway's own extensions (`x-amazon-apigateway-*`) are written back as they were read. The report says an OpenAPI reader does not read them back as integrations, backends or policies. |

### Schema dialects {#schema-dialects}

OpenAPI 3.0 schemas use their own subset of JSON Schema: `nullable: true` instead of a `"null"`
type, and `exclusiveMinimum: true` beside `minimum` instead of a number. OpenAPI 3.1 and 3.2
schemas are JSON Schema 2020-12. A 3.1 or 3.2 document can choose another dialect with
`jsonSchemaDialect`, and one schema can choose its own with `$schema`.

- **Import** keeps the dialect each schema was written in. The JSON Schema Apiome builds for
  validation names it.
- **Export across versions** rewrites schemas between the two forms. Each rewritten schema is
  listed, and each rewrite that changes meaning is listed as a loss.
- **Round trip:** a 3.0 document exported as 3.1, then 3.2, then 3.0 again comes back as it was.
  Every change on the way is listed. A default flag such as `exclusiveMinimum: false` is not
  written back.

An operation or schema edited after import is exported from its current version. The fields
Apiome has no other place for are still written, and the report lists the edited operation or
schema, because detail inside the changed fields may be missing.

## Arazzo exports {#arazzo}

Arazzo describes workflows, not APIs, so its report says what a workflow can and cannot hold. When
you read an Arazzo file back, each step is named `<workflow>#<step>`, for example
`orders#POST /orders`. The report predicts those names, so every difference a round trip finds is
listed in the report.

| You export | To | What the report says |
| --- | --- | --- |
| An item imported from Arazzo 1.0 or 1.1 | **Arazzo** | `lossless`. Workflows, steps, inputs, outputs, `components`, workflow `parameters` and the 1.1 fields (`$self`, and `channelPath`, `action`, `correlationId` and `timeout` on steps) are written back as read. Choosing **Arazzo Version** `1.0.1` for a 1.1 item drops `$self`, and the report says so. |
| A REST, RPC, GraphQL or agent item | **Arazzo** | `lossy`. Each operation becomes a step (**approximated**). Its own key is **dropped** and the step's key is **synthesized**. Each service becomes a workflow (**approximated**). Types, channels, agents and skills are **dropped**. Two operations of one service that would share a step id can't both be written, so the first is **dropped**. |
| A set of types or an event API | **Arazzo** | Not offered. There is no operation to sequence, and the card says so. |
| An item imported from Arazzo | A gateway, API client, API Blueprint or Google Discovery | Not offered. These targets need an HTTP method and path, and a workflow step has neither. |
| An item imported from Arazzo | Arrow, COBOL copybook, FIX Orchestra, Kafka Connect, ODCS, SQL DDL or xRegistry | Not offered. These targets need a record type or an event, and an Arazzo item has neither. (The COBOL copybook card is offered, but the export stops with that reason.) |
| An item imported from Arazzo | EDI X12, FIX, HL7 v2, IDoc, ISO 20022, ISO 8583 or z/OS Connect | Not offered. These targets need details that only an import of that same format records. |
| An item imported from Arazzo | Any other target, such as OpenAPI, Protobuf or GraphQL | `lossy`. The steps become the target's operations, and the report names the key each one is written under — `POST /checkout#pay` in OpenAPI, `checkout.pay` in Protobuf. See [Exports from another format](#cross-format). A target whose file Apiome cannot read back yet is tracked in [#7054](https://github.com/apiome/apiome/issues/7054). |

Apiome checks Arazzo import and export against documents it didn't write. These include the OpenAPI
Initiative's 1.0.0 examples and 1.1.0 schema fixtures, and Arazzo files from Redocly, Spectral and
Specmatic. Each must pass the official schema, import, and export back unchanged. The set covers
`$components` references, runtime expressions, `querystring` parameters and `channelPath` steps.

## Exports from another format {#cross-format}

An export to a format other than the one the item was imported from changes things that belong to
no single operation or type. The report lists each of them, so it never says "nothing lost" about
a file that reads back differently.

| The report says | When | Status and severity |
| --- | --- | --- |
| *"OpenAPI 3.1 describes REST APIs; this agent API is written in REST terms and reads back as a REST API"* | The target describes another kind of API than the source: an agent card to OpenAPI, a data schema to GraphQL, a REST API to Protobuf. | **approximated**, `warn`, on the document |
| *"… operation 'Wallet.getBalance' is written as 'POST /Wallet/getBalance' and reads back under that key"* | The target can only write an operation, a type or a service under another name. The source's key is **dropped** and the new key is **synthesized**, as for [Arazzo](#arazzo). An operation whose line already says how it is reframed (a REST operation written as a GraphQL field) is not listed a second time. | **dropped** + **synthesized**, `info` |
| *"OpenAPI 3.1 has no field for the apigee metadata of this operation (apigee, cors, rate_limits); it is not written"* | The source format records details the target has no field for: a gateway's routes and policies, a dbt model's tags, an API client's saved samples. | **dropped**, `info` |
| *"CDDL has no place for the document's title 'X12 850' and namespace 'X12-850'; they are not written"* | The target file has no title, identifier, namespace or version. | **dropped**, `info`, on the document |
| *"OpenAPI 3.1 requires a version and the source declares none; '0.0.0' is written"* | The target requires a value the source does not have. | **synthesized**, on the document |
| *"WIT has no agent descriptor; agent 'Travel Concierge' is not written"* | The source is an agent card and the target does not describe agents. Each skill is listed too. | **dropped**, `warn` |

What each target adds:

| Target | What a file built from another format's item reports |
| --- | --- |
| **OpenAPI** | An operation with no HTTP method and path is placed on one (`POST /<service>/<method>` for RPC, `/graphql/<field>` for GraphQL). An `operationId` and an empty default response are **synthesized** where the source has none. A service is kept only as the first tag of its operations. A service with no tagged operation is **dropped**, and its operations read back under `default`. |
| **AsyncAPI** | A source with no operation and no channel becomes a file that holds only `components.schemas`. An AsyncAPI 2 item written as AsyncAPI 3 lists its `publish` / `subscribe` operations (now `send` / `receive`) and the channels that gained a name. Another format's metadata is written only as its `x-` extensions, and a type name AsyncAPI does not allow as a component key (`http://example.com/orders.Order`) is written with `_` in place of each other character. |
| **CloudEvents** | Every named type is **dropped**: an event carries attributes and sample data, not type declarations. A source with no publish or subscribe operation exports as a placeholder event, and the report says so at `critical` severity. |
| **GraphQL SDL** | Every operation becomes a `Query` or `Mutation` field, and its service is **dropped**. An operation that maps to neither is **dropped**. A source with no read operation gets a placeholder `Query._` field. A type named `acme.Pet` is written as `Pet`. |
| **JSON Type Definition**, **CDDL** | A type named with a namespace (`X12-850.PO1`) is written under its bare name (`PO1`). JTD also writes the first type as the root schema when no type is named after the document. |
| **Avro**, **Kafka Connect** | A type is written under its namespace and name (`orders` becomes `commerce.orders`). The document's identifier and version are **dropped**. |
| **Protobuf**, **Connect RPC** | Service and method names become Protobuf identifiers: `Travel Concierge` is written as `Travel_Concierge`. Packages are too (`CUSTOMER-RECORD` → `CUSTOMER_RECORD`, `FIX.4.4` → `FIX._4._4`). A type with no Protobuf declaration is written as the closest Protobuf type and reported. An rpc whose payload is not a message uses a wrapper (`google.protobuf.UInt32Value`). A field number Protobuf does not allow (`0`, `19000`–`19999`), a repeated field name, and a service named like a message are renamed or renumbered and reported. |
| **ONC RPC** | Every type, program and procedure is read back under the first program's name (`Bank.Account`, `Bank.Bank.open`). A map, an alias or a scalar type is **dropped**. Scalars are written as XDR types (`integer` → `int`, `int64` → `hyper`); a type with no XDR form is written as `string`, `hyper`, `double` or `bool` and reported. |
| **XML-RPC** | The file is one `methodCall`, for the first RPC operation. Every other operation and every named type is **dropped**. A method name may use only `A–Z a–z 0–9 _ . : /`, so each run of other characters is written as `_` (an agent skill `Build itinerary` becomes `Build_itinerary`); the report lists the rename. |
| **WIT** | When no operation or type reports a loss of its own, the document does: one line names how many identifiers were rewritten in lower-kebab-case, with examples, and a package name or a `types` interface that Apiome had to invent is **synthesized**. |

An item exported back to its own format reports none of these.

## Scalar types {#scalar-types}

Each format spells its scalars its own way (`integer`, `i64`, `int64`, `long`, `fixed64` …), and an
item keeps the spelling it was imported with. An export writes each one as the target's own type.
An OpenAPI `integer` or `number` takes its width from its `format`:

| Source | ASN.1 | Avro | OMG IDL | FlatBuffers | TypeSpec | XSD, WSDL |
| --- | --- | --- | --- | --- | --- | --- |
| `integer` | `INTEGER` | `int` | `long` | `long` | `int32` | `xs:int` |
| `integer`, `format: int64` | `INTEGER` (64-bit range) | `long` | `long long` | `long` | `int64` | `xs:long` |
| `number`, `format: float` | `REAL` | `float` | `float` | `float` | `float32` | `xs:float` |
| `uint64`, `fixed64` | `INTEGER (0..18446744073709551615)` | `long` (reported) | `unsigned long long` | `ulong` | `uint64` | `xs:unsignedLong` |
| `bytes`, `binary`, `blob` | `OCTET STRING` | `bytes` | `sequence<octet>` | `[ubyte]` | `bytes` | `xs:base64Binary` |

Three spellings mean one thing in every target: Protobuf's `fixed32` and `fixed64` are unsigned,
`byte` is a signed 8-bit integer, and `blob` is binary.

When a target has no type that holds every value of a scalar, the export uses the closest one and
the fidelity report says so (**approximated**, `warn`):

| Target | Scalar | Written as |
| --- | --- | --- |
| **Avro** | `uint64`, `fixed64` | `long`, which holds values up to 2^63 − 1 |
| **Avro**, **FlatBuffers** | `bigint` (TypeScript) | `long` (64 bits) |
| **Avro**, **FlatBuffers** | `decimal` with no precision | `double`, so decimal digits can round. In Avro, a `decimal` `format` or logical type is written as the `decimal` logical type instead, which keeps every digit. |

A field of type `void` holds no value. OMG IDL has no member type for it, so the field is not
written and the report lists it as **dropped**.

## Destination documentation links

When (and only when) the cause is a genuine `destination_unsupported` specification
limit, the evidence drawer and table rows offer a link to the destination format's
**authoritative technical documentation** — e.g. the
[OpenAPI Specification](https://spec.openapis.org/oas/latest.html), the
[AsyncAPI Specification](https://www.asyncapi.com/docs/reference/specification/latest),
the [GraphQL Specification](https://spec.graphql.org/), the
[Protocol Buffers language guide](https://protobuf.dev/programming-guides/proto3/), or
the [Apache Avro Specification](https://avro.apache.org/docs/current/specification/).

These links come from a versioned, reviewed server-side registry, not ad-hoc UI text:

- Only `https` links to an **allowlisted set of authoritative hosts** can ever appear.
- Links disclose the specification name and version and are anchored to the relevant
  section where the format's documentation supports it.
- When no authoritative link applies, the UI says so plainly
  (*documentation unavailable*) rather than inventing one.

The registry version and the emitter version that produced the evidence are shown in
the drawer, so the evidence is attributable to an exact contract. (Governance of these
links — review and version-update ownership — is documented for contributors in
`apiome-rest/docs/export_projection_author_guide.md`.)

## Unavailable evidence

`unavailable` means **apiome does not know** — usually `source_parse_limit` (the parser
could not fully capture the construct) or `source_incomplete`. Unavailable constructs:

- appear in their own lane in the projection map and are never hidden by aggregation;
- are **not** counted as preserved, and do not lower a target's tier dishonestly —
  the evidence marks them explicitly instead of guessing;
- mean the emitted artifact may carry *more or less* than the evidence claims for
  those constructs. If they matter to you, fix the source (or re-import with a fuller
  parser) before trusting the export.

Evidence rows also always redact source-native identifiers and text (shown as
`[redacted]`) — construct keys, statuses, reasons, and target locations remain, but
captured source values never leave the server.

## Options change the snapshot

Per-target export options (e.g. OpenAPI's `include_paths`) are folded into the
projection snapshot: **different options are a different preview**. Changing the target
or any option in the UI immediately clears the old graph, report, and acknowledgement
and requests a fresh preview — you can never acknowledge one configuration and ship
another. Constructs excluded by an option show as `option_excluded`, so an
"unsupported-looking" loss may just be a switch you can flip.

## Snapshots and the risk acknowledgement

Every preview computes a **snapshot hash** over the exact source revision, target,
normalized options, emitter version, and registry version. The hash appears in the
preview, the projection evidence, the CLI JSON, and the completed job's result — they
all describe the same snapshot, by construction.

For a lossy or types-only export you must acknowledge the loss (the *Export anyway*
gate; a types-only export requires the typed confirmation). That acknowledgement is
bound to the snapshot hash, not to the moment in time:

- **Generate uses the acknowledged snapshot or refuses.** If the source revision,
  options, emitter, or registry changed since you previewed, the job fails with a
  structured `STALE_PREVIEW` error naming the acknowledged and current hashes — re-run
  the preview and acknowledge what you actually see now.
- **Completed jobs record their provenance**: the snapshot hash and submitted options
  are stored with the result, so an artifact is always attributable to the evidence
  that was accepted for it.
- **Several formats, one job**: a job with a `targets` list acknowledges each format
  separately (`acknowledged_snapshot` on each entry). A stale snapshot on any of them
  fails the whole job, and `error.context.target` names the format. See
  [Export to several formats in one job](./export-a-spec.md#export-to-several-formats-in-one-job).
- **Several versions, one job**: a batch export (`versions` or `all_versions`) does not
  accept `acknowledged_snapshot`, because a snapshot describes one version. Each item's
  snapshot hash is recorded on `result.batch.items[]`. See
  [Export a whole project or several versions in one job](./export-a-spec.md#export-a-whole-project-or-several-versions-in-one-job).

## Overlay rows

An export with [overlays](../bring-in/overlays.md#apply-overlays-on-export) adds one row to its
ledger for every value an overlay changed: the value's JSON Pointer, what happened to it (`set`,
`replaced`, `appended` or `removed`) and the overlay that did it. The Export studio shows them in
the **Overlays** panel on Verify and on Review, and the job returns them as `result.overlay.ledger`.

- Overlays apply in order, so a value two overlays changed has two rows, and the later one won.
- After 500 rows a last row says how many changes there were in all. The ledger never claims to
  be complete when it is not.
- An action that could not be applied is listed as a finding (such as `overlay.unmatched-target`),
  not as a row.

Overlays change the document before the fidelity report is computed, so the report, the snapshot
hash and the quality grade all describe the overlaid document. The same overlays give the same
snapshot, so a verify with overlays can be acknowledged by a job with the same overlays.

## From the CLI

```bash
# 1. What targets exist for this version, and how faithful would each be?
apiome export targets --project payments-api --version 1.0.0

# 2. Why exactly — page the per-construct projection evidence (status, reason, explanation):
apiome export evidence --project payments-api --version 1.0.0 --target avro

# Machine-readable page for automation (summary + rows + next_cursor):
apiome --json export evidence --project payments-api --target avro --limit 25

# Options are part of the snapshot — evidence for a different option set is a different snapshot:
apiome export evidence --project payments-api --target openapi --option include_paths=false

# 3. Export. A lossy/types-only export exits non-zero unless you --force (or confirm at a TTY):
apiome export avro --project payments-api --version 1.0.0 --output User.avsc --force
```

The `--json` evidence payload contains the `summary` (snapshot hash, emitter/registry
versions, status and reason counts) and a bounded `page` of rows with `next_cursor` for
paging — the machine-readable twin of what the projection map shows. In CI, treat the
snapshot hash as the identity of what you approved: a job submitted with an
acknowledged snapshot that no longer matches fails with `STALE_PREVIEW` (exit code 1)
rather than silently exporting something different. See the
[`apiome export` reference](../reference/cli/export.md) for the
full flag reference.

## Worked examples

Four situations you will actually meet, one per kind of outcome:

1. **Lossless mapping** — an AsyncAPI-imported event source exported back to
   **AsyncAPI 3**: channels, operations, messages, and schemas are `retained`; the
   tier is `lossless` and no acknowledgement is asked.
2. **Approximation** — a REST source exported to **AsyncAPI 3**: each request/response
   operation is *reframed* as an `action: send` with a `reply`, so it shows
   `approximated` with the honest explanation that the HTTP method, path, and response
   status are not represented (`destination_unsupported`, with the AsyncAPI
   specification link).
3. **Source-incomplete evidence** — a construct whose detail the parser could not
   capture shows `unavailable` / `source_parse_limit`: *"apiome's parser could not
   fully capture this construct from the source, so its export cannot be determined."*
   No destination link is shown, because the format is not at fault.
4. **Unavoidable destination limit** — a REST source exported to **Avro**: HTTP paths
   and operations show `dropped` / `destination_unsupported` (*"the format you chose
   does not support HTTP paths"*) with a link to the Avro specification; the record
   types themselves are `retained` and the tier is `types-only`.

## Canvas annotations (`x-apiome-note` / `x-apiome-canvas`)

Sticky notes and callouts drawn on the Studio schema canvas are part of the design
record, so the Studio generators serialize them into exported specs as vendor
extensions and restore them on import (Designer DUX-2.1,
apiome/private-suite#2394):

- **`x-apiome-note`** — schema-level. An **array** of notes attached to that class;
  attachment is implicit from the location (no IDs), so it survives systems that assign
  new class identifiers.
- **`x-apiome-canvas`** — document-level. `{ formatVersion, notes: [...] }` carrying
  freeform notes (and, as a fallback, notes attached to classes that were not part of
  the export, with their `attachedTo` class name preserved).

Each note object:

```json
{
  "id": "note-1721117493-h2k9x4q1a",
  "kind": "sticky",            // "sticky" | "callout"
  "text": "Confirm rounding rules with billing",
  "color": "amber",            // preset name or "#RRGGBB"
  "position": { "x": 120, "y": 240 },
  "dimensions": { "width": 220, "height": 140 },
  "attachedTo": "Invoice"      // document-level fallback only; omitted when schema-level
}
```

The round trip is **lossless** for position, size, color, text, kind, and attachment.

**Where it applies:**

| Destination | Behavior |
|---|---|
| OpenAPI 3.x, JSON Schema | Extensions emitted and re-imported (`retained`). |
| AsyncAPI 3 | Extension-capable; emitter support tracked (`emitter_unsupported` until it lands). |
| GraphQL SDL, SQL DDL, Proto3, Avro, Thrift | No vendor-extension mechanism — annotations are skipped (`dropped` / `destination_unsupported`). |
| Diagrams (Mermaid, PlantUML, GraphML, DOT) and canvas images (PNG, JPEG, SVG, PDF) | Not available: the canvas can't be exported as a diagram or an image. See [Not yet available](./export-to-any-format.mdx#not-yet-available). |

## API plans (`x-apiome-plans`) {#api-plans}

A version that an [API product](/reference/rest/api-products) includes carries the product's
[plans](/reference/rest/api-products) into its exports — every plan but the retired ones.

| Target | What happens to the plans |
| --- | --- |
| OpenAPI (3.2, 3.1, 3.0 and Swagger 2.0) | Written as the root `x-apiome-plans` extension; the fidelity report lists them as `retained`. |
| Every other format | Dropped, because the format has no equivalent; the fidelity report lists them once, as an `info` drop on the document root. |

Each entry names the product and the plan and carries the plan's auth (`strategy`, plus `header_name`
or `scopes`), `limits`, `concurrency`, `approval`, `environments`, `declared_only`,
`credential_ttl_days`, `terms_url`, `pricing_note` and `state`:

```yaml
x-apiome-plans:
  - product: payments
    product_name: Payments
    plan: standard
    name: Standard
    state: published
    auth: { strategy: key_auth, header_name: X-API-Key }
    limits:
      - { window: minute, requests: 100 }
      - { window: day, requests: 50000 }
    approval: manual
    declared_only: true
    environments: [kong-prod-cp]
```

The billing reference and the identity-provider config id are internal, so they are never written.
Exports from Browse, which need no sign-in, carry no plans.

## How exports are tested

Every format Apiome imports is exported to every target on each change to the exporter. One
example file per format is exported to all 66 targets, and each pair must end in one of four
outcomes:

| Outcome | Means |
| --- | --- |
| Exported | The file is written and nothing is lost. |
| Lossy, with a report | The file is written and the fidelity report names what was dropped, approximated or synthesized. |
| Refused, with a reason | The target cannot carry this source (for example, it needs an HTTP operation), and says so. |
| Silent loss | The report says nothing was lost, but reading the file back shows a difference. No pair ends here: the tracked list (`apiome-rest/tests/export_conformance_ledger.py`) is empty, and the check fails on any pair that would join it. |

An export that crashes fails the check. The current grid is in the repository at
`apiome-rest/tests/golden/export_conformance/matrix.md`.

The list held 148 pairs before it was emptied. Most reported nothing because the report only
looked at what the target's vocabulary cannot hold; those now report the losses in
[Exports from another format](#cross-format). The rest were defects in the exported file, now
fixed:

- **GraphQL SDL** left out every type that no `Query` or `Mutation` field reaches. An item with
  types and no operations exported as a placeholder `Query` alone.
- **ONC RPC** left out every struct that was not imported from ONC RPC, numbered every procedure
  `1`, and wrote names that are not identifiers (`Task API`) as they were.
- **OpenAPI** wrote a required request body as an optional one, in every file built from the
  canonical model (including AWS API Gateway and Azure API Management exports).
- **Azure API Management** wrote the backend a `set-backend-service` policy names into the
  definition's `servers` as well.

### Every exported file reads back {#reimport}

Each test also reads the exported file back with Apiome's importer for that format. Until this
release, the files of eight targets often did not read back: WADL, ASN.1, AsyncAPI, Postman, ONC
RPC, Protobuf, Connect RPC and CORBA IDL. Each one now reads back, or the target refuses the source
before writing anything.

| Target | What did not read back | Now |
| --- | --- | --- |
| **AsyncAPI** | Another format's metadata written as AsyncAPI fields (a Postman `sample_count`, a gateway's `backends`); references to scalar names such as `bool` or `int32` that had no schema; component keys AsyncAPI does not allow; a type that contains itself. | Metadata is written only as `x-` extensions. A scalar is written inline (`{"type": "integer", "format": "int32"}`). Component keys are renamed and every reference follows. A type that contains itself reads back as a reference to itself. |
| **Protobuf**, **Connect RPC** | Package and type names that are not identifiers, references to types the file does not declare (`.decimal`, an alias), scalar rpc payloads, field number `0`, repeated field names, a service and a message with the same name. | See the Protobuf row in [Exports from another format](#cross-format). |
| **ONC RPC** | Scalar names written as they were imported (`integer age;`), and a file of structs only, which the importer did not recognize. | XDR scalar types, and the importer reads a file of structs only. |
| **ASN.1**, **WADL** | A source with nothing either format can hold (an agent card, a gateway configuration) was written as an empty module. | Refused, with a reason, before export. |
| **Postman**, **CORBA IDL** | Nothing: every file they write reads back. Postman refuses a source with no HTTP operation. | Unchanged. |

The same refusal now applies to **Avro** schema files (`.avsc`), **CDDL**, **FlatBuffers** and
**XSD** for a source with no type, and to **RAML** for a source with no HTTP operation and no type.
Each of those exports used to be an empty file. Avro IDL (`.avdl`) still exports such a source,
because a protocol can hold its operations.

ASN.1, CDDL, FlatBuffers, XSD, WADL and RAML are greyed out in the **Export** dialog for such a
source, with the reason. Avro stays offered, because the choice between `.avsc` and `.avdl` is an
export option; an `.avsc` export of such a source is refused with the reason when it runs.

| Target | Reason shown |
| --- | --- |
| ASN.1, CDDL, FlatBuffers, XSD | *"… export needs at least one type; this source has none (only operations, agents or channels)."* |
| WADL, RAML | *"… export needs at least one HTTP operation or one type; this source has neither."* |
| Avro (`.avsc`) | *"Apache Avro schema export writes one .avsc per type, and this source has none; export Avro IDL (.avdl) to keep its operations."* |

### Every surface says the same thing

Four places export a version: the **Export** dialog, the public Browse export, `apiome export` and the
MCP `version.export` tool. A parity check runs on every change. For the same source, all four must
offer the same targets, options and defaults, and show the same fidelity report and the same advisory,
word for word. Each one also stops a lossy export the same way:

| Surface | To export a lossy conversion anyway |
| --- | --- |
| Export dialog and Browse | Tick the **Export anyway** acknowledgement |
| `apiome export` | Pass `--force` (or confirm the prompt) |
| MCP `version.export` | Pass `allow_lossy: true` |

The check records what apiome-rest answers for a REST, an event and a schema-only source in
`apiome-rest/tests/fixtures/export_surface_parity.json`. The UI, Browse and CLI tests read copies of
that file. If a surface drifts, or a copy goes stale, the build fails. After an intended change,
regenerate the file and its copies in `apiome-rest`, then review the diff:

```bash
pytest tests/test_export_surface_parity.py --update-golden
```

## REST endpoints

| Purpose | Route |
|---|---|
| Target list + per-source tier | `GET /v1/export/{tenant}/targets?artifact={id}&version={v}` |
| Pre-flight: source lint + target-readiness ranking (no job, no artifact) | `POST /v1/tenants/{tenant}/export/preflight` |
| Preview (fidelity + projection summary + snapshot hash) | `POST /v1/export/{tenant}/preview` |
| Bounded, cursor-paginated projection evidence | `POST /v1/export/{tenant}/projection-evidence` |
| Reviewed reason explanations + destination documentation | `GET /v1/export/{tenant}/capability-registry` |
| One-call verify: fidelity, validation, lint of the emitted file (format's rule pack; advisory), verdict | `POST /v1/export/{tenant}/verify` |
| Export job (accepts `acknowledged_snapshot`; fails `STALE_PREVIEW` on mismatch) | `POST /v1/export/{tenant}/jobs` |
| Multi-format export job: one zip, per-format fidelity + a rollup (`targets` list) | `POST /v1/export/{tenant}/jobs` |
| Batch export job: several versions × formats, one zip, per-item status (`versions` / `all_versions`) | `POST /v1/export/{tenant}/jobs` |
| Batch export job over several items, each at a version or its latest (`items`) | `POST /v1/export/{tenant}/jobs` |
| Export (or verify) with overlays applied first; per-value ledger in `overlay` (`overlays` list) | `POST /v1/export/{tenant}/jobs`, `POST /v1/export/{tenant}/verify` |

All routes are tenant-scoped and require an in-scope API key (`X-API-Key`).

## Related

- [Export a spec](./export-a-spec.md) — downloading the reconstructed document
- [Export studio](./export-studio.mdx) — the same evidence, step by step in the UI
- [Export catalog items](./export-catalog-items.mdx) — every target's fidelity tier for typical sources
- [OpenAPI construct matrix](../reference/openapi-construct-matrix.md) — which OpenAPI constructs survive import and export, per version
- [Push a catalog item back to the gateway](/reference/rest/connectors) — the same report, before exporting to a gateway's own format
- [Export from the CLI](./export-from-the-cli.md) — export to any format and gate CI on fidelity
- [CLI quick-start](../reference/cli-quickstart.md) — CLI setup and command groups
- [`apiome export`](../reference/cli/export.md) — full `export` flag reference
- `apiome-rest/docs/export_projection_author_guide.md`
  — the contract emitter authors must satisfy for this evidence to stay truthful
