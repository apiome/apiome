---
title: Compatibility modes
description: "How BACKWARD, FORWARD and FULL grade schema changes, per format."
sidebar_position: 2
tags: [governance, compatibility, breaking-changes, json-schema, avro, schema-registry]
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

Other formats keep their own rules, such as `buf breaking` for Protobuf, GraphQL-Inspector for
GraphQL, and the built-in ruleset where a format has none.

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

## Related

- [Avro import](../bring-in/avro-import.md): the Avro compatibility check and the schema registry's levels
- [Read a catalog item's format details](../bring-in/catalog-format-details.md#json-schema-compatibility)
- [Reviews](./reviews.mdx): require approval for breaking changes
- [Apicurio Registry rules](https://www.apicur.io/registry/docs/apicurio-registry/3.0.x/getting-started/assembly-rule-reference.html):
  the compatibility rules this check follows
