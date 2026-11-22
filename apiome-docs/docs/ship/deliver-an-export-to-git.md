---
title: Deliver an export to a git repository
description: Send a finished export to a repository as a pull request or a commit.
sidebar_position: 5.25
---

An export ends with a file to download. When the specs belong in a repository instead, Apiome can
deliver the export there: the bundle is written under a directory of the repository, on a branch, with a
**pull request** whose description carries the export's fidelity summary and a link to the full
report. You can also commit **directly** to a branch.

Delivery works on an export job that has finished (see [How an export runs](./export-jobs.mdx)). To
compare the channels, see [Deliver an export](./deliver-an-export.mdx).

## Before you start

- **A repository registered through a linked account** on GitHub, GitLab, Bitbucket or Azure DevOps (see
  [Repositories](../bring-in/repositories.mdx)). The delivery pushes with that account's existing
  credential, so the account needs write access to the repository (see
  [What each provider needs](#what-each-provider-needs)). Apiome stores no other token for delivery.
- **The `versions:publish` permission.** Delivering writes to a repository on the workspace's behalf, the
  same permission opening a PR-back pull request or an SDK delivery needs.
- **A completed export.** A dry run has no files to deliver, and an export whose download has expired
  has to be run again.

## What each provider needs

| Provider | Registered through | The pull request is | The linked account needs |
| --- | --- | --- | --- |
| GitHub | a GitHub account | a pull request | write access: a classic token with the `repo` scope, or a fine-grained token with write access to **Contents** and **Pull requests** |
| GitLab (gitlab.com) | a GitLab account | a merge request | the `api` scope, and at least the **Developer** role on the project |
| Bitbucket Cloud | a Bitbucket account | a pull request | an OAuth consumer with **Repositories: Write** and **Pull requests: Write**, and write access to the repository |
| Azure DevOps | a Microsoft account | a pull request | a token issued for Azure DevOps with the **Code (read and write)** scope (`vso.code_write`), and **Contribute**, **Create branch** and **Contribute to pull requests** on the repository; **Force push** on `apiome/export-*` branches to rebuild them |

The delivery works the same way on all four. A few things differ, because each host writes commits its
own way:

- **GitLab** has no "only if the branch has not moved" commit. In direct-commit mode Apiome checks that
  the branch still points at the commit it read just before it writes, so the window for a concurrent
  push is a fraction of a second rather than the whole delivery.
- **Bitbucket** cannot move a branch to another commit. To rebuild a delivery branch, Apiome deletes it
  and writes it again from the base branch. If Bitbucket declines the open pull request when the branch
  is deleted, Apiome opens a new one, and the run reports the new number.
- **Azure DevOps** keeps at most 4,000 characters of a pull request description. A longer description is
  shortened, and the full fidelity report stays one click away through its link. Because the shortened
  text never matches the full one, a re-delivery with nothing new reports `updated` rather than
  `unchanged`.
- On **GitLab, Bitbucket and Azure DevOps**, every commit Apiome writes ends with an `Apiome-Tree:` line.
  It names the exact content Apiome committed, so a re-delivery can tell that the branch already holds
  this export without writing anything.

## Deliver an export

Send the job's id, the repository and where the files go:

```bash
curl -X POST "$APIOME/v1/export/acme/jobs/$JOB_ID/deliveries/git" \
  -H "Authorization: Bearer $APIOME_API_KEY" -H "Content-Type: application/json" \
  -d '{"repositoryId": "<repository id>", "targetPath": "specs/orders", "mode": "pr"}'
```

| Field | What it does |
| --- | --- |
| `repositoryId` | The registered repository to deliver to. |
| `targetPath` | The directory the bundle is written under. Empty means the repository root. |
| `baseBranch` | The branch the pull request targets, or the commit lands on. Empty means the repository's default branch. |
| `mode` | `pr` (the default) opens or updates a pull request. `commit` commits straight onto the base branch. |

The answer is the delivery run: its `status`, the branch, the commit, the pull request's number and
link, the changed files and the event log. Every field is in the
[export delivery reference](/reference/rest/export-delivery).

## What lands in the repository

- **Every file the export produced, at its path in the bundle.** A multi-file bundle keeps its directory
  tree under `targetPath`. A multi-target export keeps one directory per target.
- **A delivery manifest** at `<targetPath>/.apiome/export-delivery.json`, listing the files Apiome wrote
  with their hashes, the export target, the version and the fidelity summary.
- **Nothing else changes.** A later delivery removes a file only when the previous manifest listed it and
  the export no longer produces it. Files Apiome did not write, such as a README or a CI workflow, are
  never touched.

## Pull request mode

The bundle is committed on a branch named after the artifact, the target and the path, for example
`apiome/export-orders-openapi-3.1-3f2a9c`, built on the latest base branch. The pull request's
description shows:

- the **fidelity summary**: the tier, the preserved share, and how many constructs were dropped,
  approximated or made up, with the report's headline;
- a link that **opens the full fidelity report** in Export studio;
- the **changed files**, and the export job, revision and snapshot it came from.

**A re-export updates the same pull request.** Deliver a new export of the same artifact and target to
the same path, and the branch is rebuilt and the open pull request updated. A second one is never opened.
The run's `status` says what happened:

| Status | Meaning |
| --- | --- |
| `opened` | A pull request was opened. |
| `updated` | The open pull request got a new commit, or a refreshed description. |
| `unchanged` | The open pull request already carries exactly this export; nothing was written. |
| `up_to_date` | The base branch already holds these files; nothing was written. |

The branch is Apiome's: each delivery rebuilds it on the base branch, so do not push your own commits
to it.

## Direct-commit mode

With `"mode": "commit"`, the bundle is committed straight onto the base branch with a status of
`committed`, and no pull request is opened. The commit only **fast-forwards** the branch. If the branch
moved while the delivery ran, or a branch protection rule refuses direct pushes, the delivery fails
rather than discard anyone's work. Deliver again, or use pull request mode. A base branch that already
holds the files is `up_to_date`.

## When a delivery fails

A delivery that cannot finish still answers with a run, `status: failed`, a stable `errorCode` and a log
that says what to do. The repository token never appears in the log.

| `errorCode` | What to do |
| --- | --- |
| `export-git-delivery-credential-missing` | The account that registered the repository is no longer linked. Re-link it, or register the repository through an account that can write to it. |
| `export-git-delivery-credential-rejected` | The provider refused the token: it expired, was revoked, or (Azure DevOps) was not issued for Azure DevOps. Re-link the account. |
| `export-git-delivery-permission-denied` | The account can read the repository but not push to it. Grant it what [its provider needs](#what-each-provider-needs). |
| `export-git-delivery-repository-unlinked` | The repository was registered from a public URL. Register it through a linked account. |
| `export-git-delivery-provider-unsupported` | The repository is not on GitHub, GitLab, Bitbucket or Azure DevOps. |
| `export-git-delivery-repository-invalid` | The repository's name on record does not have its provider's shape. Register it again through its linked account. |
| `export-git-delivery-target-path-invalid` | `targetPath` names a file in the repository, not a directory. |
| `export-git-delivery-tree-too-large` | The target directory holds too many files to list (Bitbucket: more than 1,000). Deliver into a dedicated directory. |
| `export-git-delivery-base-branch-missing` | The base branch does not exist. Create it, or name another. |
| `export-git-delivery-push-rejected` | A branch rule refused the push, or (direct-commit mode) the branch moved. On Azure DevOps, rebuilding a delivery branch also needs the **Force push** permission. |

An unfinished job answers `409` and an expired download `410`; run the export again, then deliver it.

## See past deliveries

`GET /v1/export/{tenant}/jobs/{job_id}/deliveries/git` lists a job's deliveries, newest first. Every
delivery is also written to the audit log as `export.git_delivery`.
