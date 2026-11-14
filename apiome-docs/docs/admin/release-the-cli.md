---
title: Release the CLI
description: "Changesets, the release pull request and cli-v tags for apiome-cli."
sidebar_position: 14
tags: [cli, releases]
---

The Apiome CLI (`apiome-cli/`, npm name `@apiome/cli`) is versioned with
[changesets](https://github.com/changesets/changesets). Nobody edits its version by hand: each pull
request describes its change in a small **changeset** file, and a bot pull request turns the
changesets into a version bump, a changelog entry and a git tag.

```text
your pull request ──merge──▶ Release: apiome-cli vX.Y.Z ──merge──▶ tag cli-vX.Y.Z ──▶ publish
 (adds a changeset)          (bumps version, CHANGELOG)
```

## Add a changeset to your pull request

1. In `apiome-cli/`, run:

   ```bash
   npx changeset
   ```

2. Pick **@apiome/cli**, then the bump:

   | Bump | When |
   | --- | --- |
   | `patch` | A fix that changes no command, option or output format. |
   | `minor` | A new command, option or output field; anything users can now do that they could not. |
   | `major` | A removed or renamed command or option, a changed exit code, or output scripts rely on. |

3. Write one or two sentences for the changelog — what changed for someone running `apiome`.
4. Commit the `.changeset/<random-name>.md` file it writes with the rest of your change.

The file looks like this, and you can edit it until the pull request merges:

```markdown
---
"@apiome/cli": minor
---

`apiome data list` takes `--columns` to pick the fields it prints.
```

Several pull requests can each add a changeset; they are released together, at the highest bump
among them.

## The changeset check

The **apiome-cli changeset / Changeset present** check runs on every pull request. It passes when:

- nothing under `apiome-cli/` changed;
- a new or edited `.changeset/*.md` file releases `@apiome/cli` (an empty changeset or one for
  another package does not count); or
- the pull request has the **`no-cli-release`** label — use it for docs-only or test-only changes
  that should not produce a release.

When it fails, the message says what to do: run `npx changeset` or add the label. Adding or
removing the label re-runs the check.

## The release pull request

After a pull request with a changeset merges to `main`, the **apiome-cli release PR** workflow
(`.github/workflows/apiome-cli-release-pr.yml`) opens — or updates — a pull request titled
**Release: apiome-cli vX.Y.Z** on the `changeset-release/main` branch. It:

- sets the new version in `apiome-cli/package.json`, `apiome-cli/pyproject.toml` and
  `apiome-cli/uv.lock`, so `apiome --version` reports it;
- adds the changesets' notes to `apiome-cli/CHANGELOG.md` under the new version; and
- deletes the changeset files it used.

The pull request stays open and collects every later changeset until you merge it. Merge it when you
want to ship.

## The release tag

When the release pull request merges, the same workflow finds no pending changesets and pushes the
tag **`cli-vX.Y.Z`** for the new version. The tag is the hand-off to the CLI publish workflow, which
publishes that version (tracked in #3268). If the tag already
exists the workflow leaves it alone, so re-running it is safe; you can also re-run it by hand from
**Actions → apiome-cli release PR → Run workflow**.

A released version can be installed straight from its tag:

```bash
curl -fsSL https://get.apiome.dev | sh -s -- --version cli-v0.142.0
```

## Pre-releases

To publish release candidates before a stable version:

1. In `apiome-cli/`, enter pre-release mode and commit the `.changeset/pre.json` it writes:

   ```bash
   npx changeset pre enter rc
   ```

2. Merge pull requests with changesets as usual. The release pull request now releases
   `X.Y.Z-rc.0`, then `X.Y.Z-rc.1`, and so on, tagged `cli-vX.Y.Z-rc.N`. In `pyproject.toml` the
   same version is written the Python way, `X.Y.Zrc0`.
3. When the candidate is good, leave pre-release mode and commit the change:

   ```bash
   npx changeset pre exit
   ```

   The next release pull request releases the stable `X.Y.Z`.

Use `rc`, `beta` or `alpha` as the pre-release name; Python versions have no spelling for others.

## Set up the release token

A tag or pull request created with the workflow's default `GITHUB_TOKEN` does not start other
workflows, so the publish workflow and the release pull request's checks would not run. A
repository admin adds a token with **Contents** and **Pull requests** write access (a fine-grained
personal access token or a GitHub App token) as the **`APIOME_RELEASE_TOKEN`** Actions secret. The
workflow uses it when it is set and falls back to `GITHUB_TOKEN` otherwise.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| The changeset check fails on a docs-only change. | Add the `no-cli-release` label. |
| `npx changeset` does not list `@apiome/cli`. | Run `yarn install` at the repository root first. |
| The release pull request did not open. | Check the **apiome-cli release PR** run on `main`; the changeset must name `"@apiome/cli"`. |
| The tag was pushed but no workflow started from it. | Set `APIOME_RELEASE_TOKEN` (see above) and re-run the workflow after deleting the tag. |
| `release:version` fails with "no PEP 440 form". | Pre-release mode uses a name other than `rc`, `beta` or `alpha`; run `npx changeset pre exit` and enter again with `rc`. |
