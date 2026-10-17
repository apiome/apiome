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

### Create a property

`apiome properties create <project>` adds a property to the project's library. You start from a
**primitive**: the command copies the primitive's JSON Schema into the new property and adds your
examples.

On a terminal, run it with just the project and answer the prompts:

```bash
apiome properties create payments-api
# ? Name: amount
# ? Primitive (type to search): iso
#   Matches: iso4217-money, iso8601-date
# ? Primitive (type to search): iso4217-money
# ? Description: Monetary amount in smallest unit.
# ? Examples (comma-separated): 19.99, 1000.00
# Create property 'amount' from primitive 'iso4217-money'? [Y/n]: y
# ✔ Created property 'amount'.
```

Type part of a primitive's name to list the matches. If only one primitive matches, it is chosen.
The command keeps the tenant's primitive list for 5 minutes, so the matches appear straight away.
Without a terminal, or with `--no-input`, nothing is asked and a missing name or primitive is an
error.

In a script, pass the fields as flags or from a file. Both send the same request as the prompts:

```bash
apiome properties create payments-api \
  --name amount \
  --primitive iso4217-money \
  --description 'Monetary amount in smallest unit.' \
  --example 19.99 --example 1000.00 \
  --yes

apiome properties create payments-api --from-file ./props/amount.yaml --yes
```

```yaml title="props/amount.yaml"
name: amount
primitive: iso4217-money
description: Monetary amount in smallest unit.
examples:
  - 19.99
  - 1000.00
```

| Option | What it does |
| --- | --- |
| `--name <name>` | The property name. It must be new in the project. |
| `--primitive <primitive>` | The primitive to copy, named by its name (any case), UUID or `$id`. It must exist. |
| `--description <text>` | What the property holds. |
| `--example <value>` | An example, repeatable. Text that parses as JSON (`19.99`, `true`) is read as JSON, anything else as a string. |
| `--from-file <path>` | A JSON or YAML object with `name`, `primitive`, `description` and `examples`. A flag overrides the same field in the file. |
| `--yes` | Skip the final question the prompts ask. |

Before anything is sent, each example is checked against the primitive's schema, including its
`format`. Nothing is created if a field is wrong. The command lists every problem, one line per
field, and exits with code **7**:

```text
name: the project already has a property 'amount'
primitive: no primitive 'iso4217-mony' in this tenant. Did you mean: iso4217-money?
examples[0]: -1 — -1 is less than the minimum of 0
Nothing was created.
```

Properties have no tags, so there is no `--tag` option. A `tags` key in the file is reported as an
error. With `--json` the command prints the created property.

### Update a property

`apiome properties update <project> <property>` changes a property. Name the property by its name
or UUID. Only the fields you change are sent.

```bash
apiome properties update payments-api amount \
  --description 'Monetary amount in the smallest unit for the currency.' \
  --add-example 1234.56
# ✔ Updated property 'amount': description, data.examples.
```

| Option | What it does |
| --- | --- |
| `--name <name>` | Rename the property. The new name must be free in the project. |
| `--description <text>` | Replace the description. An empty string clears it. |
| `--add-example <value>` / `--remove-example <value>` | Add or remove an example, repeatable. Values are read the same way as in `properties create` (`19.99` is a number). |
| `--primitive <primitive>` | Copy the schema from another primitive. The property keeps its examples and its required flag. |
| `--required-everywhere` / `--optional-everywhere` | Mark the property required (or optional) on every class attribute that uses it, in unpublished versions. |
| `--from-file <path>` | Apply an edited `properties show --json` dump, in JSON or YAML. It can't be combined with the options above. |
| `--allow-breaking` | Change the primitive even though classes require the property. |
| `--dry-run` | Print the changes as a diff and send nothing. |
| `--yes` | Skip the question that `--primitive` and `--required-everywhere` ask. |

**Preview a change.** Add `--dry-run` to see the diff without changing anything. Each changed field
gets a `-` line (now) and a `+` line (after). Schema keys appear one by one, such as
`data.examples`:

```bash
apiome properties update payments-api amount --from-file ./props/amount.yaml --dry-run
# Property amount (5f0c9a8e-1b7d-4c3e-9a51-2d6f8e4b7c10)
# - description: "Amount."
# + description: "Monetary amount in the smallest unit for the currency."
```

**Edit from a file.** Save the property with
`apiome properties show payments-api amount --json > amount.json`, edit `name`, `description`,
`data` or `enabled`, and pass the file to `--from-file`. The file's `updated_at` is checked when the
update is applied. If someone changed the property after you saved the file, nothing is written and
the command exits with code **6**. Save the property again, re-apply your edit and retry. Updates
made with flags are checked the same way against the property as it was just read.

**Change the primitive.** A property keeps its own copy of its primitive's schema, and each class
keeps its own copy too. Changing the primitive replaces the property's schema but does not change
any class. If any class uses the property as required, the command lists those class attributes,
exits with code **6** and changes nothing. Pass `--allow-breaking` to go ahead. The command asks
before applying the change; `--yes` skips the question.

**Make it required everywhere.** `--required-everywhere` (or `--optional-everywhere`) sets the
required flag on every class attribute that uses the property, together with any other change.
Published versions are never touched. The command shows which attributes will change and asks
first. Afterwards it reports how many changed, how many already matched and how many it left alone
in published versions.

As with `properties create`, a taken name or an example the schema rejects is reported one line per
field, with exit code **7**. Properties have no tags, so there are no tag options, and a `tags` key
in the file is refused. With `--json` the command prints the updated property, or the planned
changes and request when combined with `--dry-run`.

## Verify

- **UI:** the class shows its new description; properties reflect their edits.
- **Lint:** run [Lint and check quality](./lint-and-quality.md) — documented classes raise the score and
  clear the "missing description" findings that block publishing.

## Related

- [Edit paths and operations](./edit-paths.md) — paths reference these classes in request/response bodies
- [Lint and check quality](./lint-and-quality.md) — see what still needs documenting
