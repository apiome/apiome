---
title: "Version compatibility gate in CI"
description: "Fail a build when a project version introduces a breaking change."
sidebar_position: 7
tags: [ci, cli, versions]
---

`apiome versions compatibility` compares two versions of a project with Apiome's compatibility
engine and exits non-zero when the newer one breaks the older one. It is the canonical CI gate for
"fail the build if my new draft introduces a breaking schema change".

```bash
apiome versions compatibility payments-api --base v2.0.0 --head v2.1.0
# Comparing 2.0.0 → 2.1.0 …
#   ╔══════════╤═══════════════════════════════════════════════════════════════════════════╗
#   ║ SEVERITY │ FINDING                                                                   ║
#   ╠══════════╪═══════════════════════════════════════════════════════════════════════════╣
#   ║ ✖ error  │ - removal  path_removed  /paths/~1v1~1charges~1legacy — Path removed      ║
#   ║ · info   │ + addition  schema_added  /components/schemas/RefundReason — Schema added ║
#   ║ · info   │ + addition  operation_added  /paths/~1refunds/post — Operation added      ║
#   ╚══════════╧═══════════════════════════════════════════════════════════════════════════╝
#
# Result: 1 breaking change found (path_removed /paths/~1v1~1charges~1legacy).
```

Both sides are versions **already stored in Apiome** — to gate a local OpenAPI file against a
published version instead, use [`apiome diff`](./ci-diff-gate.md).

## Exit codes

| Exit | Meaning |
| --- | --- |
| `0` | No breaking change, or every breaking change was suppressed. |
| `6` | At least one unsuppressed breaking change. |
| `8` | The server could not be reached, or failed fetching either side — no verdict. |
| `2` | A bad argument, or a version / tag that does not exist. |

## Options

| Option | What it does |
| --- | --- |
| `--base <ref>` | The older version: a label (`2.0.0` or `v2.0.0`), a revision id, or a version tag. Default: the most recent **published** version older than `--head`. |
| `--head <ref>` | The newer version. Default: the project's latest version. |
| `--severity error\|warn\|info` | Show findings at this level or above. Display only — the exit code still counts every breaking change. |
| `--allow-removals` | Treat breaking **removals** (a removed path, operation, property or schema) as warnings, so they do not fail the gate. |
| `--ignore <rule>` | Skip a rule, e.g. `--ignore path_removed`. Repeat it or comma-separate; `removed-path` is accepted too. |
| `--json` | One JSON document: both sides, `breaking`, `exitCode`, and every finding with its `rule`, `severity`, `kind`, `path` and `suppressedBy`. |
| `--sarif` | SARIF 2.1.0 for GitHub code scanning. Suppressed findings are kept, marked as suppressed. |

Severity comes from the engine's classification: **breaking** → `error`, **unknown** (a change it
cannot prove safe, such as a possible rename or a changed pattern) → `warn`, **safe** → `info`.
Rule ids include `path_removed`, `operation_removed`, `schema_removed`, `property_removed`,
`required_field_added`, `enum_narrowed`, `json_type_change`, `possible_rename` and their `_added`
counterparts.

## GitHub Actions

```yaml
name: API compatibility
on: [pull_request]
jobs:
  compatibility:
    runs-on: ubuntu-latest
    permissions:
      security-events: write   # for the SARIF upload
    steps:
      - name: Install the apiome CLI
        run: curl -fsSL https://get.apio.me | bash
      - name: Check for breaking changes
        env:
          APIOME_API_KEY: ${{ secrets.APIOME_API_KEY }}
          APIOME_BASE_URL: https://api.apiome.dev
          APIOME_TENANT_ID: acme
        run: apiome versions compatibility payments-api --sarif > compatibility.sarif
      - name: Upload to code scanning
        if: always()
        uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: compatibility.sarif
```

The check step fails the job on exit `6` (or `8`); the upload step runs either way, so the
findings appear under **Security → Code scanning**.

## GitLab CI

```yaml
api-compatibility:
  image: python:3.12
  script:
    - curl -fsSL https://get.apio.me | bash
    - apiome --json versions compatibility payments-api > compatibility.json
  artifacts:
    when: always
    paths: [compatibility.json]
```

Set `APIOME_API_KEY`, `APIOME_BASE_URL` and `APIOME_TENANT_ID` as masked CI/CD variables.

## Related

- [CI contract gate on GitHub](./ci-diff-gate.md) — gate a local file with `apiome diff`
- [Versions](../../build/versions.mdx) — the versions being compared
- [`versions` command reference](../cli/versions.md)
