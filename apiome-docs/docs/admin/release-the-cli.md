---
title: Release the CLI
description: "Changesets, the release pull request and GitHub releases for apiome-cli."
sidebar_position: 14
tags: [cli, releases]
---

The Apiome CLI (`apiome-cli/`, npm name `@apiome/cli`) is versioned with
[changesets](https://github.com/changesets/changesets). Nobody edits its version by hand: each pull
request describes its change in a small **changeset** file, a maintainer turns the pending
changesets into a version bump and a changelog entry with one command, and the release itself is
published on GitHub.

```text
your pull request ──merge──▶ Release: apiome-cli vX.Y.Z ──merge──▶ GitHub release, tag cli-vX.Y.Z
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

When you want to ship the changesets that have merged to `main`, open the release pull request
yourself — no workflow opens it for you:

1. From an up-to-date `main`, create a branch whose name starts with `changeset-release/`, for
   example `changeset-release/v0.143.0`. The changeset check passes such a branch without a
   changeset of its own.
2. At the repository root, run:

   ```bash
   yarn workspace @apiome/cli release:version
   ```

   It:

   - sets the new version in `apiome-cli/package.json`, `apiome-cli/pyproject.toml` and
     `apiome-cli/uv.lock`, so `apiome --version` reports it;
   - adds the changesets' notes to `apiome-cli/CHANGELOG.md` under the new version; and
   - deletes the changeset files it used.

3. Commit the result, open a pull request titled **Release: apiome-cli vX.Y.Z** and merge it once
   its checks pass.

## The GitHub release

After the release pull request merges, publish the release on GitHub:

1. Open **Releases → Draft a new release** in the repository.
2. Under **Choose a tag**, type **`cli-vX.Y.Z`** — the version now in `apiome-cli/package.json` —
   and pick **Create new tag on publish**. Keep the target as `main`.
3. Title it **apiome-cli vX.Y.Z** and paste that version's section of `apiome-cli/CHANGELOG.md` as
   the description.
4. For a release candidate, tick **Set as a pre-release**.
5. Select **Publish release**. GitHub creates the tag.

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

2. Merge pull requests with changesets as usual. `release:version` now produces `X.Y.Z-rc.0`, then
   `X.Y.Z-rc.1`, and so on; tag each GitHub release `cli-vX.Y.Z-rc.N`. In `pyproject.toml` the
   same version is written the Python way, `X.Y.Zrc0`.
3. When the candidate is good, leave pre-release mode and commit the change:

   ```bash
   npx changeset pre exit
   ```

   The next `release:version` run produces the stable `X.Y.Z`.

Use `rc`, `beta` or `alpha` as the pre-release name; Python versions have no spelling for others.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| The changeset check fails on a docs-only change. | Add the `no-cli-release` label. |
| `npx changeset` does not list `@apiome/cli`. | Run `yarn install` at the repository root first. |
| `release:version` changes nothing. | No changeset is pending, or none names `"@apiome/cli"`. Run `npx changeset status` in `apiome-cli/`. |
| The changeset check fails on the release pull request. | Its branch name must start with `changeset-release/`. |
| `release:version` fails with "no PEP 440 form". | Pre-release mode uses a name other than `rc`, `beta` or `alpha`; run `npx changeset pre exit` and enter again with `rc`. |
