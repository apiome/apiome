# apiome/diff-action

GitHub Action that runs [`apiome diff`](../apiome-cli/README.md) as a PR contract
gate (CTG-2.2 / #4472).

- Fails the check when the CLI exits `1` (threshold met)
- Passes on exit `0`
- Surfaces operational errors (`2`) with `::error::`
- Upserts **one sticky PR comment** with the markdown changelog (`--format md`)

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

Full guide: [`docs/guide/ci-diff-gate.md`](../docs/guide/ci-diff-gate.md).

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

## Outputs

| Output | Description |
|--------|-------------|
| `exit-code` | CLI exit code (`0` / `1` / `2`) |
| `changelog-path` | Workspace-relative path to the markdown changelog |

## Container image (CTG-2.4)

The Dockerfile installs the CLI and defaults to the Action entrypoint. For bare
pipeline recipes, override the entrypoint:

```bash
docker run --rm --entrypoint apiome \
  -e APIOME_API_KEY -e APIOME_TENANT_ID -e APIOME_BASE_URL \
  -v "$PWD:/work" -w /work \
  ghcr.io/apiome/diff-action:latest \
  diff ./openapi.yaml --against payments-api@latest --fail-on breaking --format md
```

## Develop / test

```bash
cd diff-action
bash tests/run.sh          # or: npm test / node-free: bash -n …
bash -n entrypoint.sh sticky_comment.sh tests/*.sh
```
