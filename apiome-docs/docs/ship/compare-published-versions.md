---
title: "Compare published versions"
description: "Diff two published versions from the CLI, for people and CI."
sidebar_position: 5.5
tags: [cli, ci, export]
---

`apiome schema diff` compares two **published** versions of a project. It fetches both OpenAPI
documents from the public schema route, so it needs no login, and reports which **paths**,
**classes** and **properties** were added, removed or changed. It works the same for a person at
a terminal and as a one-line CI check.

It lists *what* changed. To grade changes as breaking or not, use
[`apiome versions compatibility`](../reference/ci/version-compatibility-gate.md), which asks the
server's compatibility engine.

## Run it

```bash
apiome schema diff acme-corp/payments-api 2.0.0 2.1.0
```

```text
Comparing 2.0.0 → 2.1.0 …
  + 2 added paths (GET /refunds/{id}, POST /refunds)
  - 1 removed path (GET /v1/charges/legacy)
  ~ 1 changed path (POST /charges)
  + 1 added class (Refund)
  - 1 removed class (Payout)
  ~ 2 changed classes (Charge, Customer)
  + 1 added property (Charge.refunded)
  - 1 removed property (Charge.legacy_code)
  ~ 2 changed properties (Charge.amount, Customer.email)

Use `--format unified` or `--format json` for the full diff.
```

The first argument is `tenant/project` (slugs, as in the browse URL). The two versions are labels,
older first. A label typed as `v2.1.0` that is not found is retried as `2.1.0`. For a private
version, set `APIOME_API_KEY`.

## What counts as a change

| Kind | One row per | Shown as |
|---|---|---|
| Path | operation (method + path); shared path-item keys such as `parameters` are a row of their own | `POST /refunds`, `/customers/{id}` |
| Class | schema under `components.schemas` | `Charge` |
| Property | entry of a class's `properties`, for classes in **both** versions | `Charge.amount` |

The properties of an added or removed class are part of that class's row, not counted again. Changes
to `info` (the version number, the title) are not differences, so two versions with the same paths
and schemas are **identical**.

## Flags

| Flag | What it does |
|---|---|
| `--format summary\|unified\|sarif\|json` | **summary** (default) is the text above. **unified** is a unified diff of both documents as sorted, indented JSON — pipe it into `less`. **json** is the change list with counts. **sarif** is a SARIF 2.1.0 log, one `note` per change, for code-scanning tools. The global `--json` means `--format json`. |
| `--scope paths\|schemas\|all` | Compare only operations, only classes and properties, or both (default). |
| `--ignore description-only` | Drop changes where only `description` or `summary` text differs. Repeatable. |
| `--exit-code` | Git-like: exit **1** if the versions differ, **0** if they are identical. |
| `--output FILE`, `-o` | Write the output to a file instead of stdout. |

## Use it in CI

Fail a job when the version you pinned has moved on from the one you built against:

```bash
apiome schema diff acme-corp/payments-api 2.0.0 2.1.0 --exit-code --ignore description-only
```

| Exit | Meaning |
|---|---|
| `0` | Identical (with `--exit-code`), or the diff was printed. |
| `1` | With `--exit-code`: the versions **differ**. |
| `2` | Bad usage, or a version is unknown, unpublished or private without an API key. With `--exit-code`, also a network or server error, so `1` always means "differs". |

Without `--exit-code`, a network or server error exits `1`, as for every other command.

To keep the evidence, write SARIF or JSON as a build artifact:

```bash
apiome schema diff acme-corp/payments-api 2.0.0 2.1.0 --format sarif -o schema-diff.sarif
apiome schema diff acme-corp/payments-api 2.0.0 2.1.0 --format json  -o schema-diff.json
```

## Related

- [Export a spec](./export-a-spec.md) — download one published version (`schema arazzo`,
  `schema json`, `spec export`)
- [Version compatibility gate](../reference/ci/version-compatibility-gate.md) — grade the changes
  between two versions as breaking or not
- [`apiome schema` reference](../reference/cli/schema.md) — every flag
