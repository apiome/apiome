---
title: "diff-action (GitHub Action)"
description: "Inputs, outputs and behaviour of the apiome/diff-action pull-request contract gate."
sidebar_position: 3
tags: [ci, reference]
generated: apiome-docs/scripts/sync-action-pages.mjs from diff-action/README.md
---

> This page is [`diff-action/README.md`](https://github.com/apiome/apiome/blob/main/diff-action/README.md), copied by `yarn workspace apiome-docs sync:action-pages` — edit the README, not this page.

GitHub Action that runs [`apiome diff`](https://github.com/apiome/apiome/blob/main/apiome-cli/README.md) as a PR contract
gate (CTG-2.2 / #4472).

- Fails the check when the CLI exits `1` (threshold met)
- Passes on exit `0`
- Surfaces operational errors (`2`) with `::error::`
- Upserts **one sticky PR comment** with the markdown changelog (`--format md`)
- Says what each breaking change affects in the dependency graph (`--blast-radius`, on by default)

## Usage

```yaml
name: Apiome contract gate
on: pull_request
permissions:
  contents: read
  pull-requests: write
jobs:
  diff:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: apiome/apiome/diff-action@main
        with:
          spec: openapi.yaml
          project: payments-api@latest
          fail-on: breaking
          api-key: ${{ secrets.APIOME_API_KEY }}
          tenant: ${{ secrets.APIOME_TENANT_ID }}
          base-url: ${{ vars.APIOME_BASE_URL }}
```

Full guide: [`apiome-docs/docs/reference/ci/ci-diff-gate.md`](ci-diff-gate.md).

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `spec` | yes | — | Candidate OpenAPI file path |
| `project` | yes | — | `--against` value (`project@version\|latest`) |
| `fail-on` | no | `breaking` | `breaking` or `warn` |
| `api-key` | yes | — | Apiome API key |
| `tenant` | yes | — | Tenant slug or UUID |
| `base-url` | no | `https://api.apiome.dev` | REST base URL |
| `github-token` | no | `${{ github.token }}` | Token for sticky PR comments |
| `comment` | no | `true` | Set `false` to skip the PR comment |
| `blast-radius` | no | `true` | Add the blast-radius line under each breaking change; set `false` to leave it out. Needs `projects:view` |

## The PR comment

The comment is the markdown changelog. With `blast-radius` on (the default), each breaking change
gets a line under it from the change's blast radius against the baseline project:

```markdown
- **Path removed** (`ctg.path_removed`) — `/paths/~1pets~1{petId}`
  - Blast radius: affects 4 consumers across 2 teams (mobile, payments); 2 verification runs invalidated
```

- **Consumers** are those that depend on the change, directly or through another consumer.
- **Teams** are those consumers' owner teams, named.
- **Verification runs** are the latest runs that exercised an affected operation.

A change nobody depends on reads `affects no registered consumers; no verification runs
invalidated`. At most 50 breaking changes per diff get a line; the comment says how many more were
not checked. The gate threshold does not change: `fail-on` still grades the whole specification.

## Outputs

| Output | Description |
|--------|-------------|
| `exit-code` | CLI exit code (`0` / `1` / `2`) |
| `changelog-path` | Workspace-relative path to the markdown changelog |

## Container image & non-GitHub CI (CTG-2.4)

The image is dual-mode, so the same artifact backs every platform:

| Invocation | Mode |
|---|---|
| no arguments | GitHub Action (`INPUT_*` env vars) — `entrypoint.sh` |
| any arguments | pass-through to the `apiome` CLI — `ci_entrypoint.sh` |

```bash
docker run --rm \
  -e APIOME_API_KEY -e APIOME_TENANT_ID -e APIOME_BASE_URL \
  -v "$PWD:/work" -w /work \
  ghcr.io/apiome/diff-action:latest \
  diff ./openapi.yaml --against payments-api@latest --fail-on breaking --format md
```

The pass-through mode validates `APIOME_API_KEY` / `APIOME_TENANT_ID` (exit `2`,
never `1`), defaults `APIOME_BASE_URL`, forces `APIOME_LOAD_DOTENV=0` so a committed
`.env` cannot override CI variables, and tolerates a repeated `apiome` binary name
(`… <image> apiome diff …`). `--help` / `--version` need no credentials.

Copy-paste pipelines live in [`recipes/`](https://github.com/apiome/apiome/blob/main/diff-action/recipes/):

| File | Platform |
|---|---|
| [`recipes/.gitlab-ci.yml`](https://github.com/apiome/apiome/blob/main/diff-action/recipes/.gitlab-ci.yml) | GitLab CI |
| [`recipes/bitbucket-pipelines.yml`](https://github.com/apiome/apiome/blob/main/diff-action/recipes/bitbucket-pipelines.yml) | Bitbucket Pipelines |

Guide: [`apiome-docs/docs/reference/ci/ci-gitlab-bitbucket.md`](ci-gitlab-bitbucket.md). The guide
embeds those files verbatim and `tests/test_ci_recipes.sh` fails if either copy drifts.

## Develop / test

```bash
cd diff-action
bash tests/run.sh                                  # everything
bash tests/test_ci_recipes.sh --recipe gitlab      # one recipe (as CI's matrix runs it)
bash -n entrypoint.sh ci_entrypoint.sh sticky_comment.sh tests/*.sh
```

The recipe smoke test extracts each recipe's `variables:` / `script:` blocks and runs them
under `set -e` against a stub CLI, asserting exit-code propagation (`0`/`1`/`2`), the changelog
artifact, and fail-fast behaviour when a credential is missing.
CI: [`.github/workflows/diff-action.yml`](https://github.com/apiome/apiome/blob/main/.github/workflows/diff-action.yml).
