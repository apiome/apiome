---
title: "pact-action (GitHub Action)"
description: "Inputs, outputs and behaviour of the apiome/pact-action publish, can-i-deploy and record-deployment steps."
sidebar_position: 5
tags: [ci, reference]
generated: apiome-docs/scripts/sync-action-pages.mjs from pact-action/README.md
---

> This page is `pact-action/README.md`, copied by `yarn workspace apiome-docs sync:action-pages` — edit the README, not this page.

GitHub Action that runs the three Pact steps of a pipeline against your Apiome workspace's Pact
Broker (PFX-4.3 / #6940), with the [`apiome pact` commands](../../ship/pact-broker/cli.mdx):

- **`publish`** — publishes the consumer's pacts for the commit and its branch, with a link to the run
- **`can-i-deploy`** — gates a pull request or a deploy on the broker's verdict, and keeps **one
  sticky PR comment** with the answer up to date
- **`record-deployment`** — records what was deployed, after the deploy, on merge

Every step exits like `pact-broker`: `0` when it worked (or the version can be deployed), `1`
otherwise. Wrong or missing inputs are refused with the reason before anything is sent. The runner
needs `bash`, `curl` and `jq`; GitHub-hosted runners have all three.

## Usage

```yaml
name: pact
on:
  pull_request:
  push:
    branches: [main]
permissions:
  contents: read
  pull-requests: write
jobs:
  pact:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: npm ci && npm run test:pact          # writes ./pacts

      - uses: apiome/apiome/pact-action@main
        with:
          command: publish
          broker-base-url: ${{ secrets.PACT_BROKER_BASE_URL }}
          broker-token: ${{ secrets.PACT_BROKER_TOKEN }}

      - uses: apiome/apiome/pact-action@main
        with:
          command: can-i-deploy
          pacticipant: Billing Service
          environment: production
          retry-while-unknown: "12"
          broker-base-url: ${{ secrets.PACT_BROKER_BASE_URL }}
          broker-token: ${{ secrets.PACT_BROKER_TOKEN }}

      - if: github.event_name == 'push'
        run: ./deploy.sh production

      - if: github.event_name == 'push'
        uses: apiome/apiome/pact-action@main
        with:
          command: record-deployment
          pacticipant: Billing Service
          environment: production
          broker-base-url: ${{ secrets.PACT_BROKER_BASE_URL }}
          broker-token: ${{ secrets.PACT_BROKER_TOKEN }}
```

`PACT_BROKER_BASE_URL` is your workspace's broker base URL, such as
`https://api.apiome.dev/v1/tenants/acme/pact-broker`. `PACT_BROKER_TOKEN` is an API key with the
**Pact: consumer + deploy** preset; a job that only asks `can-i-deploy` needs **Pact: read-only**.
When the job already sets `PACT_BROKER_BASE_URL` and `PACT_BROKER_TOKEN` in `env:`, leave the two
inputs out.

Full guide: [Run Pact in CI](../../ship/pact-broker/ci-pact.mdx), which also has the
GitLab CI and Bitbucket Pipelines [recipes](../../ship/pact-broker/ci-pact.mdx).

## Inputs

| Input | Used by | Default | Description |
|-------|---------|---------|-------------|
| `command` | all | *(required)* | `publish`, `can-i-deploy` or `record-deployment`. Anything else is refused; run other `apiome pact` commands in a `run:` step |
| `broker-base-url` | all | `PACT_BROKER_BASE_URL` | The workspace's broker base URL (http or https) |
| `broker-token` | all | `PACT_BROKER_TOKEN` | API key with the Pact scopes the command needs. Passed to the CLI in the environment, never on its command line. `PACT_BROKER_PASSWORD` also works |
| `pacts` | `publish` | `pacts` | Pact files or folders of pact files, one per line. A path that does not exist is refused |
| `pacticipant` | `can-i-deploy`, `record-deployment` | — | The application being deployed (required) |
| `version` | all | the PR's head commit, or the commit the workflow runs on | The application version |
| `branch` | `publish` | the PR's head branch, or the branch the workflow runs on | The branch the version came from |
| `tags` | `publish` | — | Tags for the consumer version, one per line |
| `environment` | `can-i-deploy`, `record-deployment` | — | The environment's name, such as `production` (required) |
| `application-instance` | `record-deployment` | — | The instance deployed to (a region, a customer) |
| `retry-while-unknown` | `can-i-deploy` | `0` | Retry this many times while a verification result is missing |
| `retry-interval` | `can-i-deploy` | `10` | Seconds between retries |
| `dry-run` | `can-i-deploy` | `false` | `true` reports the verdict but never fails the step |
| `comment` | `publish`, `can-i-deploy` | `true` | `false` skips the sticky PR comment |
| `comment-id` | `publish`, `can-i-deploy` | — | Tells comments apart when one PR runs the same command more than once |
| `github-token` | `publish`, `can-i-deploy` | `${{ github.token }}` | Token for the sticky comment (needs `pull-requests: write`) |
| `install` | all | `true` | Install the Apiome CLI unless `apiome` is already on `PATH`; `false` when an earlier step installs it |
| `cli-version` | all | `main` | Git tag, branch or commit of the CLI to install. Pin a tag in real pipelines |

## Outputs

| Output | Description |
|--------|-------------|
| `exit-code` | The command's exit code: `0` it worked (or deployable), `1` anything else |
| `report-path` | `apiome-pact-<command>.md` in the workspace: the command's markdown output |
| `deployable` | `can-i-deploy` only: `true` or `false`; empty when the check could not run |

## What it does

1. **Installs the CLI** with the installer from `https://get.apiome.dev` for the runner user
   (`~/.local/bin`, no sudo), unless `apiome` is already on `PATH`.
2. **Runs one command** with `--output markdown`, writes the output to `apiome-pact-<command>.md`
   and prints it in the log.
3. **Writes the job summary**: a heading with the verdict, the command's output and any messages
   it printed.
4. **Upserts one sticky PR comment** for `publish` and `can-i-deploy` on a pull request. The comment
   is found again by a hidden marker made of the command, the pacticipant and the environment (or
   `comment-id`), so each gate keeps one comment however many times the PR is pushed. A comment that
   cannot be posted is a warning; it never changes the step's result. Outside a pull request no
   comment is posted.

## What it refuses

Each refusal is an error annotation with the reason, exits `1`, and sends nothing:

| Refused | Why |
|---------|-----|
| A `command` other than the three | The action covers the pipeline's three steps; the rest of `apiome pact` runs in a `run:` step |
| No broker URL or token, or a URL that is not http(s) | The step cannot reach your workspace |
| `can-i-deploy` or `record-deployment` without `pacticipant` or `environment` | The broker needs both to answer |
| `retry-while-unknown`, `retry-interval`, `dry-run` or `comment` with a value of the wrong kind | No guessing what was meant |
| An empty `pacts`, or a path that does not exist | Usually the Pact tests did not run before the step |
| `record-deployment` in a `pull_request` or `pull_request_target` run | Recording it would tell `can-i-deploy` the PR's commit is live; run it on push to your main branch |

## Tests

```bash
bash pact-action/tests/run.sh                          # every test
bash pact-action/tests/test_ci_recipes.sh --recipe gitlab
```

`test_ci_recipes.sh` runs each job of the GitLab and Bitbucket recipes against a stub CLI and checks
that the guide embeds each recipe byte for byte.
