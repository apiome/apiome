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
thirteen OpenAPI rules carry a fix. The REST API plans fixes and applies them as a new revision
(see [Plan the fixes](#plan-the-fixes) and [Apply fixes](#apply-fixes)), and `apiome lint --fix`
does both from the command line for a stored version (see [Fix from the CLI](#fix-from-the-cli)).
Pull requests show the fixes as suggestions (see [Fix suggestions in CI](#fix-suggestions-in-ci)).
Fixing a local file from the CLI, and **Apply fix** in the lint report, arrive in later releases. Nothing in a lint report, score or grade changes because these
rules exist: the twelve new rules below are evaluated only when a fix plan is asked for.

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

## What every fix is tested against

Each fixable rule has a one-defect fixture in the scanner-evaluation corpus
(`apiome-rest/tests/fixtures/scanner_evaluation/fix/<rule id>/`): a small OpenAPI document with
exactly one defect, the plan Apiome must produce for it, and the document it must produce after the
fix. Five gates run in the REST CI on every fixture, so a fix cannot silently change more than its
finding:

1. **After the fix the rule is clean.** The finding is gone, and the fixed document is the expected one,
   key order included.
2. **No other finding changes.** The findings of every other rule, default lint and fixable rules
   alike, are the same before and after.
3. **Byte-stable twice.** Planning and applying a second time changes nothing, and planning the same
   document twice yields the same plan.
4. **The classified diff is non-breaking.** The [classified diff](/reference/rest/classified-diff) of the fix's
   own change must not be breaking. The few fixes the classifier does read as breaking (the
   `nullable` rewrite, the two server URL rules and the schema rename) are pinned in their fixture with
   the reason; the plan withholds them as `breaking` and never applies them. If a classification
   changes, the fixture has to change in review.
5. **No fixable rule without a fixture.** Adding a rule with a fix but no fixture fails the build in
   `test_every_fixable_rule_has_a_fixture`.

The corpus README lists every fixable rule with its fixture, regenerated from the rule registry. See
[the scanner-evaluation corpus](https://github.com/apiome/apiome/blob/main/apiome-rest/docs/scanner_evaluation.md)
for how the corpus is organised and how to add a fixture.

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

## Plan the fixes

A **fix plan** lists every finding a fix could repair, the JSON Patch operations of each fix, and
whether the fix may be applied. Ask for one over a stored revision:

```http
GET /v1/versions/{tenantSlug}/{projectId}/{versionId}/lint/fixes
X-API-Key: <your-api-key>
```

Or over a file, without storing anything (file mode). Send the document as YAML or JSON text:

```http
POST /v1/lint/fixes/plan
X-API-Key: <your-api-key>
Content-Type: application/json

{ "document": "openapi: 3.1.0\ninfo: …" }
```

A revision is planned under its project's style guide. A posted document is planned under your
workspace's style guide. A rule the guide turns off is not planned unless you name it.

Both take the same options:

| Option | Default | Meaning |
| --- | --- | --- |
| `format` | `json` | `json`, `patch`, `overlay` or `diff` (see [Plan formats](#plan-formats)) |
| `rules` | every rule | Plan only these rules. Comma-separated in the query, a list in the body. Naming a rule also selects a fix that is off by default, a rename, or a rule the guide turns off |
| `includeRenames` | `false` | Plan `rename` fixes, including `naming.schema-pascal-case` |
| `operationIdTemplate` | `{method}{Path}` | The [operationId template](#the-operationid-template) |

The same document and options always give a byte-identical plan.

### Plan statuses

Every entry of a plan has a `status`:

| Status | Meaning |
| --- | --- |
| `ready` | The fix may be applied |
| `conflict` | The fix edits the same part of the document as another ready fix. `conflictsWith` names that fix |
| `breaking` | The fix's own change is classified as breaking. It is never applied |
| `excluded` | The fix was not selected. `reason` says why |

**Conflicts.** Two fixes conflict when one edits a node and the other edits that node or
something inside it. The fix of the outer node wins. Removing an unused schema wins over
re-spelling `example` inside it. Plan again after applying the winner: if the loser's finding is
still there, it is ready this time.

**Breaking fixes.** Apiome applies each fix on its own and compares the result with the original
using the [classified diff](/reference/rest/classified-diff). If the change contains anything
breaking, the fix becomes `breaking`, and the entry's `classification` lists the changes. A
schema rename is the usual case: removing the old name breaks clients. The classifier also
treats a changed server URL (trailing slash, scheme case) as a removed server, and a widened
`type` array as a type change, so those fixes are `breaking` too.

**Exclusions.** `reason` is one of:

| `reason` | Why |
| --- | --- |
| `not-selected` | You named other rules in `rules` |
| `guide-disabled` | The style guide turns the rule off |
| `renames-not-included` | It is a `rename` fix and `includeRenames` is `false` |
| `opt-in-required` | The fix is off by default (`structure.operation-missing-tags`) |

An excluded entry still lists its operations, so you can see what it would do.

### A plan entry

```json
{
  "fixId": "fix-05817bbcff5519df",
  "ruleId": "structure.empty-required",
  "fixClass": "removal",
  "wireVisible": false,
  "path": "components.schemas.Order",
  "pointer": "/components/schemas/Order",
  "findingId": "lint-05817bbcff5519df",
  "message": "Schema declares an empty required list.",
  "ops": [{ "op": "remove", "path": "/components/schemas/Order/required" }],
  "status": "ready",
  "reason": null,
  "conflictsWith": null,
  "classification": {
    "maxSeverity": null,
    "counts": { "breaking": 0, "non-breaking": 0, "docs-only": 0, "unclassified": 0, "total": 0 },
    "changes": []
  }
}
```

The plan also returns `counts` (entries per status), `appliedOrder` (the ready fixes in the order
they are applied), `documentFingerprint` and `fixedDocumentFingerprint`. A revision's plan adds
`reportFingerprint` and `reportCurrent`: the fingerprint of the revision's stored lint report and
whether that report still matches the planned document.

### Plan formats

| `format` | Returns |
| --- | --- |
| `json` | The plan, as above |
| `patch` | One [JSON Patch](https://www.rfc-editor.org/rfc/rfc6902) document with the ready fixes' operations, in the order they apply (`application/json-patch+json`) |
| `overlay` | The same change as an [Overlay 1.0](/build/overlay-manager) document. Each operation becomes a `remove` and/or an `update` action, and `info.title` names the rules |
| `diff` | A unified diff of the document before and after, as indented JSON (`text/x-diff`) |

The `overlay` output produces the same document as the patch. Keep it instead of editing your
source: store it in the revision's overlay chain, or apply it at export.

## Apply fixes

```http
POST /v1/versions/{tenantSlug}/{projectId}/{versionId}/lint/fixes/apply
X-API-Key: <your-api-key>
Content-Type: application/json

{ "fixIds": ["fix-05817bbcff5519df"], "reason": "Tidy before review" }
```

Name the fixes in exactly one of:

- **`fixIds`**: fixes from the plan. Each must be `ready`.
- **`rules`**: every `ready` fix of these rules. Fixes of those rules that are not ready are
  listed in the response's `skipped`.

`reason` is required and is recorded on the audit entry. The body also takes `includeRenames`,
`operationIdTemplate` and `versionLabel`. Send the same `includeRenames` and
`operationIdTemplate` you planned with, so the fix ids match.

Applying needs the `versions:edit` permission, and the revision must not be published.

**Apply never changes the revision.** Apiome builds the fixed document and imports it as a
**new revision** of the same project, through the import quality gate, like an upload. Then it:

1. lints the new revision and stores its report;
2. records `source: lint-fix` on the new revision, with the fix ids, the rules and your reason;
3. writes a `version.lint_fix_applied` audit entry.

Steps 2 and 3 are written together. If they cannot be written, the new revision is withdrawn, so
an apply leaves one audited revision or nothing. The response names the new revision
(`versionRecordId`, `versionLabel`), the fixes applied, and its new score and grade.

| Status | Code | When |
| --- | --- | --- |
| 409 | `lint-fix-version-published` | The revision is published |
| 422 | `lint-fix-breaking` | A named fix is `breaking`, or every fix of the named rules is |
| 422 | `lint-fix-conflict` | A named fix is a `conflict`. Apply the fix it conflicts with first |
| 422 | `lint-fix-excluded` | A named fix is `excluded`. Name its rule in `rules`, or set `includeRenames` |
| 422 | `lint-fix-unknown` | A fix id is not in the revision's plan |
| 422 | `lint-fix-nothing-to-apply` | The named rules have no ready fixes |
| 422 | `lint-fix-invalid-options` | An unknown rule, or an invalid operationId template |
| 422 | `lint-fix-not-openapi` | The revision is not an OpenAPI 3.x document |

Applying every `ready` fix and then planning again leaves nothing ready.

## Apply fixes in the UI

Both UI surfaces call the same apply endpoint, with a reason:

- **Versions → lint report:** a **Fix** chip on each fixable finding and **Apply N deterministic
  fixes** for all ready ones. See [Version dialogs → Lint report](./version-dialogs.mdx#lint-report).
- **Lint posture:** **Apply fix** in a finding's drawer and in the bulk bar, for findings on catalog
  revisions. The finding moves to **Fixed** only once the new revision's lint report no longer lists
  it. See [Lint posture → Apply a fix](../govern/lint-posture.mdx#apply-a-fix).

Only `ready` fixes are offered. `breaking` and `conflict` entries show their reason, and a published
revision's fixes are read-only.

## Fix from the CLI

`apiome lint --fix` plans a version's fixes and applies the ready ones as a new revision, like
[Apply fixes](#apply-fixes). Add `--dry-run` first to see the change without writing anything:

```bash
apiome lint --project payments-api --version 1.0.0 --fix --dry-run
```

The summary goes to stderr and the change to stdout, as a unified diff of the document before and
after:

```text
Fix plan: 2 ready, 0 conflict, 1 breaking, 0 excluded
  ready     structure.empty-required  components.schemas.Order
  ready     structure.nullable-keyword  components.schemas.Order.properties.note
  breaking  structure.server-url-trailing-slash  servers[0]  (the change is breaking; never applied)
Dry run: nothing was written.
```

```diff
--- a/openapi.json
+++ b/openapi.json
@@ -20,10 +20,10 @@
       "Order": {
         "properties": {
           "note": {
-            "nullable": true,
-            "type": "string"
+            "type": [
+              "string",
+              "null"
+            ]
           }
         },
-        "required": [],
         "type": "object"
       }
```

Drop `--dry-run` to apply. The CLI prints the plan again, then the new revision:

```text
Applied 2 fixes as new revision 1.0.1 (dddddddd-dddd-4ddd-8ddd-dddddddddddd).
  Score 91  grade A
1 fix need a person:
  1 breaking: never applied; change the API by hand.
```

The revision you planned on is never changed, and the apply needs the same permission and an
unpublished revision as the REST call. Its audited reason is `Applied with apiome lint --fix`.

| Option | Meaning |
| --- | --- |
| `--dry-run` | Print the change and write nothing |
| `--only rule,rule` | Fix only these rules. An unknown rule id is refused, and nothing is planned. Naming a rule also selects a fix that is off by default or a rename, as `rules` does |
| `--allow-renames` | Include `rename` fixes (`includeRenames`) |
| `--fix-format diff\|patch\|overlay` | Print or write the change as a unified diff (the default), one JSON Patch, or an Overlay 1.0 document |
| `-o`, `--output <file>` | Write the change to this file. On a dry run the summary then stays on stdout; without `--dry-run`, the file records what was applied |

A **breaking** fix is never applied, whatever the options, `--allow-renames` included. `--json`
prints the plan (with `--dry-run`), or the plan and the apply response as `{"plan", "applied"}`.

### Exit codes

| Code | When |
| --- | --- |
| `0` | Nothing to fix, or every ready fix was applied. A dry run always exits `0` when the plan was read |
| `3` | Fixes remain that need a person: a **breaking** fix, or a **conflict** (run `--fix` again on the new revision, and it is ready) |
| `2` | A refused request: an unknown `--only` rule, a published revision, a missing permission, or an option given without `--fix` |
| `1` | Apiome could not be reached, or a server error |

See the [`apiome lint` reference](/reference/cli/lint) and [Exit codes](/reference/cli/exit-codes).

### Local files

`apiome lint <file> --fix`, which rewrites a local file in place, follows the local-file lint of
`apiome lint <file>`. Until that command exists, plan a file with
[`POST /v1/lint/fixes/plan`](#plan-the-fixes). When it lands, a YAML file keeps its comments, key
order, quoting and indentation, and a JSON file keeps its key order and indentation: only the
places a fix changes are rewritten.

## Fix suggestions in CI

A reviewer can tell from the pull request which lint failures are mechanical, without opening a
terminal. Three CI summaries carry a **Suggested fixes** section. Each lists the number of
**ready** fixes per rule, the fix class and the first hunk of one fix as a `diff` snippet. It
also says how many **breaking** and **conflict** fixes are left for a person. Suggestions are
never applied for you: nothing is written to the version or pushed to the branch.

| Where | What it shows |
| --- | --- |
| `apiome lint gate --format markdown` | The section before *Provenance*, planned over the stored version. It links `GET …/lint/fixes?format=patch` and `?format=overlay` |
| `apiome checks run --format md` and the provider check run | The section under the evidence of the API change check suite. The provider check's summary is this text, so the pull request shows the fix count and the patch link |
| [diff-action](/reference/ci/diff-action#suggested-fixes) | A second section of the one sticky comment, planned over the spec file in the pull request. It adds one-click suggestion blocks and a workflow artefact |

The version summaries plan with the default options: every rule the style guide turns on, without
renames. The linked patch therefore holds the same bytes as
`apiome lint --project P --version V --fix --dry-run --fix-format patch`. A version that is not
OpenAPI 3.x has no section.

### Suggest fixes for a spec file

`apiome lint suggest <file>` plans a local file ([`POST /v1/lint/fixes/plan`](#plan-the-fixes),
nothing stored). Each ready fix is applied on its own to the file's text, so the snippets and line
numbers are those of the file itself, YAML comments included. The file is never rewritten.

```bash
apiome lint suggest api/openapi.yaml                       # the Suggested fixes section (Markdown)
apiome lint suggest api/openapi.yaml --format json         # rules, plus a line range per fix
apiome lint suggest api/openapi.yaml --format patch -o fixes.patch.json
```

| Option | What it does |
| --- | --- |
| `--format` | `markdown` (default), `json`, or the full change as `patch`, `overlay` or `diff` (the plan endpoint's bytes) |
| `--path` | The file's path as the pull request names it, used in the section (default: the path you gave) |
| `--artifact-url` | With `markdown`: link the full patch and overlay at this URL |
| `--only`, `--allow-renames` | As for [`--fix`](#fix-from-the-cli) |
| `-o` | Write to this file instead of standard output |

With `--format json`, `suggestions` lists every ready fix that changes **one region** of the file.
Each has its `startLine`, `endLine` and the `replacement` text for those lines. That is what a
GitHub `suggestion` block needs. A fix that changes several places is listed under `rules` only. The
command exits `0` whatever it suggests.

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
- [Lint REST reference](/reference/rest/lint) — the plan and apply endpoints
- [`apiome lint` CLI reference](/reference/cli/lint) — `--fix`, `--dry-run`, `suggest` and the other options
- [diff-action](/reference/ci/diff-action#suggested-fixes) — suggested fixes on a pull request
