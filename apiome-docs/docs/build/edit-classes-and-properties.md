---
title: "Edit classes and properties"
description: "Shape the data model: classes become schemas, properties become their fields."
sidebar_position: 2
tags: [studio, schemas]
---

A **class** is a schema object (it becomes an OpenAPI component schema); its **properties** are the
fields. Editing classes and properties is how you shape the data model that your published spec
exposes. Every class must carry a description before a version can be published (see the publish
gates in [Publish a version](../ship/publish-a-version.md)).

---

## In the UI

1. Open the **Designer** at `/ade/studio`.
2. Select a class on the canvas (or **Add a class → Browse templates** to start from one of the
   built-in starter templates).
3. Edit the class name and description, then add or edit properties — type, description, required.
4. Changes are saved through the same REST endpoints listed below.

## With the REST API

Update a class (name, description, metadata):

```http
PUT /v1/classes/{tenant_slug}/{class_id}
X-API-Key: <your-api-key>

{ "description": "A pet available in the store." }
```

Update a single property on a class:

```http
PUT /v1/classes/{tenant_slug}/{class_id}/properties/{class_property_id}
X-API-Key: <your-api-key>

{ "description": "Unique identifier for the pet.", "required": true }
```

## With the CLI

The CLI is **read-only** for classes and properties (authoring happens in the UI/REST). Inspect them
with:

```bash
apiome schemas list                       # all classes in the tenant
apiome schemas get <class_id>             # one class
apiome properties list <project>          # the project's property library
```

### List a project's properties

`apiome properties list <project>` lists the project's reusable properties: each one's name, its
**type**, whether its schema marks it required, and the classes that use it.

```bash
apiome properties list payments-api
# NAME         TYPE           REQ?  USED BY
# amount       int64          —     Charge,Refund
# created_at   date-time      yes   Charge,Customer,Refund +1
# customer_id  uuid           —     Charge,Customer
# legacy_ref   string|null    —     —
#
# 4 properties in project 'payments-api'.
```

- **TYPE** is read from the property's JSON Schema: its `format` when it has one (`uuid`,
  `date-time`), otherwise its `type` (`array<string>`, `string|null`). Properties are not bound to
  primitive types.
- **USED BY** lists the classes, in any version of the project, that use the property.
- Properties have no tags, so there is no tag column or filter.

| Option | What it does |
| --- | --- |
| `--type <type>` (or `--primitive`) | Only properties of that type — the whole label or one of its `\|` alternatives (`--type string` matches `string\|null`). |
| `--search <text>` | Only properties whose name or description contains the text (any case). |
| `--unused` | Only properties no class uses. |
| `--limit N` / `--all` | Show the first `N` (default 50) or every match. |

With `--json` it prints `{ "total": …, "items": [...] }`, each item with `used_by` and
`used_by_count`. The older form `apiome properties list --project-id <uuid>` still works.

### Show one property

`apiome properties show <project> <property>` shows one property in a single pane, so you can see
what governs it and who depends on it before you change it. Name the property by its name or its
UUID.

```bash
apiome properties show payments-api amount
# amount  (5f0c9a8e-1b7d-4c3e-9a51-2d6f8e4b7c10)
# ──────────────────────────────────────────────
# Type:         number
# Required:     yes
# Constraints:  minimum=0, multipleOf=0.01
# Examples:     19.99, 1000.0, 0.5
# Description:  Monetary amount in the smallest unit for the currency.
# Enabled:      yes
# Used by:      Charge.amount         (required)
#               Payout.amount         (required)
#               Refund.refund_amount  (optional)
```

- **Type** works the same way as in `properties list`. **Constraints** lists the JSON Schema
  limits the property sets (`minimum`, `maxLength`, `pattern`, `enum` and similar). **Examples**
  comes from its `examples` or `example`.
- **Used by** lists every class attribute, in any version of the project, that uses the property.
  Each one shows whether that class marks it required.
- A **Primitive** row appears only when the property's schema is a `$ref`. Properties have no tags,
  so there is no tags row.
- The name is matched exactly first, then ignoring case. If nothing matches, the command exits
  with code 2 and suggests the closest names, such as `Did you mean: amount?`.

With `--json` it prints the whole property plus a `usage` array of
`{ "class_name": …, "attribute_name": …, "required": … }`. **Used by** needs apiome-rest 1.354.0 or
later. An older server shows it as not reported, and `usage` is `null`.

## Verify

- **UI:** the class shows its new description; properties reflect their edits.
- **Lint:** run [Lint and check quality](./lint-and-quality.md) — documented classes raise the score and
  clear the "missing description" findings that block publishing.

## Related

- [Edit paths and operations](./edit-paths.md) — paths reference these classes in request/response bodies
- [Lint and check quality](./lint-and-quality.md) — see what still needs documenting
