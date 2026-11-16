---
title: Compatibility modes
description: "How compatibility modes, Buf categories and AsyncAPI sides grade changes, per format."
sidebar_position: 2
tags: [governance, compatibility, breaking-changes, json-schema, avro, protobuf, asyncapi, schema-registry]
---

When you compare two versions of a catalog item, Apiome grades every change **Safe**,
**Dangerous** or **Breaking**. For data-schema formats, whether a change breaks anyone depends
on who reads and who writes. Schema registries such as Confluent and Apicurio call that the
**compatibility mode**:

| Mode | A change passes when… | Who is protected |
| --- | --- | --- |
| `BACKWARD` | the **new** schema accepts every value the old one did | New readers of data old writers wrote |
| `FORWARD` | the **old** schema accepts every value the new one does | Old readers of data new writers write |
| `FULL` | both of the above | Both |

The `_TRANSITIVE` forms (`BACKWARD_TRANSITIVE`, `FORWARD_TRANSITIVE`, `FULL_TRANSITIVE`) apply
the same check against every earlier version, not only the latest. For one pair of versions,
they check the same thing as the plain form.

Changes are graded against `BACKWARD`, a Confluent registry's default:

| A change… | Severity |
| --- | --- |
| fails `BACKWARD` | **Breaking** |
| passes `BACKWARD` but fails `FORWARD` | **Dangerous** |
| passes `FULL` | **Safe** |

Each grade's explanation starts with the mode it was graded under, such as `[BACKWARD]`, then
names the modes the change breaks.

## Formats graded by mode

| Format | How it is checked | Details |
| --- | --- | --- |
| Avro | Avro schema resolution, the way a Confluent registry applies it | [Compatibility between versions](../bring-in/avro-import.md#compatibility-between-versions) |
| JSON Schema | The open and closed content models, the way Confluent and Apicurio apply them | [JSON Schema](#json-schema) on this page |
| Protobuf | Buf's four breaking-change **categories** instead of modes | [Protobuf](#protobuf) on this page |
| AsyncAPI 2 and 3 | Channel and operation rules graded for **consumers** and **producers**, read by mode; payloads by their own format | [AsyncAPI](#asyncapi) on this page |

Other formats keep their own rules, such as GraphQL-Inspector for GraphQL, and the built-in
ruleset where a format has none.

## JSON Schema

### Open and closed content models

Whether adding or removing a property is safe depends on the object's **content model**:

- **Open**: `additionalProperties` is absent or `true`. The object may carry any property it does
  not declare.
- **Closed**: `additionalProperties: false`, or `unevaluatedProperties: false`. The object may
  carry only the properties it declares.
- **Partially open**: `additionalProperties` is a schema. Undeclared properties must match it.

The same change can therefore get opposite verdicts. In a **closed** model, old data cannot carry a
property that was never declared, so adding one is backward compatible. Old readers still reject
it, so it fails `FORWARD`. In an **open** model, old data may already carry that name with any
value. Declaring it narrows what new readers accept, so adding one fails `BACKWARD`. The grade's
explanation names the content model it used.

### The rules

| Change | Breaks | Severity | Rule id |
| --- | --- | --- | --- |
| Property added to a **closed** model | `FORWARD`, `FULL` | Dangerous | `jsonschema.forward.closed-property-added` |
| Property removed from a **closed** model | `BACKWARD`, `FULL` | Breaking | `jsonschema.backward.closed-property-removed` |
| Property added to an **open** model | `BACKWARD`, `FULL` | Breaking | `jsonschema.backward.open-property-added` |
| Property removed from an **open** model | `FORWARD`, `FULL` | Dangerous | `jsonschema.forward.open-property-removed` |
| `additionalProperties` open → closed | `BACKWARD`, `FULL` | Breaking | `jsonschema.backward.additional-properties-closed` |
| `additionalProperties` closed → open | `FORWARD`, `FULL` | Dangerous | `jsonschema.forward.additional-properties-opened` |
| A property becomes `required` | `BACKWARD`, `FULL` | Breaking | `jsonschema.backward.required-added` |
| A property is no longer `required` | `FORWARD`, `FULL` | Dangerous | `jsonschema.forward.required-removed` |
| An `enum` or `const` value removed, or an `enum` added | `BACKWARD`, `FULL` | Breaking | `jsonschema.backward.enum-narrowed` |
| An `enum` value added, or the `enum` removed | `FORWARD`, `FULL` | Dangerous | `jsonschema.forward.enum-widened` |
| `type` widened: `integer` → `number`, or `null` allowed | `FORWARD`, `FULL` | Dangerous | `jsonschema.forward.type-widened` |
| `type` narrowed: `number` → `integer` | `BACKWARD`, `FULL` | Breaking | `jsonschema.backward.type-narrowed` |
| `type` replaced: `integer` → `string` | All three | Breaking | `jsonschema.backward.type-changed` |
| A `oneOf` / `anyOf` branch removed | `BACKWARD`, `FULL` | Breaking | `jsonschema.backward.one-of-branch-removed` |
| A `oneOf` / `anyOf` branch added | `FORWARD`, `FULL` | Dangerous | `jsonschema.forward.any-of-branch-added` |
| A bound tightened: `maximum`, `maxLength`, `minLength`, `maxItems`… | `BACKWARD`, `FULL` | Breaking | `jsonschema.backward.max-length-tightened` |
| A bound loosened or removed | `FORWARD`, `FULL` | Dangerous | `jsonschema.forward.maximum-loosened` |
| A `pattern`, `format` or `multipleOf` added | `BACKWARD`, `FULL` | Breaking | `jsonschema.backward.pattern-tightened` |
| A `pattern`, `format` or `multipleOf` replaced | All three | Breaking | `jsonschema.backward.pattern-changed` |
| `uniqueItems` turned on | `BACKWARD`, `FULL` | Breaking | `jsonschema.backward.unique-items-tightened` |

Rule ids follow `jsonschema.<direction>.<rule>`. The direction is `backward` when the new schema
rejects old data and `forward` when the old schema rejects new data. Bound rules name their
keyword, such as `minimum-tightened` or `max-items-loosened`, and the `oneOf` and `anyOf` rules
name theirs (`one-of-branch-added`, `any-of-branch-removed`).

A property added to a **partially open** model is checked against the old `additionalProperties`
schema. If that schema already allowed the value, the addition is safe.

### What is not graded

- **Annotations.** `title`, `description`, `default`, `examples`, `deprecated`, `readOnly`,
  `writeOnly` and `$comment` never change which data is valid, so editing them is safe.
- **Keywords the check does not model.** `not`, `if` / `then` / `else`, `patternProperties`,
  `propertyNames`, `dependentRequired`, `dependentSchemas`, `contains` and `prefixItems` are
  compared as written. A change to one is **Dangerous** under every mode with
  `jsonschema.review.unmodeled-keyword-changed`, and never fails a mode on its own.
- **A `$ref` outside the document.** A change to a reference such as
  `https://example.com/address.json` is flagged `jsonschema.review.ref-changed`.

### `$ref`

Local references (`#/$defs/Address`) are resolved inside each version before comparing. When
both versions point at the same definition, the definition is compared once, on its own type,
so a change to `Address` is reported on `Address` and not again on every property that uses it.
When a property's `$ref` now points at a different definition, the two targets are compared and
the result is reported on that property. Self-referencing definitions are supported.

### Where the results show

The grades appear wherever Apiome grades a JSON Schema catalog item's changes. That includes
drift, under **What changed** on the item's **Versions** tab (see
[Catalog refresh](../bring-in/catalog-refresh.mdx#see-what-changed)), and the change list when you
re-import a file over an existing item. The classifier is named `jsonschema-compatibility`.

Each grade joins the change it belongs to: a property's grade joins that property's change, and any
other grade joins its type's change. Some changes have no row of their own, such as an
`additionalProperties` flip or a property inside a nested object. They are still graded, and they
count toward the overall grade, so a breaking one is never missed.

## Protobuf

Protobuf has no reader and writer modes. [Buf](https://buf.build/docs/breaking/rules) instead
sorts breaking changes into four **categories**, from least to most strict. Each one includes
everything the one above it checks:

| Category | Protects | Breaks when… |
| --- | --- | --- |
| `WIRE` | Binary-encoded messages | The bytes no longer decode the same way, such as a field number now carrying another type |
| `WIRE_JSON` | Binary and JSON-encoded messages | `WIRE`, or a JSON key changes, such as a renamed field or a new `json_name` |
| `PACKAGE` | Code generated for a package | `WIRE_JSON`, or a declaration is deleted, renamed or changes label |
| `FILE` | Code generated per file | `PACKAGE`, or a declaration moves to another file |

Changes are graded under `WIRE_JSON` by default, because gRPC services carry both binary and
JSON (transcoded) traffic. A change is **Breaking** when it breaks the category, otherwise the
severity in the table below.

Each grade's explanation starts with the category it was graded under, such as `[WIRE_JSON]`. A
Protobuf rule's explanation also lists its grade under all four, so you can see that a change is
safe on the wire but breaks generated code:

```text
[WIRE_JSON] acme.v1.User.user_name: json_name changed 'userName' → 'login'
(breaking under WIRE_JSON, PACKAGE, FILE; safe under WIRE)
```

### The Protobuf rules

| Change | `WIRE` | `WIRE_JSON` | `PACKAGE` | `FILE` | Rule id |
| --- | --- | --- | --- | --- | --- |
| A `reserved` number or name removed | Dangerous | Dangerous | Dangerous | Dangerous | `protobuf.wire.reserved-removed` |
| A reserved number used again | Breaking | Breaking | Breaking | Breaking | `protobuf.wire.reserved-number-reused` |
| A reserved name used again | Breaking | Breaking | Breaking | Breaking | `protobuf.wire.reserved-name-reused` |
| A field deleted, number not reserved | Dangerous | Breaking | Breaking | Breaking | `protobuf.wire_json.field-deleted-unreserved` |
| A field deleted, number reserved but name not | Safe | Breaking | Breaking | Breaking | `protobuf.wire_json.field-deleted-unreserved` |
| A field deleted, number and name reserved | Safe | Safe | Breaking | Breaking | `protobuf.package.field-deleted` |
| A field renamed, same number and type | Safe | Breaking | Breaking | Breaking | `protobuf.wire_json.field-renamed` |
| A field number now carrying another type | Breaking | Breaking | Breaking | Breaking | `protobuf.wire.field-number-reused` |
| `json_name` changed | Safe | Breaking | Breaking | Breaking | `protobuf.wire_json.json-name-changed` |
| A message or enum moved to another file in the same package | Safe | Safe | Safe | Breaking | `protobuf.file.type-moved-file` |
| A message or enum moved to another package | Breaking | Breaking | Breaking | Breaking | `protobuf.wire.package-changed` |
| An enum value renamed (its number taken by a new name) | Safe | Breaking | Breaking | Breaking | `protobuf.wire_json.enum-value-number-reused` |
| An enum value moved to another number | Breaking | Breaking | Breaking | Breaking | `protobuf.wire.enum-value-number-changed` |
| A field moved into, out of or between `oneof`s | Breaking | Breaking | Breaking | Breaking | `protobuf.wire.oneof-membership-changed` |
| A field made `repeated`, or no longer `repeated` | Breaking | Breaking | Breaking | Breaking | `protobuf.wire.cardinality-changed` |
| A field made `required`, or no longer `required` | Breaking | Breaking | Breaking | Breaking | `protobuf.wire.required-changed` |
| `optional` added to or removed from a proto3 field | Safe | Safe | Breaking | Breaking | `protobuf.package.presence-changed` |
| A number or name reserved | Safe | Safe | Safe | Safe | `protobuf.compatible` |

Rule ids follow `protobuf.<category>.<rule>`. The category is the least strict one where the rule
reaches its worst severity, so `protobuf.wire_json.json-name-changed` is safe under `WIRE` and
breaking from `WIRE_JSON` up.

Changes these rules do not cover keep the built-in grade under every category, such as a field's
type changing (**Breaking**) or a field being added (**Safe**).

### Where Apiome differs from Buf

The grades follow Buf's rules in all but two places, where Apiome is deliberately softer:

- **Removing a reservation** is **Dangerous**, not breaking. Nothing breaks until a later change
  reuses the number or name, and that reuse is graded **Breaking**.
- **Deleting a field whose number is not reserved** is **Dangerous** under `WIRE`, not breaking.
  The bytes old writers send are skipped as an unknown field. Under `WIRE_JSON` and above it is
  **Breaking**, as in Buf.

### With `buf` installed

When the server has `buf` and both versions' `.proto` sources, it also runs `buf breaking` under
the same category and uses its verdict for the overall grade:

- If `buf` finds a break, each `buf` finding is listed too, under rule ids such as
  `protobuf.buf-breaking.field_same_json_name`, and the overall grade is **Breaking**.
- If `buf` finds none, every **Breaking** grade is lowered to **Dangerous**, with rule id
  `buf-breaking.wire-compatible`.

When `buf` and the rules above disagree about whether the change breaks, the explanation says
`disagreement:` and names the rules on each side. Without `buf`, the rules above grade on their
own.

### Where the Protobuf results show

The grades appear wherever Apiome grades a Protobuf or gRPC catalog item's changes. That includes
drift, under **What changed** on the item's **Versions** tab (see
[Catalog refresh](../bring-in/catalog-refresh.mdx#see-what-changed)), and the change list when you
re-import a file over an existing item. The **Why** column starts with the category in brackets.
The classifier is named `buf-breaking`.

A message or enum moved to another file has no row of its own, because the file a declaration sits
in is not part of the version comparison. It is still graded under `FILE`, and it counts toward the
overall grade.

## AsyncAPI

An event channel has two sides, and a change can break one and not the other. Apiome grades every
AsyncAPI channel, operation and message change for each side:

| Side | Who upgrades first | The mode that checks it |
| --- | --- | --- |
| **Consumers** | New consumers, while old producers keep sending | `BACKWARD` |
| **Producers** | New producers, while old consumers keep reading | `FORWARD` |

`FULL` checks both sides. Changes are graded under `BACKWARD` by default. A side the mode checks
keeps its grade. A side it does not check drops one step: a break there is **Dangerous**, and a
**Dangerous** grade there is **Safe**. So adding a message is **Safe** under `BACKWARD`, because new
consumers already handle it, but **Dangerous** under `FORWARD`, because old consumers must handle it
once producers send it.

Each grade's explanation starts with the mode and what it checks, and ends with both sides' grades:

```text
[BACKWARD: new consumers against old producers] message 'onOrder#event.OrderCancelled' removed
from the operation's messages; new consumers break on it while old producers still send it
(consumers: breaking, producers: safe)
```

### The AsyncAPI rules

| Change | Consumers | Producers | `BACKWARD` | `FORWARD` | `FULL` | Rule id |
| --- | --- | --- | --- | --- | --- | --- |
| A channel's address or address template changed | Breaking | Dangerous | Breaking | Dangerous | Breaking | `asyncapi.consumer.address-changed` |
| An address parameter added without a `default` | Breaking | Dangerous | Breaking | Dangerous | Breaking | `asyncapi.consumer.parameter-added` |
| An address parameter added with a `default` | Safe | Safe | Safe | Safe | Safe | `asyncapi.both.parameter-added-with-default` |
| A server's `protocol` changed | Breaking | Breaking | Breaking | Breaking | Breaking | `asyncapi.both.protocol-changed` |
| A channel, operation, message or server binding changed | Breaking | Breaking | Breaking | Breaking | Breaking | `asyncapi.both.binding-changed` |
| An operation's `action` flipped between `send` and `receive` (`publish` and `subscribe` in 2.x) | Breaking | Breaking | Breaking | Breaking | Breaking | `asyncapi.both.action-flipped` |
| An operation's `reply` removed (3.x) | Breaking | Dangerous | Breaking | Dangerous | Breaking | `asyncapi.consumer.reply-removed` |
| A message removed from a channel's messages (`oneOf` in 2.x) | Breaking | Safe | Breaking | Dangerous | Breaking | `asyncapi.consumer.message-removed` |
| A message added to a channel's messages | Safe | Dangerous | Safe | Dangerous | Dangerous | `asyncapi.producer.message-added` |
| A payload's `schemaFormat` changed to another schema language | Breaking | Breaking | Breaking | Breaking | Breaking | `asyncapi.both.schema-format-changed` |
| A payload changed in a way its own format accepts both ways | Safe | Safe | Safe | Safe | Safe | `asyncapi.both.payload-compatible` |
| A server added, removed or moved | Dangerous | Dangerous | Dangerous | Dangerous | Dangerous | `asyncapi.both.server-changed` |
| A server's or an operation's `security` changed | Dangerous | Dangerous | Dangerous | Dangerous | Dangerous | `asyncapi.both.security-changed` |

Rule ids follow `asyncapi.<side>.<rule>`. The side is the one the change is worst for: `consumer`,
`producer`, or `both` when the two sides grade alike. Requesters consume the reply, so a removed
`reply` is graded on the consumer side. AsyncAPI 2 has no `reply`, so that rule applies to 3.x only.

A message counts as removed or added only when its operation exists in both versions. When a whole
operation is removed or added, its messages keep the built-in grade, and so does any other change
these rules do not cover, such as removing a whole channel (**Breaking**) or changing a message's
headers (**Dangerous**).

### When an address or action changes

A channel is identified by its address, so a new address first looks like one channel removed and
another added. Apiome treats them as one channel with a new address when the channel keeps its
name (AsyncAPI 3), or when an operation in both versions moved from one to the other. Both rows,
and the operation's row, are then graded `address-changed`.

In AsyncAPI 2 an operation without an `operationId` is identified by its action and address, so
flipping `subscribe` to `publish` looks like one operation removed and another added. When both are
on the same channel, both rows are graded `action-flipped`.

### Payloads

A payload is graded by the check of its own schema language, named by `schemaFormat`. In AsyncAPI
3 that is the payload's `schemaFormat` and `schema`; in AsyncAPI 2 it is the message's
`schemaFormat` and `payload`:

| `schemaFormat` | Checked by | Rule ids |
| --- | --- | --- |
| None, `application/vnd.aai.asyncapi`, `application/schema+json` or `+yaml` | The [JSON Schema](#json-schema) rules | `jsonschema.*` |
| `application/vnd.apache.avro` (`+json`, `+yaml`) | Avro schema resolution, both ways | `avro-compatibility.*` |
| `application/vnd.google.protobuf`, `application/x-protobuf` | The [Protobuf](#protobuf) rules under `WIRE_JSON` | `protobuf.*` |
| Anything else, such as RAML or the OpenAPI Schema Object | Not checked: the built-in grade stands | — |

So an Avro payload that gains a field without a default reports
`avro-compatibility.reader-field-missing-default-value`: **Breaking** for consumers, because new
consumers cannot read what old producers wrote, and **Safe** for producers. A problem the new
schema finds in old data is a consumer-side break; a problem the old schema finds in new data is a
producer-side break. Protobuf's rules grade both sides alike.

Only the media type counts as the schema language. `application/vnd.apache.avro;version=1.9.0` and
`…;version=1.11.0` are the same language. A Protobuf payload is checked only when the server has
`buf` to compile it; otherwise the built-in grade stands.

### With `@asyncapi/diff` installed

When the server has the `asyncapi-diff` tool, it also runs `@asyncapi/diff` over the two documents.
Its verdict replaces the grade of each whole channel or operation it classifies, with rule id
`asyncapi-diff.breaking` or `asyncapi-diff.non-breaking`. Every other change keeps the grades above.

### Where the AsyncAPI results show

The grades appear wherever Apiome grades an AsyncAPI catalog item's changes. That includes drift,
under **What changed** on the item's **Versions** tab (see
[Catalog refresh](../bring-in/catalog-refresh.mdx#see-what-changed)), and the change list when you
re-import a file over an existing item. The rule id names the side and the **Why** column starts
with the mode in brackets. The classifier is named `asyncapi-diff`.

Servers have no row of their own in the version comparison, and neither does a `.proto` text
payload in AsyncAPI 2. Their findings are still graded, and they count toward the overall grade.

## Related

- [Avro import](../bring-in/avro-import.md): the Avro compatibility check and the schema registry's levels
- [Read a catalog item's format details](../bring-in/catalog-format-details.md#json-schema-compatibility)
- [What a Protobuf item records for comparison](../bring-in/catalog-format-details.md#protobuf-what-a-comparison-reads)
- [What an AsyncAPI item records for comparison](../bring-in/catalog-format-details.md#asyncapi-what-a-comparison-reads)
- [Reviews](./reviews.mdx): require approval for breaking changes
- [Apicurio Registry rules](https://www.apicur.io/registry/docs/apicurio-registry/3.0.x/getting-started/assembly-rule-reference.html):
  the compatibility rules this check follows
- [Buf breaking rules and categories](https://buf.build/docs/breaking/rules): the categories the
  Protobuf grades follow
- [AsyncAPI 3.0 specification](https://www.asyncapi.com/docs/reference/specification/v3.0.0): channels,
  operations, `reply` and the Multi Format Schema Object
