---
title: "Migration plans and version tags from the CLI"
description: "Inspect migration plans and manage version tags with apiome migrations and apiome tags."
sidebar_position: 2.15
tags: [versions, cli, ci]
---

Two small surfaces sit beside a project's versions, and the CLI covers both:

- A **migration plan** holds the rules that move data from one version of a project to another —
  one plan per pair of versions, with rules per class (`Charge.legacy_status → Charge.status`).
  `apiome migrations` lists, counts and shows plans. It is read-only.
- A **version tag** (`stable`, `latest`, `prod` …) is a named pointer to one version of a project.
  Tags float: promoting a release is moving a tag, not changing a version. `apiome tags` lists,
  shows, creates, moves and deletes them.

Every command calls the REST surfaces under `/v1/migration-plans/{tenant_slug}` and
`/v1/version-tags/{tenant_slug}/{project_id}` with your API key, so a script or CI job can do the
same as a person at a terminal.

Use it when you:
- promote a release in CI by moving `stable` to the version you just published;
- check who may be affected before you move a tag consumers follow;
- audit which version pairs of a project have migration rules, and how many;
- read one plan's mappings while you upgrade a consumer from one version to the next.

## Before you start

- **Install** the CLI and **sign in**: see [Install the CLI](../reference/install-the-cli.md) and the
  [CLI quick-start](../reference/cli-quickstart.md). In CI, set `APIOME_API_KEY`,
  `APIOME_BASE_URL` and `APIOME_TENANT_ID` instead of signing in.
- A project is named by its **slug** (`payments-api`) or UUID. A version is named by its **label**
  (`2.1.0` or `v2.1.0`) or revision UUID; `migrations list --from` / `--to` also take a tag.
- Put `--json` before the command (`apiome --json tags show …`) to get machine-readable output.

## The commands

| Command | What it does | REST |
| --- | --- | --- |
| `apiome migrations list --project <project>` | A project's plans, newest first; `--from` / `--to` narrow it to one version pair | `GET /v1/migration-plans/{tenant}/projects/{project}` |
| `apiome migrations counts` | Plans, distinct classes and rules per project, most plans first | `GET /v1/migration-plans/{tenant}/projects/{project}` |
| `apiome migrations show <plan-id>` | One plan: project, from and to versions, dates and every mapping | `GET /v1/migration-plans/{tenant}/{plan_id}` |
| `apiome tags list <project>` | A project's tags, the version each points to, its channel and creator | `GET /v1/version-tags/{tenant}/{project}` |
| `apiome tags show <project> <tag>` | One tag in full, including whether it is immutable or protected | `GET /v1/version-tags/{tenant}/{project}` |
| `apiome tags create <project> <tag> --version 2.1.0` | Point a new tag at a version | `POST /v1/version-tags/{tenant}/{project}` |
| `apiome tags update <project> <tag> --version 2.2.0` | Move a tag, after showing who may be affected | `PATCH …/{tag_id}` |
| `apiome tags delete <project> <tag>` | Delete a tag after you type its name; the version is not touched | `DELETE …/{tag_id}` |

Every option is listed in the [`apiome migrations`](../reference/cli/migrations.md) and
[`apiome tags`](../reference/cli/tags.md) references, with worked examples on
[Versions](../build/versions.mdx#list-version-tags-from-the-cli).

## Promote a release with a tag

The usual flow, by hand or in CI, after [publishing](./publish-a-version.md) `2.2.0`:

```bash
apiome tags list payments-api
apiome tags update payments-api stable --version v2.2.0 --dry-run
apiome tags update payments-api stable --version v2.2.0 --yes
```

1. **List** the tags to see where `stable` points now.
2. **Dry-run** the move. It shows the current version and, best-effort, who may be affected: mock
   requests in the last 7 days, downloads of its frozen snapshot and the other tags on it. A figure
   Apiome cannot read shows as *unavailable* and never stops the move.
3. **Move** it. In a script, `--yes` skips the question.

A tag that does not exist yet is made with `apiome tags create payments-api stable --version v2.2.0`.
Tag names are lower-cased, 2–41 characters: a letter, then letters, digits or hyphens. Creating a
name the project already has exits `6` — move it with `tags update` instead.

### Locked tags

- An **immutable** tag can never be moved or deleted; `tags update` and `tags delete` exit `6`.
  `tags create` asks before it makes one (`--yes` skips the question).
- A **protected** tag can be deleted only by a tenant administrator.
- Apiome keeps only a tag's current pointer and who created it, so there is no move history.

[Unpublishing](./publish-a-version.md#unpublish-a-version) a version moves its tags back to the
previous published version, unless you pass `--keep-tags`.

## Read migration plans

```bash
apiome migrations counts
apiome migrations list --project payments-api --from v2.0.0 --to stable
apiome migrations show 3a910000-0000-4000-8000-00000000b41c --scope mappings
```

1. **Count** plans per project to see where migration rules exist.
2. **List** one project's plans, narrowed to the version pair you care about. A version can be a
   label, a revision id or a tag; one the project does not have exits `2`.
3. **Show** a plan by the id in the **PLAN ID** column. Each mapping reads
   **source → target (rule type · rule name)**; a rule with no target reads `(removed)`.

Apiome records no status, breaking-change flag, author or notes for a migration plan, so none of
the commands show or filter on them. The CLI does not create or edit plans.

## Exit codes

| Exit | When |
| --- | --- |
| `0` | Done |
| `2` | A version, tag or plan was not found, a plan id is not a UUID, or `--from-file` cannot be read |
| `6` | A tag name already exists, or an immutable tag was moved or deleted |

The full list is on [Exit codes](../reference/cli/exit-codes.md).

## Where next

- [Manage versions from the CLI](./manage-versions-from-the-cli.md) — cut, publish and freeze the
  versions tags point at.
- [Version tags REST API](../reference/rest/version-tags.md) and
  [Migration plans REST API](../reference/rest/migration-plans.md).
