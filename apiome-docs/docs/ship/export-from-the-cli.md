---
title: "Export from the CLI"
description: "Export a version to any format from a terminal or CI, gated on fidelity."
sidebar_position: 5.1
tags: [export, cli, ci, fidelity, preflight, toolchain]
---

`apiome export` writes a version in any format Apiome exports: OpenAPI, AsyncAPI, GraphQL,
Protobuf, Avro, Thrift, Smithy, TypeSpec and the rest. It runs the same export job as the
**Export** dialog, so the file, its fidelity report and its checks are the same as in the app. Use it
in a terminal, or in a CI job that should fail when an export loses too much.

## When to use it

- **In CI**, to publish a version in other formats on every release, and fail the build when an
  export is lossy or its lint grade falls below your bar.
- **In a terminal**, to get one file quickly, or several formats or catalog items in one archive.

To export from the app instead, see [Export a spec](./export-a-spec.md).

## At a glance

| Step | Command | Details |
| --- | --- | --- |
| **List** the targets and how faithful each would be | `apiome export targets` | [Understand export fidelity](./export-fidelity.md#from-the-cli) |
| **Rank** the targets and check the quality policy, without exporting | `apiome export preflight` | [Target readiness](./export-fidelity.md#target-readiness-the-pre-flight-ranking) |
| **See why** a construct changes or is lost | `apiome export evidence --target <format>` | [Understand export fidelity](./export-fidelity.md#from-the-cli) |
| **Export** to one format | `apiome export <format> <project>` | [Export to one format](#export-to-one-format) |
| **Export** to several formats, or several items | `--targets`, `--items` | [Several formats or several items](./export-a-spec.md#from-the-cli-several-formats-or-several-items) |
| **Apply overlays** first | `--overlay FILE` | [Apply overlays when you export](./export-a-spec.md#apply-overlays-when-you-export) |
| **Gate** on fidelity and lint | `--force`, `--min-grade`, `--fail-on` | [Gate a pipeline](#gate-a-pipeline) |

## Export to one format

Name the format, then the project (id or slug):

```bash
apiome export thrift payments-api --version 1.0.0 --out payments.thrift
apiome export typespec payments-api --out main.tsp
apiome export postman payments-api --flavor bruno --out collection.zip
apiome export mcp payments-api --out payments.mcp.json --force   # MCP tools for an agent
apiome export a2a payments-api --out agent-card.json --force     # an A2A Agent Card
apiome export xregistry orders-api --out orders.xregistry.json --force  # an xRegistry document
apiome export sql orders-api --out orders.sql --dialect mysql --force  # SQL DDL (also dbml, prisma, liquibase, flyway)
apiome export bigquery orders-api --out lake/ --force             # BigQuery schemas (also parquet, spark, iceberg)
```

Any format the server can export is a `<format>`: `apiome export targets --project <project>`
lists them for a version. The command submits an export job, waits for it, and writes the result to
`--out`: a file, a directory for a format that writes several files, a `.zip` path, or `-` for
stdout. Without `--version`, the latest version is exported.

| Flag | What it does |
| --- | --- |
| `--version` | The version: id, slug or label. Default: the latest. |
| `--out` | Where to write: a file, a directory, a `.zip` path, or `-` for stdout. |
| `--option KEY=VALUE` | A per-target option, repeatable. Options change the fidelity snapshot. |
| `--force` | Exit 0 even when the export is lossy or types-only. |
| `--confirm` | Go ahead with a severe conversion that would otherwise be blocked. |
| `--export-timeout`, `--poll-interval` | How long to wait for the job, and how often to check it. |

OpenAPI, AsyncAPI, GraphQL, gRPC and Avro also have dedicated commands with `--project`,
`--version` and `--output`, such as `apiome export openapi --project payments-api --version 1.0.0
-o openapi.yaml --yaml`. See the [`apiome export` reference](../reference/cli/export.md).

With `-` as the output, only the document goes to stdout. The fidelity summary goes to stderr, so a
pipe receives the exact bytes.

## The fidelity report

Every export prints its fidelity on stderr: how much of the version the target format keeps, as a
tier (`lossless`, `lossy` or `types-only`) and a share preserved. To see what a target will lose
before you export, list the targets, then page the evidence for one of them:

```bash
apiome export targets  --project payments-api --version 1.0.0
apiome export evidence --project payments-api --version 1.0.0 --target avro
```

With the global `--json`, `export evidence` returns the snapshot hash, the status and reason counts,
and one row per construct. See [Understand export fidelity](./export-fidelity.md) for what the tiers,
statuses and reasons mean.

## Gate a pipeline

An export that loses fidelity, or does not meet your lint bar, fails the command:

- **Lossy or types-only.** The command exits **1** unless you pass `--force`. In an interactive
  terminal it asks first.
- **`--min-grade A`–`F`.** Exits **4** when the exported file's lint grade is worse.
- **`--fail-on error|warning|info`.** Exits **4** when the lint report has a finding at or above
  that severity.
- **The tenant's export quality policy.** Exits **3** when the policy blocks the export.

`--min-grade` and `--fail-on` gate one project and one format, so they cannot be combined with
`--targets` or `--items`. To gate before anything is exported, run `apiome export preflight` with the
same flags: it ranks every target and exits **3**, **4**, or **5** when no target is usable.

```bash
# In CI: fail the build if the Avro export is lossy or its lint grade is worse than B
apiome export avro --project payments-api --version "$VERSION" -o dist/payments.avsc --min-grade B
```

See [Exit codes](../reference/cli/exit-codes.md) for every code.

## Checked with the format's own tool

Before an export is delivered, it is validated. For many formats Apiome uses the tool that format's
community uses, the same tool it runs when it imports that format: `buf` for Protobuf, `tsp` for
TypeSpec, the Smithy CLI, AMF for RAML, drafter for API Blueprint, `flatc`, `capnp` and others. A
blocked export exits non-zero and prints the error and the job's log lines. See
[Exports checked with the format's own tool](./export-a-spec.md#exports-checked-with-the-formats-own-tool)
and [How an export is checked](./check-an-export.mdx).

## Related

- [`apiome export` reference](../reference/cli/export.md): every subcommand and flag
- [How an export runs](./export-jobs.mdx): the job pipeline behind every export
- [Manage versions from the CLI](./manage-versions-from-the-cli.md): cut and publish the versions you export
