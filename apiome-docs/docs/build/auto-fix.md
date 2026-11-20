---
title: "Auto-fix"
description: "Which lint findings Apiome can repair by itself, and which it never touches."
sidebar_position: 4.6
tags: [lint, quality]
---

Some lint findings have exactly one correct repair. A server URL that ends in a slash loses the
slash. A `nullable: true` in an OpenAPI 3.1 document becomes a `type` array with `"null"`.
For these, a lint rule can carry a **fix**: a small, deterministic edit computed from the
document alone. No AI model is involved, and the same document always gets the same fix.

This page explains which rules are fixable, what kind of edit each fix makes, and where the line
is drawn. The rule catalog shows the same information for every rule; see
[Built-in lint rules](./lint-rules.md).

:::note What ships today

The rule catalog (`GET /v1/lint/rules`) publishes every rule's fix capability, and the first
thirteen OpenAPI rules carry a fix. Asking for a fix plan and applying it from the REST API, the
CLI and the lint report arrive in later releases. Until then nothing in a lint report, score or
grade changes: the twelve new rules below are evaluated only when a fix is asked for.

:::

## How a fix is described

A fix is a list of [JSON Patch](https://www.rfc-editor.org/rfc/rfc6902) operations (`add`,
`remove`, `replace`, `move`) against the document the finding was reported on. Every fixable rule
declares four things, and the catalog publishes them:

| Catalog field | Meaning |
| --- | --- |
| `fixClass` | What kind of edit the fix makes: `structural`, `removal`, `fill-in` or `rename` |
| `wireVisible` | Whether the fix changes what clients see on the wire or in generated code |
| `fixScope` | What the fix may touch: `finding` or `document` |
| `fixDefault` | Whether the fix is applied without being switched on by name |

`fixSummary` is one line saying what the fix does.

## Fix classes

| Class | What it does | Example |
| --- | --- | --- |
| `structural` | Re-spells something without changing its meaning | `example: "Rex"` becomes `examples: ["Rex"]` |
| `removal` | Deletes something that carries no information | An unused component, or `required: []` |
| `fill-in` | Adds a value derived from the document itself | An `operationId` built from the method and path |
| `rename` | Changes how an identifier is spelled | `List_pets` becomes `listPets` |

## A fix stays inside its finding

A fix may only touch the place its finding points at, and anything beneath it. The engine checks
every operation, and refuses the whole fix if one reaches outside. A fix for a finding on
`components.schemas.Pet` cannot edit `components.schemas.Owner`.

One fix needs more room. Renaming a schema moves it to a new key and rewrites every `$ref` that
points to it, anywhere in the document. That rule declares `fixScope: document`, and the catalog
says so. Every other fix has `fixScope: finding`.

## The fixable rules

All thirteen are OpenAPI rules. The three syntax rules at the top apply to documents that declare
OpenAPI 3.1 or later, where the 3.0 spelling is no longer valid.

| Rule | Class | What the fix does |
| --- | --- | --- |
| `structure.nullable-keyword` | `structural` | Adds `"null"` to the schema's `type` (and to `enum`), and removes `nullable` |
| `structure.schema-example-keyword` | `structural` | Moves `example` into a one-item `examples` array |
| `structure.boolean-exclusive-bound` | `structural` | Moves the bound's number onto `exclusiveMinimum` / `exclusiveMaximum` |
| `structure.server-url-trailing-slash` | `structural` | Removes the trailing slash from a server URL |
| `structure.server-url-scheme-case` | `structural` | Lower-cases a server URL's scheme (`HTTPS://` becomes `https://`) |
| `structure.unused-component` | `removal` | Removes a component that nothing references |
| `structure.empty-required` | `removal` | Removes `required: []` |
| `structure.duplicate-tag` | `removal` | Removes a repeated tag declaration |
| `structure.operation-missing-operation-id` | `fill-in` | Adds an `operationId` built from the method and path |
| `structure.operation-missing-tags` | `fill-in` | Adds a tag named after the first path segment. **Off by default** |
| `naming.operation-id-camel-case` | `rename` | Re-cases an `operationId` to camelCase |
| `naming.tag-case-mismatch` | `rename` | Re-cases a tag on an operation to match its declaration |
| `naming.schema-pascal-case` | `rename` | Renames a schema to PascalCase and rewrites its references. **Off by default**, wire-visible |

### The operationId template

A missing `operationId` is built from a template. The default is `{method}{Path}`, which turns
`GET /pets/{petId}` into `getPetsPetId`. The template may use four placeholders:

| Placeholder | Value for `GET /pets/{petId}` |
| --- | --- |
| `{method}` | `get` |
| `{Method}` | `Get` |
| `{path}` | `petsPetId` |
| `{Path}` | `PetsPetId` |

A template must use `{path}` or `{Path}`. If two operations would receive the same id, the later
one gets a number: `getPetsId`, then `getPetsId2`.

### Fixes that are off by default

Two fixes are never applied unless they are switched on by name (`fixDefault: false`):

- **`structure.operation-missing-tags`** guesses a tag from the path. That suits some APIs and
  not others.
- **`naming.schema-pascal-case`** is **wire-visible**: a renamed schema changes the type names in
  every generated SDK.

### When a fix declines

A fixable rule does not promise a fix for every finding. The fix produces nothing when the repair
is not a purely mechanical one, and the finding stays for a person:

- `nullable: true` on a schema with no `type`, or beside a `$ref`.
- `example` on a schema that already has `examples`.
- A duplicate tag that carries its own description.
- An `operationId` whose new spelling is already taken, or that a link refers to.
- A schema whose PascalCase name is already taken.
- An operation with no tags whose path starts with a parameter, such as `/{tenant}/pets`.

## What is never fixed

A fix never invents meaning. These are never fixable, whatever the rule:

- **Descriptions and summaries.** Apiome cannot know what your operation does.
- **Examples.** A missing or non-conforming example needs a real value.
- **Security schemes and requirements.** Guessing these is a risk, not a repair.

The catalog marks who repairs each rule's findings in `fixOwner`:

| `fixOwner` | Meaning |
| --- | --- |
| `engine` | The rule carries a deterministic fix |
| `agent` | The repair needs judgement about meaning: every `documentation` and `security` rule, and the `examples` pack. These are left for an AI assistant or a person, never for a fix |
| `human` | Everything else |

## Read the fix capability of a rule

```http
GET /v1/lint/rules
X-API-Key: <your-api-key>
```

Each rule carries `fixable`, `fixOwner`, and, when it is fixable, `fixClass`, `wireVisible`,
`fixSummary`, `fixScope` and `fixDefault`:

```json
{
  "ruleId": "structure.server-url-trailing-slash",
  "pack": "openapi",
  "category": "structure",
  "defaultSeverity": "info",
  "fixable": true,
  "fixClass": "structural",
  "wireVisible": false,
  "fixSummary": "Removes the trailing slash from the server URL.",
  "fixScope": "finding",
  "fixDefault": true,
  "fixOwner": "engine"
}
```

For a rule that is not fixable, `fixable` is `false` and the other fix fields are `null`. See the
[lint REST reference](/reference/rest/lint).

## Related

- [Built-in lint rules](./lint-rules.md) — every rule, with its fix owner and fix
- [How linting works](./how-linting-works.md) — rule packs, the score and the grade
- [Lint and check quality](./lint-and-quality.md) — read the lint report and the rule catalog
- [Upgrade a spec](./upgrade-a-spec.mdx) — move a whole document from OpenAPI 3.0 to 3.1 or 3.2
