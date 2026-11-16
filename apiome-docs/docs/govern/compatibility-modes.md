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

`NONE` turns compatibility checking off: changes are still listed with their rule ids, but none
of them fails. Changes are graded against `BACKWARD`, a Confluent registry's default, unless the
project's policy or the request names another mode (see
[Choose a project's mode](#choose-a-projects-mode)):

| A change… | Severity |
| --- | --- |
| fails `BACKWARD` | **Breaking** |
| passes `BACKWARD` but fails `FORWARD` | **Dangerous** |
| passes `FULL` | **Safe** |

Each grade's explanation starts with the mode it was graded under, such as `[FORWARD]`, then
names the modes the change breaks. Avro grades under the default `BACKWARD` keep their
explanation without the bracket.

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

## Choose a project's mode

A project's mode is part of its style guide's policy. The Style guides screen is not yet available,
so set the three settings over the REST API with
[`PUT /v1/style-guides/{tenant}/{guide}/policy`](../reference/rest/style-guides.md#put-style-guide-policy-settings-v1-style-guides-tenant-slug-guide-id-policy-put):

```http
PUT /v1/style-guides/{tenant}/{guide}/policy
X-API-Key: <your-api-key>

{ "compatibilityMode": "FULL", "compatibilityTransitive": true, "protobufBreakingCategory": "WIRE_JSON" }
```

A field you leave out keeps its value:

| Field | Values | Default |
| --- | --- | --- |
| `compatibilityMode` | `BACKWARD`, `FORWARD`, `FULL`, `NONE` | `BACKWARD` |
| `compatibilityTransitive` | `true` checks every earlier version too | `false` |
| `protobufBreakingCategory` | `WIRE`, `WIRE_JSON`, `PACKAGE`, `FILE` | `WIRE_JSON` |

`GET` on the same path reads them back.

The policy resolves the way every guide setting does: a guide assigned to the project wins over
one assigned to the workspace, which wins over the workspace's default guide. It applies to:

- the classified diff, [`POST /v1/diff/{tenant}/classified`](../reference/rest/classified-diff.md),
  and so to [`apiome diff`](../reference/cli/diff.md) and the [CI diff gate](../reference/ci/ci-diff-gate.md);
- the compatibility check,
  [`POST /v1/versions/{tenant}/{project}/compatibility`](../reference/rest/compatibility.md), and so
  to `apiome compat --mode`;
- the breaking-change publish guardrail, when a version is published.

Every guide edit records the three settings in the guide's history, so a past verdict can be
explained by the policy it ran under.

### Ask for a mode in one request

The classified diff and the compatibility check both accept `mode`, `transitive` and `category` in
the request body. Anything you leave out comes from the project's policy:

```json
{
  "base": { "project": "orders-events", "version": "3.0.0" },
  "head": { "project": "orders-events", "version": "3.1.0" },
  "mode": "FULL_TRANSITIVE"
}
```

A `_TRANSITIVE` mode name also turns on `transitive`. From the CLI:

```bash
apiome diff ./orders.avsc --against orders-events@latest --mode forward
apiome diff ./orders.avsc --against orders-events@latest --mode full --transitive
apiome compat --project orders-events --base-version 3.0.0 --version 3.1.0 --mode full
```

### What a response says it evaluated

Every response carries `evaluatedUnder`:

```json
"evaluatedUnder": {
  "mode": "FORWARD",
  "transitive": false,
  "category": null,
  "formats": ["avro"],
  "modeApplied": true,
  "categoryApplied": false,
  "ruleset": "avro-compatibility",
  "source": { "mode": "request", "transitive": "policy", "category": "policy" },
  "comparedRevisions": [{ "revisionId": "…", "versionLabel": "3.0.0", "role": "base" }],
  "comparedRevisionsTruncated": false
}
```

- `modeApplied` is `true` only when an Avro, JSON Schema or AsyncAPI classifier graded the changes
  by `mode`. For a format without one, such as OpenAPI, RAML, API Blueprint or WSDL, it is
  `false` and `ruleset` names what graded the changes instead: `ctg` for the OpenAPI change
  taxonomy, `openapi-compatibility` for the compatibility check's OpenAPI engine, or the format's
  own classifier. The response never implies a mode it did not apply.
- `category` is set, and `categoryApplied` is `true`, only when Protobuf was compared.
- `source` says whether each setting came from the request or from the project's policy.

Each change also carries its `ruleId`. In the classified diff, a change graded by one of these
classifiers also carries `grade` (`safe`, `dangerous` or `breaking`) and `rationale`. Its
`severity` is `breaking` for a break and `non-breaking` otherwise, so `--fail-on warn` fails on
both dangerous and safe changes, as it does for OpenAPI.

### Transitive checks

With `transitive` on, the head is compared with the base and then with every earlier revision
of the base, newest first, up to 50. The earlier revisions are the base's published ancestors.
For a catalog item, which is never published, they are the item's earlier revisions.

Every change against the base is listed. From an earlier revision, only breaking changes are
added, and only ones no newer revision already reported. Each change then names the revision it
was found against:

```json
{
  "ruleId": "avro-compatibility.reader-field-missing-default-value",
  "severity": "breaking",
  "against": { "revisionId": "…", "versionLabel": "1.0.0" }
}
```

A change can therefore be compatible with the base and still fail. When the publish guardrail
finds one, its message names the earlier version, for example
`1 breaking change(s) versus 2.0.0 published as 2.1.0 (breaking against earlier revision(s) 1.0.0)`.
Under a **block** policy that publish is refused.

## Known differences from reference tools

Apiome checks its grades against the tools each format's teams already run. A test corpus of
version pairs per format records Apiome's verdict under every mode, alongside each reference
tool's verdict on the same pair:

| Format | Reference tool | Compared under |
| --- | --- | --- |
| Avro, JSON Schema | Apicurio Registry (its Confluent-compatible API) and recorded Confluent Schema Registry answers | `BACKWARD`, `FORWARD`, `FULL`, `NONE` |
| Protobuf | `buf breaking` | `WIRE`, `WIRE_JSON`, `PACKAGE`, `FILE` |
| AsyncAPI | `@asyncapi/diff` | `BACKWARD` (the tool has no modes) |
| GraphQL | GraphQL-Inspector | The default grade (GraphQL has no modes) |

The Avro cases include the rows of Confluent's compatibility-types table (add or delete a field,
with or without a default). The JSON Schema cases include Confluent's open, closed and partially
open content-model rules. The Protobuf cases fire every Protobuf rule in the
[rule catalogue](#protobuf-rules).

Every pull request that changes a classifier runs the corpus against live reference tools. If
Apiome and a tool disagree about whether a change is compatible, the build fails. The only
exceptions are the differences listed below, each with the reason Apiome grades it its own way.
**Modes** lists the modes, or Protobuf categories, where the two verdicts differ. The corpus
and its generated README are in `apiome-rest/tests/golden/compatibility/`.

<!-- compatibility-reference-waivers:start (generated by apiome-rest/tests/compatibility_corpus.py) -->

| Case | Reference tool | Modes | Why Apiome differs |
| --- | --- | --- | --- |
| `protobuf/reserved-removed` | `buf breaking` | `FILE`, `PACKAGE`, `WIRE`, `WIRE_JSON` | XPC-4.3 decision: removing a reservation is Dangerous, not breaking. Nothing breaks until a later change reuses the number or name, and that reuse is graded Breaking. |
| `protobuf/field-deleted-unreserved` | `buf breaking` | `WIRE` | XPC-4.3 decision: under `WIRE`, deleting a field whose number is not reserved is Dangerous. The bytes old writers send are skipped as an unknown field; from `WIRE_JSON` up it is Breaking, as in Buf. |
| `asyncapi/v2-server-changed` | `@asyncapi/diff` (standard ruleset) | `BACKWARD` | XPC-4.4 decision: a server added, removed or moved is Dangerous on both sides. It changes where clients connect, not the messages they exchange; `@asyncapi/diff` calls a host edit breaking. |
| `asyncapi/v3-server-changed` | `@asyncapi/diff` (standard ruleset) | `BACKWARD` | XPC-4.4 decision: a server added, removed or moved is Dangerous on both sides. It changes where clients connect, not the messages they exchange; `@asyncapi/diff` calls a host edit breaking. |
| `asyncapi/v2-security-changed` | `@asyncapi/diff` (standard ruleset) | `BACKWARD` | XPC-4.4 decision: a server's or an operation's `security` change is Dangerous on both sides. Clients need new credentials, but the contract's messages are unchanged. |
| `asyncapi/v3-security-changed` | `@asyncapi/diff` (standard ruleset) | `BACKWARD` | XPC-4.4 decision: a server's or an operation's `security` change is Dangerous on both sides. Clients need new credentials, but the contract's messages are unchanged. |
| `asyncapi/v2-parameter-added` | `@asyncapi/diff` (standard ruleset) | `BACKWARD` | XPC-4.4 decision: an address parameter added without a `default` is Breaking for consumers, who cannot build the new address; `@asyncapi/diff` calls any parameter addition non-breaking. |
| `json-schema/array-items-narrowed` | Apicurio Registry (ccompat API) | `FORWARD` | Apicurio fails both directions when a `type` list narrows. Every value the new schema accepts the old one accepts too, so old readers still read new data: Apiome fails `BACKWARD` only. |
| `json-schema/partially-open-property-added-narrower` | Apicurio Registry (ccompat API) | `FORWARD` | Apicurio fails both directions when a `type` list narrows. Every value the new schema accepts the old one accepts too, so old readers still read new data: Apiome fails `BACKWARD` only. |
| `json-schema/ref-cycle` | Apicurio Registry (ccompat API) | `BACKWARD`, `FULL` | Apiome grades every `$defs` entry as a type of its own; a registry checks only the root schema, so a change to a definition the root never references passes there. |
| `json-schema/ref-target-moved` | Apicurio Registry (ccompat API) | `BACKWARD`, `FULL` | Apiome grades every `$defs` entry as a type of its own; a registry checks only the root schema, so a change to a definition the root never references passes there. |
| `json-schema/ref-shared-definition` | Apicurio Registry (ccompat API) | `FORWARD`, `FULL` | Apiome grades every `$defs` entry as a type of its own; a registry checks only the root schema, so a change to a definition the root never references passes there. |
| `graphql/enum-value-removed` | GraphQL-Inspector (`@graphql-inspector/core`) | `DEFAULT` | The compatibility API grades GraphQL with the format-agnostic structural rules; GraphQL-Inspector's verdict replaces them only where the server runs it. The structural rules grade a removed enum value as a Dangerous type change. |
| `graphql/output-field-made-nullable` | GraphQL-Inspector (`@graphql-inspector/core`) | `DEFAULT` | The compatibility API grades GraphQL with the format-agnostic structural rules; GraphQL-Inspector's verdict replaces them only where the server runs it. They do not read nullability by direction, so an output field made nullable is graded Safe. |
| `graphql/output-field-made-non-null` | GraphQL-Inspector (`@graphql-inspector/core`) | `DEFAULT` | The compatibility API grades GraphQL with the format-agnostic structural rules; GraphQL-Inspector's verdict replaces them only where the server runs it. They do not read nullability by direction, so an output field made non-null is graded Breaking. |
| `graphql/required-argument-added` | GraphQL-Inspector (`@graphql-inspector/core`) | `DEFAULT` | The compatibility API grades GraphQL with the format-agnostic structural rules; GraphQL-Inspector's verdict replaces them only where the server runs it. They grade a new required argument as a Dangerous field change. |
| `graphql/required-input-field-added` | GraphQL-Inspector (`@graphql-inspector/core`) | `DEFAULT` | The compatibility API grades GraphQL with the format-agnostic structural rules; GraphQL-Inspector's verdict replaces them only where the server runs it. They grade a new required input field as Dangerous (`added-mandatory-field`). |

<!-- compatibility-reference-waivers:end -->

## Rule catalogue

[`GET /v1/compatibility/rules`](../reference/rest/compatibility.md) lists every rule id these
classifiers report, with its severity under each mode or Protobuf category. Add `?format=avro`
(or `json-schema`, `protobuf`, `asyncapi`, or a format key such as `asyncapi-3`) to list one
format's rules. API keys with `diff:read` or `registry:read` can read it. The tables below are
generated from the same data.

**Breaks** is the side a rule protects: `backward` (the new schema rejects old data), `forward`
(the old schema rejects new data), `review` (a change the check cannot prove either way), or
`either` for an Avro rule, which is breaking under the modes that check the direction it was
found in. AsyncAPI rules name `consumer`, `producer` or `both`. A rule id ending in `*` is a
family: the rest of the id is the tool's own rule name.

<!-- compatibility-rule-catalogue:start (generated by apiome-rest/scripts/generate_compatibility_rule_catalogue.py) -->

### Avro rules

| Rule id | Breaks | `BACKWARD` | `FORWARD` | `FULL` | `NONE` | Description |
| --- | --- | --- | --- | --- | --- | --- |
| `avro-compatibility.compatible` | — | Safe | Safe | Safe | Safe | Avro schema resolution reads the change both ways (FULL compatible). |
| `avro-compatibility.fixed-size-mismatch` | either | Breaking | Breaking | Breaking | Dangerous | A fixed of another size. |
| `avro-compatibility.missing-enum-symbols` | either | Breaking | Breaking | Breaking | Dangerous | Writer enum symbols the reader lacks, and the reader's enum has no default. |
| `avro-compatibility.missing-union-branch` | either | Breaking | Breaking | Breaking | Dangerous | A writer union branch no reader branch can read. |
| `avro-compatibility.name-mismatch` | either | Breaking | Breaking | Breaking | Dangerous | A record, enum or fixed renamed without an alias for the old name. |
| `avro-compatibility.reader-field-missing-default-value` | either | Breaking | Breaking | Breaking | Dangerous | A reader field the writer lacks has no default. |
| `avro-compatibility.type-mismatch` | either | Breaking | Breaking | Breaking | Dangerous | Two types that do not resolve; Avro's promotions such as int to long do. |

### JSON Schema rules

| Rule id | Breaks | `BACKWARD` | `FORWARD` | `FULL` | `NONE` | Description |
| --- | --- | --- | --- | --- | --- | --- |
| `jsonschema.backward.additional-properties-closed` | backward | Breaking | Dangerous | Breaking | Dangerous | additionalProperties turned from open to closed. |
| `jsonschema.backward.any-of-branch-removed` | backward | Breaking | Dangerous | Breaking | Dangerous | An anyOf branch removed. |
| `jsonschema.backward.closed-property-removed` | backward | Breaking | Dangerous | Breaking | Dangerous | A property removed from a closed content model. |
| `jsonschema.backward.enum-narrowed` | backward | Breaking | Dangerous | Breaking | Dangerous | An enum or const value removed, or an enum added. |
| `jsonschema.backward.exclusive-maximum-tightened` | backward | Breaking | Dangerous | Breaking | Dangerous | The exclusiveMaximum bound tightened or added. |
| `jsonschema.backward.exclusive-minimum-tightened` | backward | Breaking | Dangerous | Breaking | Dangerous | The exclusiveMinimum bound tightened or added. |
| `jsonschema.backward.format-changed` | backward | Breaking | Dangerous | Breaking | Dangerous | A format replaced by another. |
| `jsonschema.backward.format-tightened` | backward | Breaking | Dangerous | Breaking | Dangerous | A format added. |
| `jsonschema.backward.max-items-tightened` | backward | Breaking | Dangerous | Breaking | Dangerous | The maxItems bound tightened or added. |
| `jsonschema.backward.max-length-tightened` | backward | Breaking | Dangerous | Breaking | Dangerous | The maxLength bound tightened or added. |
| `jsonschema.backward.max-properties-tightened` | backward | Breaking | Dangerous | Breaking | Dangerous | The maxProperties bound tightened or added. |
| `jsonschema.backward.maximum-tightened` | backward | Breaking | Dangerous | Breaking | Dangerous | The maximum bound tightened or added. |
| `jsonschema.backward.min-items-tightened` | backward | Breaking | Dangerous | Breaking | Dangerous | The minItems bound tightened or added. |
| `jsonschema.backward.min-length-tightened` | backward | Breaking | Dangerous | Breaking | Dangerous | The minLength bound tightened or added. |
| `jsonschema.backward.min-properties-tightened` | backward | Breaking | Dangerous | Breaking | Dangerous | The minProperties bound tightened or added. |
| `jsonschema.backward.minimum-tightened` | backward | Breaking | Dangerous | Breaking | Dangerous | The minimum bound tightened or added. |
| `jsonschema.backward.multiple-of-changed` | backward | Breaking | Dangerous | Breaking | Dangerous | A multipleOf replaced by another. |
| `jsonschema.backward.multiple-of-tightened` | backward | Breaking | Dangerous | Breaking | Dangerous | A multipleOf added. |
| `jsonschema.backward.one-of-branch-removed` | backward | Breaking | Dangerous | Breaking | Dangerous | A oneOf branch removed. |
| `jsonschema.backward.open-property-added` | backward | Breaking | Dangerous | Breaking | Dangerous | A property added to an open content model. |
| `jsonschema.backward.pattern-changed` | backward | Breaking | Dangerous | Breaking | Dangerous | A pattern replaced by another. |
| `jsonschema.backward.pattern-tightened` | backward | Breaking | Dangerous | Breaking | Dangerous | A pattern added. |
| `jsonschema.backward.required-added` | backward | Breaking | Dangerous | Breaking | Dangerous | A property became required. |
| `jsonschema.backward.schema-rejects-all` | backward | Breaking | Dangerous | Breaking | Dangerous | The schema became false and now rejects every value. |
| `jsonschema.backward.type-changed` | backward | Breaking | Dangerous | Breaking | Dangerous | A type replaced by an unrelated one, such as integer to string. |
| `jsonschema.backward.type-narrowed` | backward | Breaking | Dangerous | Breaking | Dangerous | A type narrowed, such as number to integer. |
| `jsonschema.backward.unique-items-tightened` | backward | Breaking | Dangerous | Breaking | Dangerous | uniqueItems turned on. |
| `jsonschema.compatible` | — | Safe | Safe | Safe | Safe | The JSON Schema check accepts the change both ways (FULL compatible). |
| `jsonschema.forward.additional-properties-opened` | forward | Dangerous | Breaking | Breaking | Dangerous | additionalProperties turned from closed to open. |
| `jsonschema.forward.any-of-branch-added` | forward | Dangerous | Breaking | Breaking | Dangerous | An anyOf branch added. |
| `jsonschema.forward.closed-property-added` | forward | Dangerous | Breaking | Breaking | Dangerous | A property added to a closed content model. |
| `jsonschema.forward.enum-widened` | forward | Dangerous | Breaking | Breaking | Dangerous | An enum value added, or the enum removed. |
| `jsonschema.forward.exclusive-maximum-loosened` | forward | Dangerous | Breaking | Breaking | Dangerous | The exclusiveMaximum bound loosened or removed. |
| `jsonschema.forward.exclusive-minimum-loosened` | forward | Dangerous | Breaking | Breaking | Dangerous | The exclusiveMinimum bound loosened or removed. |
| `jsonschema.forward.format-changed` | forward | Dangerous | Breaking | Breaking | Dangerous | A format replaced by another. |
| `jsonschema.forward.format-loosened` | forward | Dangerous | Breaking | Breaking | Dangerous | A format removed. |
| `jsonschema.forward.max-items-loosened` | forward | Dangerous | Breaking | Breaking | Dangerous | The maxItems bound loosened or removed. |
| `jsonschema.forward.max-length-loosened` | forward | Dangerous | Breaking | Breaking | Dangerous | The maxLength bound loosened or removed. |
| `jsonschema.forward.max-properties-loosened` | forward | Dangerous | Breaking | Breaking | Dangerous | The maxProperties bound loosened or removed. |
| `jsonschema.forward.maximum-loosened` | forward | Dangerous | Breaking | Breaking | Dangerous | The maximum bound loosened or removed. |
| `jsonschema.forward.min-items-loosened` | forward | Dangerous | Breaking | Breaking | Dangerous | The minItems bound loosened or removed. |
| `jsonschema.forward.min-length-loosened` | forward | Dangerous | Breaking | Breaking | Dangerous | The minLength bound loosened or removed. |
| `jsonschema.forward.min-properties-loosened` | forward | Dangerous | Breaking | Breaking | Dangerous | The minProperties bound loosened or removed. |
| `jsonschema.forward.minimum-loosened` | forward | Dangerous | Breaking | Breaking | Dangerous | The minimum bound loosened or removed. |
| `jsonschema.forward.multiple-of-changed` | forward | Dangerous | Breaking | Breaking | Dangerous | A multipleOf replaced by another. |
| `jsonschema.forward.multiple-of-loosened` | forward | Dangerous | Breaking | Breaking | Dangerous | A multipleOf removed. |
| `jsonschema.forward.one-of-branch-added` | forward | Dangerous | Breaking | Breaking | Dangerous | A oneOf branch added. |
| `jsonschema.forward.open-property-removed` | forward | Dangerous | Breaking | Breaking | Dangerous | A property removed from an open content model. |
| `jsonschema.forward.pattern-changed` | forward | Dangerous | Breaking | Breaking | Dangerous | A pattern replaced by another. |
| `jsonschema.forward.pattern-loosened` | forward | Dangerous | Breaking | Breaking | Dangerous | A pattern removed. |
| `jsonschema.forward.required-removed` | forward | Dangerous | Breaking | Breaking | Dangerous | A property is no longer required. |
| `jsonschema.forward.schema-accepts-values` | forward | Dangerous | Breaking | Breaking | Dangerous | The schema stopped being false and now accepts values. |
| `jsonschema.forward.type-changed` | forward | Dangerous | Breaking | Breaking | Dangerous | A type replaced by an unrelated one, such as integer to string. |
| `jsonschema.forward.type-widened` | forward | Dangerous | Breaking | Breaking | Dangerous | A type widened, such as integer to number or null allowed. |
| `jsonschema.forward.unique-items-loosened` | forward | Dangerous | Breaking | Breaking | Dangerous | uniqueItems turned off. |
| `jsonschema.review.ref-changed` | review | Dangerous | Dangerous | Dangerous | Dangerous | A $ref that points outside the document changed. |
| `jsonschema.review.unmodeled-keyword-changed` | review | Dangerous | Dangerous | Dangerous | Dangerous | A keyword the check does not model changed, such as not or if. |

### AsyncAPI rules

| Rule id | Breaks | `BACKWARD` | `FORWARD` | `FULL` | `NONE` | Description |
| --- | --- | --- | --- | --- | --- | --- |
| `asyncapi-diff.breaking` | — | Breaking | Breaking | Breaking | Dangerous | @asyncapi/diff classified the whole channel or operation as breaking. |
| `asyncapi-diff.non-breaking` | — | Safe | Safe | Safe | Safe | @asyncapi/diff classified the whole channel or operation as non-breaking. |
| `asyncapi.both.action-flipped` | both | Breaking | Breaking | Breaking | Dangerous | An operation's action flipped between send and receive. Consumers: breaking; producers: breaking. |
| `asyncapi.both.binding-changed` | both | Breaking | Breaking | Breaking | Dangerous | A channel, operation, message or server binding changed. Consumers: breaking; producers: breaking. |
| `asyncapi.both.parameter-added-with-default` | both | Safe | Safe | Safe | Safe | An address parameter added with a default. Consumers: safe; producers: safe. |
| `asyncapi.both.payload-compatible` | both | Safe | Safe | Safe | Safe | A payload changed in a way its own format accepts both ways. Consumers: safe; producers: safe. |
| `asyncapi.both.protocol-changed` | both | Breaking | Breaking | Breaking | Dangerous | A server's protocol changed. Consumers: breaking; producers: breaking. |
| `asyncapi.both.schema-format-changed` | both | Breaking | Breaking | Breaking | Dangerous | A payload's schemaFormat changed to another schema language. Consumers: breaking; producers: breaking. |
| `asyncapi.both.security-changed` | both | Dangerous | Dangerous | Dangerous | Dangerous | A server's or an operation's security changed. Consumers: dangerous; producers: dangerous. |
| `asyncapi.both.server-changed` | both | Dangerous | Dangerous | Dangerous | Dangerous | A server added, removed or moved. Consumers: dangerous; producers: dangerous. |
| `asyncapi.consumer.address-changed` | consumer | Breaking | Dangerous | Breaking | Dangerous | A channel's address or address template changed. Consumers: breaking; producers: dangerous. |
| `asyncapi.consumer.message-removed` | consumer | Breaking | Dangerous | Breaking | Dangerous | A message removed from a channel's messages. Consumers: breaking; producers: safe. |
| `asyncapi.consumer.parameter-added` | consumer | Breaking | Dangerous | Breaking | Dangerous | An address parameter added without a default. Consumers: breaking; producers: dangerous. |
| `asyncapi.consumer.reply-removed` | consumer | Breaking | Dangerous | Breaking | Dangerous | An operation's reply removed (AsyncAPI 3). Consumers: breaking; producers: dangerous. |
| `asyncapi.producer.message-added` | producer | Safe | Dangerous | Dangerous | Safe | A message added to a channel's messages. Consumers: safe; producers: dangerous. |

### Protobuf rules

| Rule id | Category | `WIRE` | `WIRE_JSON` | `PACKAGE` | `FILE` | Description |
| --- | --- | --- | --- | --- | --- | --- |
| `buf-breaking.wire-compatible` | — | Dangerous | Dangerous | Dangerous | Dangerous | buf breaking found no break, so a rule's breaking grade was lowered to dangerous. |
| `protobuf.buf-breaking.*` | — | Breaking | Breaking | Breaking | Breaking | A break buf breaking reported, named after buf's own rule (protobuf.buf-breaking.field_same_json_name), at the category the diff was graded at. |
| `protobuf.compatible` | — | Safe | Safe | Safe | Safe | A change the rules explain without a break, such as a number or name reserved. |
| `protobuf.file.type-moved-file` | `FILE` | Safe | Safe | Safe | Breaking | A message or enum moved to another file in the same package. |
| `protobuf.package.field-deleted` | `PACKAGE` | Safe | Safe | Breaking | Breaking | A field deleted with its number and name reserved. |
| `protobuf.package.presence-changed` | `PACKAGE` | Safe | Safe | Breaking | Breaking | optional added to or removed from a proto3 field. |
| `protobuf.wire.cardinality-changed` | `WIRE` | Breaking | Breaking | Breaking | Breaking | A field made repeated, or no longer repeated. |
| `protobuf.wire.enum-value-number-changed` | `WIRE` | Breaking | Breaking | Breaking | Breaking | An enum value moved to another number. |
| `protobuf.wire.field-number-reused` | `WIRE` | Breaking | Breaking | Breaking | Breaking | A field number now carrying another type. |
| `protobuf.wire.oneof-membership-changed` | `WIRE` | Breaking | Breaking | Breaking | Breaking | A field moved into, out of or between oneofs. |
| `protobuf.wire.package-changed` | `WIRE` | Breaking | Breaking | Breaking | Breaking | A message or enum moved to another package. |
| `protobuf.wire.required-changed` | `WIRE` | Breaking | Breaking | Breaking | Breaking | A field made required, or no longer required. |
| `protobuf.wire.reserved-name-reused` | `WIRE` | Breaking | Breaking | Breaking | Breaking | A reserved name used again. |
| `protobuf.wire.reserved-number-reused` | `WIRE` | Breaking | Breaking | Breaking | Breaking | A reserved number used again. |
| `protobuf.wire.reserved-removed` | `WIRE` | Dangerous | Dangerous | Dangerous | Dangerous | A reserved number or name removed. |
| `protobuf.wire_json.enum-value-number-reused` | `WIRE_JSON` | Safe | Breaking | Breaking | Breaking | An enum value renamed: its number taken by a new name. |
| `protobuf.wire_json.field-deleted-unreserved` | `WIRE_JSON` | Dangerous | Breaking | Breaking | Breaking | A field deleted without reserving its number or name. |
| `protobuf.wire_json.field-renamed` | `WIRE_JSON` | Safe | Breaking | Breaking | Breaking | A field renamed, same number and type. |
| `protobuf.wire_json.json-name-changed` | `WIRE_JSON` | Safe | Breaking | Breaking | Breaking | A field's json_name changed. |

<!-- compatibility-rule-catalogue:end -->

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
