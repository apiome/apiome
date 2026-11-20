# apiome/diff-action

GitHub Action that runs [`apiome diff`](../apiome-cli/README.md) as a PR contract
gate (CTG-2.2 / #4472).

- Fails the check when the CLI exits `1` (threshold met)
- Passes on exit `0`
- Surfaces operational errors (`2`) with `::error::`
- Upserts **one sticky PR comment** with the markdown changelog (`--format md`)
- Says what each breaking change affects in the dependency graph (`--blast-radius`, on by default)
- Grades by the baseline project's compatibility policy, or by the `mode`, `transitive` and
  `category` inputs (XPC-4.5)
- Suggests the spec's mechanical lint fixes in the same comment, as one-click GitHub suggestion
  blocks where it can, with the full patch and overlay for a workflow artefact (GVM-3.4); nothing
  is ever pushed to the branch

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
      - uses: actions/checkout@v7
      - uses: apiome/apiome/diff-action@main
        with:
          spec: openapi.yaml
          project: payments-api@latest
          fail-on: breaking
          api-key: ${{ secrets.APIOME_API_KEY }}
          tenant: ${{ secrets.APIOME_TENANT_ID }}
          base-url: ${{ vars.APIOME_BASE_URL }}
```

Full guide: [`apiome-docs/docs/reference/ci/ci-diff-gate.md`](../apiome-docs/docs/reference/ci/ci-diff-gate.md).

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `spec` | yes | — | Candidate file path: OpenAPI, or the baseline's own format (Avro, JSON Schema, AsyncAPI, Protobuf) |
| `project` | yes | — | `--against` value (`project@version\|latest`) |
| `fail-on` | no | `breaking` | `breaking` or `warn` |
| `api-key` | yes | — | Apiome API key |
| `tenant` | yes | — | Tenant slug or UUID |
| `base-url` | no | `https://api.apiome.dev` | REST base URL |
| `github-token` | no | `${{ github.token }}` | Token for sticky PR comments |
| `comment` | no | `true` | Set `false` to skip the PR comment |
| `blast-radius` | no | `true` | Add the blast-radius line under each breaking change; set `false` to leave it out. Needs `projects:view` |
| `mode` | no | — | Compatibility mode: `backward`, `forward`, `full` or `none`, optionally with `_transitive`. Empty uses the project's policy |
| `transitive` | no | — | `true` also compares against every earlier version of the baseline; `false` only against the baseline. Empty uses the project's policy |
| `category` | no | — | Protobuf breaking category: `wire`, `wire_json`, `package` or `file`. Empty uses the project's policy |
| `fix-suggestions` | no | `true` | Add the *Suggested fixes* section, post suggestion blocks and write the fix patch and overlay; set `false` to leave fixes out. Never changes the check result |

## Compatibility mode

Left empty, `mode`, `transitive` and `category` come from the baseline project's style-guide
policy, so the gate and the API always agree. Set them to override the policy for one workflow:

```yaml
      - uses: apiome/apiome/diff-action@main
        with:
          spec: schemas/order-created.avsc
          project: orders-events@latest
          mode: full
          transitive: "true"
          api-key: ${{ secrets.APIOME_API_KEY }}
          tenant: ${{ secrets.APIOME_TENANT_ID }}
```

The mode applies to Avro, JSON Schema and AsyncAPI baselines, and `category` to Protobuf ones. For
those, `spec` is read as the baseline's format. When a mode, category or transitive check was
applied, the comment ends with what the changes were graded under:

```markdown
_Graded under `FULL_TRANSITIVE` by avro-compatibility, against 2.0.0, 1.0.0._
```

An unknown `mode` or `category` fails the step with exit `2`, as does a `transitive` other than
`true`, `false` or empty.

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

## Suggested fixes

With `fix-suggestions` on (the default), the action runs
[`apiome lint suggest`](../cli/lint.md) on `spec` and adds a second section to the same sticky
comment. The section lists, per rule, how many fixes are ready, the fix class and the first hunk:

````markdown
### Suggested fixes

2 mechanical fixes ready for `api/openapi.yaml`; nothing is pushed to the branch.

- `structure.duplicate-tag` — 2 fixes (removal)

```diff
@@ -5,4 +5,3 @@
 tags:
   - name: orders
-  - name: orders
 paths:
```

Download the full patch and overlay: [workflow artefacts](https://github.com/…/actions/runs/…#artifacts).
````

- **One comment.** The changelog and the fixes are two marked sections
  (`<!-- apiome-diff-action:diff -->` and `<!-- apiome-diff-action:fixes -->`) of the one sticky
  comment. Each run replaces each section in place, so the diff and the fixes update independently.
- **Suggestion blocks.** A fix that changes one region of the spec, on lines the pull request
  changes, is also posted as a review comment with a GitHub `suggestion` block. The reviewer accepts
  it with **Commit suggestion**. Every other fix stays a plain snippet in the sticky comment. A fix
  is suggested once per pull request: later runs skip fix ids that already have a review comment.
- **The artefact.** The full change is written to `.apiome-lint-fixes.patch.json` (RFC 6902) and
  `.apiome-lint-fixes.overlay.json` (Overlay 1.0), as the `fix-patch-path` and `fix-overlay-path`
  outputs. The patch holds the same bytes as `apiome lint suggest <spec> --format patch`. The
  comment links the run's artefacts, so add an upload step after the action:

```yaml
      - uses: apiome/apiome/diff-action@main
        id: gate
        with:
          spec: api/openapi.yaml
          project: payments-api@latest
          api-key: ${{ secrets.APIOME_API_KEY }}
          tenant: ${{ secrets.APIOME_TENANT_ID }}
      - uses: actions/upload-artifact@v7
        if: always()
        with:
          name: apiome-lint-fixes
          path: |
            ${{ steps.gate.outputs.fix-patch-path }}
            ${{ steps.gate.outputs.fix-overlay-path }}
          if-no-files-found: ignore
```

Suggested fixes never change the check result. When the spec is not OpenAPI 3.x, or the fixes
cannot be planned, the section says so and the gate result stands.

## Outputs

| Output | Description |
|--------|-------------|
| `exit-code` | CLI exit code (`0` / `1` / `2`) |
| `changelog-path` | Workspace-relative path to the markdown changelog |
| `fix-count` | Number of ready lint fixes suggested for `spec` (empty when they could not be computed) |
| `fix-patch-path` | Workspace-relative path to the full fix patch (RFC 6902) |
| `fix-overlay-path` | Workspace-relative path to the same change as an Overlay 1.0 document |

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

Copy-paste pipelines live in [`recipes/`](recipes/):

| File | Platform |
|---|---|
| [`recipes/.gitlab-ci.yml`](recipes/.gitlab-ci.yml) | GitLab CI |
| [`recipes/bitbucket-pipelines.yml`](recipes/bitbucket-pipelines.yml) | Bitbucket Pipelines |

Guide: [`apiome-docs/docs/reference/ci/ci-gitlab-bitbucket.md`](../apiome-docs/docs/reference/ci/ci-gitlab-bitbucket.md). The guide
embeds those files verbatim and `tests/test_ci_recipes.sh` fails if either copy drifts.

## Develop / test

```bash
cd diff-action
bash tests/run.sh                                  # everything
bash tests/test_ci_recipes.sh --recipe gitlab      # one recipe (as CI's matrix runs it)
bash -n entrypoint.sh ci_entrypoint.sh sticky_comment.sh fix_suggestions.sh tests/*.sh
```

The recipe smoke test extracts each recipe's `variables:` / `script:` blocks and runs them
under `set -e` against a stub CLI, asserting exit-code propagation (`0`/`1`/`2`), the changelog
artifact, and fail-fast behaviour when a credential is missing.
CI: [`.github/workflows/diff-action.yml`](../.github/workflows/diff-action.yml).
