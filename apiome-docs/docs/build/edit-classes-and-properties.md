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

The CLI can list a version's classes and create new ones, and can list, show, create, update,
delete and copy the project's properties. Editing an existing class still happens in the UI or
through the REST API.

```bash
apiome classes list <project> <version>   # a version's classes
apiome schemas get <class_id>             # one class
apiome properties list <project>          # the project's property library
```

### List a version's classes

`apiome classes list <project> <version>` lists the classes in one version: each one's name, how many
properties it has, its tags and its description. Name the version by its label (`2.1.0` or
`v2.1.0`), its UUID or a version tag such as `stable`.

```bash
apiome classes list payments-api v2.1.0
# NAME      #PROPS  TAGS             DESCRIPTION
# Charge    11      core, financial  Inbound payment from a customer.
# Customer  9       identity, pii    End-user / payer record.
# Refund    7       financial        Reversal of a charge.
#
# 3 classes in payments-api 2.1.0.
```

**#PROPS** counts a class's top-level properties. Properties nested under another property aren't
counted.

Add `--with-properties` to see each class's properties under its name. Each line shows the
property's name, type and whether it's required, and nested properties are indented. The whole
version comes back in one request.

```bash
apiome classes list payments-api v2.1.0 --with-properties
# Charge  (3 properties · core, financial)  Inbound payment from a customer.
#   NAME        TYPE       REQ?
#   amount      number     yes
#   created_at  date-time  yes
#   metadata    object     —
#     note      string     —
```

| Option | What it does |
| --- | --- |
| `--tag <tag>` | Only classes with that tag (any case). |
| `--search <text>` | Only classes whose name or description contains the text (any case). |
| `--with-properties` | Show each class's properties. |
| `--limit N` / `--all` | Show the first `N` (default 50) or every match. |

With `--json` the command prints the classes exactly as the API returns them, after the filters and
the limit are applied: the plain list, or with `--with-properties` the list with properties and tags
inline. The property count and tags need apiome-rest 1.357.0 or later; an older server shows `?` in
**#PROPS**.

### Create a class

`apiome classes create <project> <version>` adds a class to a **draft** version, along with its
properties and tags. The properties come from the project's property library.

On a terminal, run it with just the project and version and answer the prompts:

```bash
apiome classes create payments-api v2.2.0-rc.1
# ? Class name: Refund
# ? Description: Reversal of a charge.
# ? Tags (comma-separated): financial
# ? Add properties now? [Y/n]: y
# ? Property (type to search, empty to finish): am
#   Required in this class? (amount) [y/N]: y
# ? Property (type to search, empty to finish):
# Create class 'Refund' with 1 property in 2.2.0-rc.1? [Y/n]: y
# ✔ Created class 'Refund' with 1 property.
#   New project tags: financial
```

Pick properties one at a time. Type part of a name to list the matches; if only one property
matches, it is chosen. For each property, answer whether this class requires it. Leave the answer
empty when you're done.

In a script, pass the class as flags or from a file:

```bash
apiome classes create payments-api v2.2.0-rc.1 \
  --name Refund \
  --description 'Reversal of a charge.' \
  --tag financial \
  --property amount:required \
  --property currency:required \
  --property reason \
  --yes

apiome classes create payments-api v2.2.0-rc.1 --from-file ./classes/refund.yaml --yes
```

```yaml title="classes/refund.yaml"
name: Refund
description: Reversal of a charge.
tags: [financial]
properties:
  - amount:required
  - currency:required
  - reason                              # optional
  - {name: note, required: false}       # the object form works too
```

| Option | What it does |
| --- | --- |
| `--name <name>` | The class name. It must be new in the version. |
| `--description <text>` | What the class represents. |
| `--tag <tag>` | A project tag, repeatable. Tag names are lower-cased. A tag the project doesn't have yet is created. |
| `--property <name>[:required]` | A property from the project's library, repeatable. Add `:required` if the class requires it. |
| `--from-file <path>` | A JSON or YAML class spec with `name`, `description`, `tags` and `properties`. A flag overrides the same field in the file. |
| `--create-missing` | Create properties that aren't in the library yet. The command asks for each one's primitive, so it needs a terminal. |
| `--yes` | Skip the final question the prompts ask. |

Each property is attached as a copy of its library definition, with **required** set for this
class.

**What can stop it.** Nothing is created in these cases:

- The version is published or frozen. The command exits with code **6**. Create a draft version and
  add the class there.
- A field is wrong: the name is missing or already used in the version, a property is listed twice,
  or a property isn't in the library (without `--create-missing`). The command lists every problem,
  one line per field, and exits with code **7**.

The class is created first, then its properties and tags are attached one at a time. If one of
those steps fails, the class is deleted again and the command exits with code **1**, so you can fix
the problem and run it again with the same name. Project tags and properties created along the way
are kept. With `--json` the command prints the created class, its properties and tags, and which
tags and properties it created.

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

### Delete a property

`apiome properties delete <project> <property>` deletes a property. It first checks which classes use
the property. Name the property by its name or UUID.

If no class uses it, type the property name to confirm:

```bash
apiome properties delete payments-api unused_prop
# Used by 0 classes — safe to delete.
# Type the property name to confirm: unused_prop
# ✔ Deleted property 'unused_prop'.
```

If classes use it, nothing is deleted. The command lists the class attributes and exits with code
**6**:

```bash
apiome properties delete payments-api amount
# ✘ Property 'amount' is in use by 3 class attributes:
#      Charge.amount  (required)
#      Payout.amount  (required)
#      Refund.amount  (optional)
# Hint: remove the attribute from those classes in the Studio,
#       or pass --force --yes to remove them and delete the property in one step.
```

To go ahead anyway, either remove the attribute from each class in the Studio and run the command
again, or pass `--force --yes`. With `--force`, the server removes the property from every class that
uses it, along with any attributes nested under it, and then deletes it, all in one transaction.
Published versions can't change, so if any class in a published version uses the property, nothing is
deleted and the command lists those classes with their versions (exit code **6**). Remove the
property from those classes in a new draft version first.

| Option | What it does |
| --- | --- |
| `--yes` | Skip typing the name. |
| `--force` | Remove the property from the classes that use it, then delete it. Requires `--yes`. |

With `--json` the command prints `{ "deleted": true, "property": …, "property_id": …, "detached": … }`,
where `detached` is how many class attributes were removed.

### Copy properties to another project

`apiome properties copy <source-project> <names> --to <destination-project>` reuses property
definitions in another project of the same tenant. Each copy takes the property's name, description
and schema.

```bash
apiome properties copy payments-api amount --to billing-api
# ✔ Copied 'amount' from payments-api → billing-api.

apiome properties copy payments-api amount --to billing-api --rename gross_amount
apiome properties copy payments-api 'amount,currency,customer_id' --to billing-api
apiome properties copy payments-api --all --to billing-api --dry-run
```

Name one property or several, separated by commas, or pass `--all` to copy every property of the
source project. When more than one property is written, the command shows its progress as
`[1/3] amount: created` and then a summary.

| Option | What it does |
| --- | --- |
| `--to <project>` | The destination project. Required. You can also write `<tenant>/<project>`, but only for the current tenant. |
| `--all` | Copy every property of the source project. |
| `--rename <name>` | Use another name in the destination. Works with exactly one property. |
| `--skip-conflicts` | Leave a destination property with the same name alone. This is the default. |
| `--update` | Overwrite a destination property with the same name. The command asks first; `--yes` skips the question. |
| `--dry-run` | List what would be created, overwritten or skipped, and write nothing. |

**Conflicts.** If the destination already has a property with the same name, it is skipped and
named in the summary. Pass `--update` to overwrite it instead. An overwrite fails if someone changes
that property while the copy runs.

**Primitives.** Before anything is written, every `$ref` in the copied schemas is checked against
the tenant's primitives. If a reference matches none of them, the command lists each property and
reference, copies nothing and exits with code **7**. Import the missing primitives into the tenant
first, then run the copy again.

**Other tenants.** Properties can only be copied within one tenant. Naming another tenant, as in
`--to globex/billing-api`, exits with code **4**. To move properties to another tenant, export them
and import them there.

If a write fails, the copy carries on with the rest, lists each failure in the summary and exits
with code **1**. Properties have no tags, so there is nothing else to copy. With `--json` the
command prints each property's `source`, `target`, `action` and `result`.

## Verify

- **UI:** the class shows its new description; properties reflect their edits.
- **Lint:** run [Lint and check quality](./lint-and-quality.md) — documented classes raise the score and
  clear the "missing description" findings that block publishing.

## Related

- [Edit paths and operations](./edit-paths.md) — paths reference these classes in request/response bodies
- [Lint and check quality](./lint-and-quality.md) — see what still needs documenting
